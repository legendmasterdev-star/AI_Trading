from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Iterable

import pandas as pd

from .indicators import add_indicators
from .mt5_client import MT5Connection, as_dict
from .settings import MARKET_TIMEFRAMES, SYMBOLS


# MetaTrader 5 deal classifiers (mirrors mt5.DEAL_* constants so we do not need
# the package imported here just to filter history).
_DEAL_TYPE_BUY = 0
_DEAL_TYPE_SELL = 1
_DEAL_ENTRY_IN = 0
_DEAL_ENTRY_OUT = 1
_DEAL_ENTRY_OUT_BY = 3


def _clean_number(value):
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    return value


def _deal_net(item: dict) -> float:
    """Net cash impact of a single MT5 deal (profit plus all costs)."""
    return (
        float(item.get("profit") or 0.0)
        + float(item.get("commission") or 0.0)
        + float(item.get("swap") or 0.0)
        + float(item.get("fee") or 0.0)
    )


def _deal_time_iso(timestamp) -> str | None:
    if not timestamp:
        return None
    try:
        return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _forex_session_open(now: datetime) -> bool:
    day = now.weekday()  # Monday = 0, Sunday = 6
    hour = now.hour
    if day == 5:
        return False
    if day == 6 and hour < 22:
        return False
    if day == 4 and hour >= 22:
        return False
    return True


