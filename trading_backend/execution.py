from __future__ import annotations

import math

import pandas as pd

from .market_data import MarketDataService
from .mt5_client import MT5Connection, as_dict


class OrderExecutor:
    def __init__(
        self,
        connection: MT5Connection | None = None,
        market_data: MarketDataService | None = None,
    ):
        self.connection = connection or MT5Connection()
        self.market_data = market_data or MarketDataService(self.connection)

    def normalize_price(self, symbol: str, price: float) -> float:
        info = self.connection.symbol_info(symbol)
        return round(price, info.digits)

    def normalize_volume(self, symbol: str, volume: float) -> float:
        info = self.connection.symbol_info(symbol)
        minimum = float(getattr(info, "volume_min", 0.01) or 0.01)
        maximum = float(getattr(info, "volume_max", volume) or volume)
        step = float(getattr(info, "volume_step", 0.01) or 0.01)

        clamped = max(minimum, min(maximum, float(volume)))
        normalized = math.floor(clamped / step) * step
        return round(max(minimum, normalized), 2)

    def risk_sized_volume(self, symbol: str, sl_points: int) -> float:
        settings = self.connection.settings
        risk_pct = max(0.0, float(settings.risk_per_trade_pct))
        if risk_pct <= 0 or sl_points <= 0:
            return self.normalize_volume(symbol, settings.lot_size)

        account = self.market_data.account_snapshot()
        equity = float(account.get("equity") or account.get("balance") or 0.0)
        if equity <= 0:
            return self.normalize_volume(symbol, settings.lot_size)

        info = self.connection.symbol_info(symbol)
        point = float(getattr(info, "point", 0.0) or 0.0)
        tick_size = float(getattr(info, "trade_tick_size", 0.0) or 0.0)
        tick_value = float(getattr(info, "trade_tick_value", 0.0) or 0.0)
        if point <= 0 or tick_size <= 0 or tick_value <= 0:
            return self.normalize_volume(symbol, settings.lot_size)

        value_per_point_per_lot = tick_value * (point / tick_size)
        risk_amount = equity * (risk_pct / 100)
        raw_volume = risk_amount / (sl_points * value_per_point_per_lot)
        return self.normalize_volume(symbol, raw_volume)

    def market_order(
        self,
        symbol: str,
        side: str,
        volume: float = 0.01,
        sl_points: int | None = None,
        tp_points: int | None = None,
        comment: str = "python-mt5",
        dry_run: bool = False,
    ) -> dict:
        side = side.upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")

        module = self.connection.module
        symbol_info = self.connection.symbol_info(symbol)
        tick = self.connection.tick(symbol)
        is_buy = side == "BUY"
        order_type = module.ORDER_TYPE_BUY if is_buy else module.ORDER_TYPE_SELL
        price = tick.ask if is_buy else tick.bid
        point = symbol_info.point

        sl = 0.0
        tp = 0.0
        if sl_points:
            sl = price - sl_points * point if is_buy else price + sl_points * point
        if tp_points:
            tp = price + tp_points * point if is_buy else price - tp_points * point

        request = {
            "action": module.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": self.normalize_volume(symbol, volume),
            "type": order_type,
            "price": self.normalize_price(symbol, price),
            "sl": self.normalize_price(symbol, sl) if sl else 0.0,
            "tp": self.normalize_price(symbol, tp) if tp else 0.0,
            "deviation": 20,
            "magic": self.connection.settings.magic_number,
            "comment": comment,
            "type_time": module.ORDER_TIME_GTC,
            "type_filling": module.ORDER_FILLING_IOC,
        }

        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "request": request,
                "message": "Order was prepared but not sent.",
            }

        result = self.connection.order_send(request)
        result_dict = as_dict(result)
        result_dict["ok"] = result.retcode == module.TRADE_RETCODE_DONE
        result_dict["dry_run"] = False
        return result_dict

    def strategy_order(
        self,
        symbol: str,
        side: str,
        volume: float | None = None,
        dry_run: bool = False,
    ) -> dict:
        tick = self.market_data.tick_info(symbol)
        max_spread = self.connection.settings.max_spread_points.get(symbol, 15.0)
        if tick["spread_points"] > max_spread:
            return {
                "ok": False,
                "dry_run": dry_run,
                "message": f"{symbol} spread is too high: {tick['spread_points']} points.",
            }

        atr_value = self.market_data.latest_atr(symbol)
        if atr_value is None or pd.isna(atr_value):
            return {
                "ok": False,
                "dry_run": dry_run,
                "message": f"{symbol} ATR is not available.",
            }

        info = self.connection.symbol_info(symbol)
        sl_points = max(1, int((atr_value * 2) / info.point))
        tp_points = max(1, int((atr_value * 3) / info.point))

        return self.market_order(
            symbol=symbol,
            side=side,
            volume=(
                self.normalize_volume(symbol, volume)
                if volume is not None
                else self.risk_sized_volume(symbol, sl_points)
            ),
            sl_points=sl_points,
            tp_points=tp_points,
            comment=f"auto_{side.lower()}",
            dry_run=dry_run,
        )

    def close_position(
        self,
        ticket: int,
        comment: str = "python-close",
        dry_run: bool = False,
    ) -> dict:
        positions = self.connection.positions(ticket=ticket)
        if not positions:
            raise RuntimeError(f"No position found with ticket {ticket}")

        module = self.connection.module
        position = positions[0]
        tick = self.connection.tick(position.symbol)

        if position.type == module.POSITION_TYPE_BUY:
            close_type = module.ORDER_TYPE_SELL
            price = tick.bid
        else:
            close_type = module.ORDER_TYPE_BUY
            price = tick.ask

        request = {
            "action": module.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "volume": position.volume,
            "type": close_type,
            "position": ticket,
            "price": self.normalize_price(position.symbol, price),
            "deviation": 20,
            "magic": self.connection.settings.magic_number,
            "comment": comment,
            "type_time": module.ORDER_TIME_GTC,
            "type_filling": module.ORDER_FILLING_IOC,
        }

        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "request": request,
                "message": "Close order was prepared but not sent.",
            }

        result = self.connection.order_send(request)
        result_dict = as_dict(result)
        result_dict["ok"] = result.retcode == module.TRADE_RETCODE_DONE
        result_dict["dry_run"] = False
        return result_dict

    def cancel_order(self, order_ticket: int, dry_run: bool = False) -> dict:
        module = self.connection.module
        request = {
            "action": module.TRADE_ACTION_REMOVE,
            "order": order_ticket,
        }

        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "request": request,
                "message": "Cancel order was prepared but not sent.",
            }

        result = self.connection.order_send(request)
        result_dict = as_dict(result)
        result_dict["ok"] = result.retcode == module.TRADE_RETCODE_DONE
        result_dict["dry_run"] = False
        return result_dict

    def handle_signal(self, signal: dict, dry_run: bool = False) -> dict:
        action = signal["action"].lower()

        if action in {"buy", "sell"}:
            return self.market_order(
                symbol=signal["symbol"],
                side=action,
                volume=float(signal.get("volume", 0.01)),
                sl_points=signal.get("sl_points"),
                tp_points=signal.get("tp_points"),
                dry_run=dry_run,
            )

        if action == "close":
            return self.close_position(ticket=int(signal["ticket"]), dry_run=dry_run)

        if action == "cancel":
            return self.cancel_order(order_ticket=int(signal["order_ticket"]), dry_run=dry_run)

        raise ValueError(f"Unknown signal action: {action}")