class MarketDataService:
    def __init__(self, connection: MT5Connection | None = None):
        self.connection = connection or MT5Connection()

    def account_snapshot(self) -> dict:
        return self.connection.account_info()

    def tick_info(self, symbol: str) -> dict:
        info = self.connection.symbol_info(symbol)
        tick = self.connection.tick(symbol)
        spread_price = tick.ask - tick.bid
        spread_points = spread_price / info.point if info.point else 0

        return {
            "symbol": symbol,
            "time": datetime.fromtimestamp(tick.time).strftime("%Y-%m-%d %H:%M:%S"),
            "time_epoch": tick.time,
            "time_iso": datetime.fromtimestamp(tick.time, tz=timezone.utc).isoformat(),
            "bid": tick.bid,
            "ask": tick.ask,
            "last": tick.last,
            "volume": tick.volume,
            "spread_price": spread_price,
            "spread_points": round(spread_points, 1),
            "digits": info.digits,
            "point": info.point,
            "trade_mode": info.trade_mode,
        }

    def positions(self, symbol: str | None = None) -> list[dict]:
        return [as_dict(position) for position in self.connection.positions(symbol=symbol)]

    def pending_orders(self, symbol: str | None = None) -> list[dict]:
        return [as_dict(order) for order in self.connection.pending_orders(symbol=symbol)]

    def daily_realized_profit(self, now: datetime | None = None) -> float | None:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)

        try:
            deals = self.connection.history_deals(start, now)
        except Exception:
            return None

        total = 0.0
        for deal in deals:
            payload = as_dict(deal)
            total += float(payload.get("profit") or 0.0)
            total += float(payload.get("commission") or 0.0)
            total += float(payload.get("swap") or 0.0)
            total += float(payload.get("fee") or 0.0)
        return total

    def today_history(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)

        try:
            deals = self.connection.history_deals(start, now)
        except Exception:
            return {
                "date": start.date().isoformat(),
                "realized_profit": None,
                "trade_count": 0,
                "wins": 0,
                "losses": 0,
                "deals": [],
                "unavailable": True,
            }
        payload = []
        realized_profit = 0.0
        wins = 0
        losses = 0

        for deal in deals:
            item = as_dict(deal)
            profit = (
                float(item.get("profit") or 0.0)
                + float(item.get("commission") or 0.0)
                + float(item.get("swap") or 0.0)
                + float(item.get("fee") or 0.0)
            )
            realized_profit += profit
            if profit > 0:
                wins += 1
            elif profit < 0:
                losses += 1

            timestamp = item.get("time")
            if timestamp:
                try:
                    item["time_iso"] = datetime.fromtimestamp(int(timestamp), tz=timezone.utc).isoformat()
                except (TypeError, ValueError, OSError):
                    item["time_iso"] = None
            else:
                item["time_iso"] = None
            item["net_profit"] = profit
            payload.append(item)

        payload.sort(key=lambda item: item.get("time") or 0)
        return {
            "date": start.date().isoformat(),
            "realized_profit": realized_profit,
            "trade_count": len(payload),
            "wins": wins,
            "losses": losses,
            "deals": payload,
        }

    def closed_trades(self, date_from: datetime, date_to: datetime) -> list[dict]:
        """Group raw MT5 deals into round-trip trades over a time range.

        This reads the full account deal history from MetaTrader 5, so it
        captures trades placed manually in the terminal or by other tools, not
        only orders sent through this app. Deals are grouped by ``position_id``;
        a trade is considered closed once it has an exit deal.
        """
        deals = [as_dict(deal) for deal in self.connection.history_deals(date_from, date_to)]

        groups: dict[object, dict] = {}
        for item in deals:
            deal_type = item.get("type")
            # Keep only buy/sell market deals; skip balance, credit, charge, etc.
            if deal_type not in (_DEAL_TYPE_BUY, _DEAL_TYPE_SELL):
                continue

            position_id = item.get("position_id") or item.get("order") or item.get("ticket")
            entry = item.get("entry")
            timestamp = item.get("time") or 0
            net = _deal_net(item)

            group = groups.get(position_id)
            if group is None:
                group = {
                    "position_id": position_id,
                    "ticket": item.get("ticket"),
                    "symbol": item.get("symbol") or "-",
                    "side": None,
                    "volume": 0.0,
                    "open_time": None,
                    "close_time": None,
                    "open_price": None,
                    "close_price": None,
                    "net_profit": 0.0,
                    "commission": 0.0,
                    "swap": 0.0,
                    "fee": 0.0,
                    "comment": item.get("comment") or "",
                    "closed": False,
                    "_open_ts": None,
                    "_close_ts": None,
                }
                groups[position_id] = group

            group["net_profit"] += net
            group["commission"] += float(item.get("commission") or 0.0)
            group["swap"] += float(item.get("swap") or 0.0)
            group["fee"] += float(item.get("fee") or 0.0)
            if item.get("symbol"):
                group["symbol"] = item["symbol"]
            if item.get("comment") and not group["comment"]:
                group["comment"] = item["comment"]

            if entry == _DEAL_ENTRY_IN:
                # Opening deal defines side, volume, entry price and open time.
                group["side"] = "BUY" if deal_type == _DEAL_TYPE_BUY else "SELL"
                group["volume"] = float(item.get("volume") or group["volume"])
                group["open_price"] = item.get("price")
                if group["_open_ts"] is None or timestamp < group["_open_ts"]:
                    group["_open_ts"] = timestamp
            elif entry in (_DEAL_ENTRY_OUT, _DEAL_ENTRY_OUT_BY):
                group["closed"] = True
                group["close_price"] = item.get("price")
                group["ticket"] = item.get("ticket") or group["ticket"]
                if group["_close_ts"] is None or timestamp > group["_close_ts"]:
                    group["_close_ts"] = timestamp

            # Track first/last seen timestamps as a fallback for missing entries.
            if group["_open_ts"] is None or (timestamp and timestamp < group["_open_ts"]):
                group["_open_ts"] = group["_open_ts"] or timestamp
            if timestamp and (group["_close_ts"] is None or timestamp > group["_close_ts"]):
                group["_close_ts"] = timestamp

        trades = []
        for group in groups.values():
            if group["side"] is None:
                group["side"] = "-"
            group["open_time"] = _deal_time_iso(group.pop("_open_ts"))
            group["close_time"] = _deal_time_iso(group.pop("_close_ts"))
            group["net_profit"] = round(group["net_profit"], 2)
            group["commission"] = round(group["commission"], 2)
            group["swap"] = round(group["swap"], 2)
            group["fee"] = round(group["fee"], 2)
            trades.append(group)

        trades.sort(key=lambda trade: trade.get("close_time") or trade.get("open_time") or "")
        return trades

    def trade_history(self, days: int = 30, now: datetime | None = None) -> dict:
        """Full MT5 trade history with summary stats, an equity curve and
        per-symbol / per-day breakdowns for the dashboard.
        """
        days = max(1, min(int(days or 30), 3650))
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        start = datetime.combine((now - timedelta(days=days - 1)).date(), time.min, tzinfo=timezone.utc)

        try:
            trades = self.closed_trades(start, now)
        except Exception:
            return {
                "range": {"days": days, "from": start.isoformat(), "to": now.isoformat()},
                "summary": {
                    "realized_profit": None,
                    "trade_count": 0,
                    "wins": 0,
                    "losses": 0,
                    "win_rate": None,
                    "gross_profit": 0.0,
                    "gross_loss": 0.0,
                    "profit_factor": None,
                    "best_trade": None,
                    "worst_trade": None,
                    "unavailable": True,
                },
                "trades": [],
                "by_symbol": [],
                "equity_curve": [],
                "daily": [],
                "unavailable": True,
            }

        closed = [trade for trade in trades if trade.get("closed")]

        realized = 0.0
        wins = 0
        losses = 0
        gross_profit = 0.0
        gross_loss = 0.0
        best = None
        worst = None
        by_symbol: dict[str, dict] = {}
        by_day: dict[str, dict] = {}
        equity_curve = []
        cumulative = 0.0

        for trade in closed:
            profit = float(trade.get("net_profit") or 0.0)
            realized += profit
            if profit > 0:
                wins += 1
                gross_profit += profit
            elif profit < 0:
                losses += 1
                gross_loss += abs(profit)
            best = profit if best is None else max(best, profit)
            worst = profit if worst is None else min(worst, profit)

            symbol = trade.get("symbol") or "-"
            symbol_bucket = by_symbol.setdefault(
                symbol,
                {"symbol": symbol, "net_profit": 0.0, "trades": 0, "wins": 0, "losses": 0},
            )
            symbol_bucket["net_profit"] = round(symbol_bucket["net_profit"] + profit, 2)
            symbol_bucket["trades"] += 1
            if profit > 0:
                symbol_bucket["wins"] += 1
            elif profit < 0:
                symbol_bucket["losses"] += 1

            stamp = trade.get("close_time") or trade.get("open_time")
            day = stamp[:10] if stamp else "unknown"
            day_bucket = by_day.setdefault(day, {"date": day, "profit": 0.0, "trades": 0})
            day_bucket["profit"] = round(day_bucket["profit"] + profit, 2)
            day_bucket["trades"] += 1

            cumulative = round(cumulative + profit, 2)
            equity_curve.append(
                {
                    "time": stamp,
                    "symbol": symbol,
                    "profit": round(profit, 2),
                    "cumulative": cumulative,
                }
            )

        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None
        win_rate = round(wins / len(closed), 4) if closed else None

        return {
            "range": {"days": days, "from": start.isoformat(), "to": now.isoformat()},
            "summary": {
                "realized_profit": round(realized, 2),
                "trade_count": len(closed),
                "wins": wins,
                "losses": losses,
                "win_rate": win_rate,
                "gross_profit": round(gross_profit, 2),
                "gross_loss": round(gross_loss, 2),
                "profit_factor": profit_factor,
                "best_trade": None if best is None else round(best, 2),
                "worst_trade": None if worst is None else round(worst, 2),
                "unavailable": False,
            },
            "trades": closed,
            "by_symbol": sorted(
                by_symbol.values(),
                key=lambda bucket: abs(bucket["net_profit"]),
                reverse=True,
            ),
            "equity_curve": equity_curve,
            "daily": sorted(by_day.values(), key=lambda bucket: bucket["date"]),
            "unavailable": False,
        }

    def candles(self, symbol: str, timeframe: str, count: int = 300) -> pd.DataFrame:
        rates = self.connection.copy_rates(symbol, timeframe, count)
        if rates is None:
            return pd.DataFrame()

        df = pd.DataFrame(rates)
        if df.empty:
            return df

        df["time"] = pd.to_datetime(df["time"], unit="s")
        return df

    def latest_atr(self, symbol: str, timeframe: str = "M15") -> float | None:
        df = add_indicators(self.candles(symbol, timeframe, count=300))
        if df.empty:
            return None
        value = df.iloc[-1].get("atr14")
        if pd.isna(value):
            return None
        return float(value)

    def candle_payload(self, symbol: str, timeframe: str = "M5", count: int = 120) -> list[dict]:
        df = add_indicators(self.candles(symbol, timeframe, count=count))
        if df.empty:
            return []

        payload = []
        for row in df.tail(count).to_dict("records"):
            payload.append(
                {
                    "time": row["time"].isoformat() if hasattr(row["time"], "isoformat") else str(row["time"]),
                    "open": _clean_number(row.get("open")),
                    "high": _clean_number(row.get("high")),
                    "low": _clean_number(row.get("low")),
                    "close": _clean_number(row.get("close")),
                    "tick_volume": _clean_number(row.get("tick_volume")),
                    "ema20": _clean_number(row.get("ema20")),
                    "ema50": _clean_number(row.get("ema50")),
                    "rsi14": _clean_number(row.get("rsi14")),
                    "macd": _clean_number(row.get("macd")),
                    "macd_signal": _clean_number(row.get("macd_signal")),
                    "macd_hist": _clean_number(row.get("macd_hist")),
                    "atr14": _clean_number(row.get("atr14")),
                    "atr_pct": _clean_number(row.get("atr_pct")),
                    "adx14": _clean_number(row.get("adx14")),
                }
            )
        return payload

    def symbol_report(
        self,
        symbol: str,
        timeframes: Iterable[str] = MARKET_TIMEFRAMES,
        candle_count: int = 120,
    ) -> dict:
        tick = self.tick_info(symbol)
        positions = self.positions(symbol)
        pending_orders = self.pending_orders(symbol)

        timeframe_data = {}
        for timeframe in timeframes:
            candles = self.candle_payload(symbol, timeframe, count=candle_count)
            last = candles[-1] if candles else None
            timeframe_data[timeframe] = {
                "latest": last,
                "candles": candles,
            }

        return {
            "symbol": symbol,
            "tick": tick,
            "positions": positions,
            "pending_orders": pending_orders,
            "timeframes": timeframe_data,
        }

    def market_status(self, symbol_reports: list[dict], now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        newest_tick = None
        for report in symbol_reports:
            tick_epoch = report.get("tick", {}).get("time_epoch")
            if tick_epoch is None:
                continue
            try:
                tick_time = datetime.fromtimestamp(float(tick_epoch), tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                continue
            if newest_tick is None or tick_time > newest_tick:
                newest_tick = tick_time

        session_open = _forex_session_open(now)
        tick_age_seconds = None
        has_fresh_tick = False
        if newest_tick is not None:
            tick_age_seconds = max(0.0, (now - newest_tick).total_seconds())
            has_fresh_tick = tick_age_seconds <= 300

        is_open = session_open and has_fresh_tick
        reason = "fresh MT5 tick" if is_open else "forex session closed"
        if session_open and not has_fresh_tick:
            reason = "no fresh MT5 tick"

        return {
            "label": "Market open" if is_open else "Market closed",
            "is_open": is_open,
            "session_open": session_open,
            "has_fresh_tick": has_fresh_tick,
            "newest_tick_time": newest_tick.isoformat() if newest_tick else None,
            "tick_age_seconds": tick_age_seconds,
            "reason": reason,
        }

    def dashboard_snapshot(self, symbols: Iterable[str] = SYMBOLS) -> dict:
        symbol_reports = [self.symbol_report(symbol) for symbol in symbols]
        return {
            "account": self.account_snapshot(),
            "positions": self.positions(),
            "pending_orders": self.pending_orders(),
            "today_history": self.today_history(),
            "market_status": self.market_status(symbol_reports),
            "symbols": symbol_reports,
        }
