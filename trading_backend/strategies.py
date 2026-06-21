from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping, Protocol

import pandas as pd

from .indicators import add_indicators
from .market_data import MarketDataService
from .settings import DEFAULT_MAX_SPREAD_POINTS, STRATEGY_TIMEFRAMES, SYMBOLS, Settings


BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"
WEAK_BUY = "WEAK_BUY"
WEAK_SELL = "WEAK_SELL"

PAIR_PROFILES = {
    "EURUSD": {
        "name": "Euro / US Dollar",
        "base_currency": "EUR",
        "quote_currency": "USD",
        "max_spread_points": DEFAULT_MAX_SPREAD_POINTS["EURUSD"],
        "min_atr_pct": 0.00008,
        "max_atr_pct": 0.004,
        "note": "Trend-following bias with tight spread filter.",
    },
    "GBPUSD": {
        "name": "British Pound / US Dollar",
        "base_currency": "GBP",
        "quote_currency": "USD",
        "max_spread_points": DEFAULT_MAX_SPREAD_POINTS["GBPUSD"],
        "min_atr_pct": 0.0001,
        "max_atr_pct": 0.005,
        "note": "Momentum signal with wider volatility allowance.",
    },
    "USDJPY": {
        "name": "US Dollar / Japanese Yen",
        "base_currency": "USD",
        "quote_currency": "JPY",
        "max_spread_points": DEFAULT_MAX_SPREAD_POINTS["USDJPY"],
        "min_atr_pct": 0.00008,
        "max_atr_pct": 0.0045,
        "note": "Trend confirmation across intraday timeframes.",
    },
}


@dataclass(frozen=True)
class RiskPolicy:
    """Configurable pre-trade guardrails used before a signal can execute."""

    max_spread_points: Mapping[str, float] = field(
        default_factory=lambda: DEFAULT_MAX_SPREAD_POINTS.copy()
    )
    min_confidence_to_trade: float = 0.68
    risk_per_trade_pct: float = 1.0
    max_daily_loss_pct: float = 3.0
    max_account_drawdown_pct: float = 8.0
    max_open_positions: int = 3
    max_positions_per_symbol: int = 1
    max_currency_exposure_units: float = 2.0
    kill_switch: bool = False
    news_lockout_active: bool = False
    trade_session_start_hour_utc: int = 0
    trade_session_end_hour_utc: int = 24
    rollover_blackout_minutes: int = 15
    avoid_weekend: bool = True

    @classmethod
    def from_settings(cls, settings: Settings) -> "RiskPolicy":
        return cls(
            max_spread_points=settings.max_spread_points,
            min_confidence_to_trade=settings.min_strategy_confidence,
            risk_per_trade_pct=settings.risk_per_trade_pct,
            max_daily_loss_pct=settings.max_daily_loss_pct,
            max_account_drawdown_pct=settings.max_account_drawdown_pct,
            max_open_positions=settings.max_open_positions,
            max_positions_per_symbol=settings.max_positions_per_symbol,
            max_currency_exposure_units=settings.max_currency_exposure_units,
            kill_switch=settings.risk_kill_switch,
            news_lockout_active=settings.news_lockout_active,
            trade_session_start_hour_utc=settings.trade_session_start_hour_utc,
            trade_session_end_hour_utc=settings.trade_session_end_hour_utc,
            rollover_blackout_minutes=settings.rollover_blackout_minutes,
        )


@dataclass(frozen=True)
class RiskAssessment:
    """Result of applying risk policy to a proposed strategy signal."""

    allow_trade: bool
    risk_level: str
    target_signal: str
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    checks: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "allow_trade": self.allow_trade,
            "risk_level": self.risk_level,
            "target_signal": self.target_signal,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "checks": dict(self.checks),
        }


@dataclass(frozen=True)
class StrategyState:
    """Standard input passed to every currency-pair strategy."""

    symbol: str
    profile: Mapping[str, object]
    candles: Mapping[str, pd.DataFrame]
    tick: Mapping[str, object] | None = None
    account: Mapping[str, object] | None = None
    positions: tuple[Mapping[str, object], ...] = ()
    all_positions: tuple[Mapping[str, object], ...] = ()
    pending_orders: tuple[Mapping[str, object], ...] = ()
    all_pending_orders: tuple[Mapping[str, object], ...] = ()
    daily_realized_profit: float | None = None
    now_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def candles_for(self, timeframe: str) -> pd.DataFrame:
        return self.candles.get(timeframe, pd.DataFrame())


@dataclass(frozen=True)
class TimeframeSignal:
    """Standard per-timeframe signal produced by a strategy."""

    signal: str
    confidence: float
    buy_score: int | float = 0
    sell_score: int | float = 0
    reasons: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        payload = {
            "signal": self.signal,
            "confidence": round(self.confidence, 2),
            "buy_score": self.buy_score,
            "sell_score": self.sell_score,
            "reasons": list(self.reasons),
        }

        if self.metadata:
            payload["metadata"] = dict(self.metadata)

        return payload


@dataclass(frozen=True)
class TimeframeDecision:
    """Standard output for a single timeframe analysis."""

    symbol: str
    timeframe: str
    signal: TimeframeSignal
    latest: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "signal": self.signal.to_dict(),
            "latest": dict(self.latest),
        }


@dataclass(frozen=True)
class StrategyDecision:
    """Standard output produced by every currency-pair strategy."""

    symbol: str
    profile: Mapping[str, object]
    final_signal: str
    confidence: float
    timeframes: Mapping[str, TimeframeDecision]
    strategy_name: str
    reasons: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        payload = {
            "symbol": self.symbol,
            "profile": dict(self.profile),
            "final_signal": self.final_signal,
            "confidence": round(self.confidence, 2),
            "strategy_name": self.strategy_name,
            "reasons": list(self.reasons),
            "timeframes": {
                timeframe: decision.to_dict()
                for timeframe, decision in self.timeframes.items()
            },
        }

        if self.metadata:
            payload["metadata"] = dict(self.metadata)

        return payload


class CurrencyPairStrategy(Protocol):
    """Contract implemented by swappable pair-specific strategies."""

    name: str
    profile: Mapping[str, object]
    timeframes: tuple[str, ...]
    candle_count: int

    def analyze_timeframe(
        self,
        state: StrategyState,
        timeframe: str,
    ) -> TimeframeDecision:
        ...

    def evaluate(self, state: StrategyState) -> StrategyDecision:
        ...


def _clean_float(value) -> float | None:
    if value is None:
        return None
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    return float(value)


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _position_side(position: Mapping[str, object]) -> str | None:
    position_type = position.get("type")
    if position_type == 0:
        return BUY
    if position_type == 1:
        return SELL
    return None


def _currency_exposure(
    profile: Mapping[str, object],
    side: str,
    units: float = 1.0,
) -> dict[str, float]:
    base = str(profile.get("base_currency") or "")[:3]
    quote = str(profile.get("quote_currency") or "")[:3]
    if not base or not quote or side not in {BUY, SELL}:
        return {}

    direction = 1.0 if side == BUY else -1.0
    return {
        base: direction * units,
        quote: -direction * units,
    }


def _within_session(now_utc: datetime, policy: RiskPolicy) -> bool:
    start = policy.trade_session_start_hour_utc
    end = policy.trade_session_end_hour_utc
    if start == 0 and end == 24:
        return True
    if start < end:
        return start <= now_utc.hour < end
    return now_utc.hour >= start or now_utc.hour < end


def assess_trade_risk(
    state: StrategyState,
    target_signal: str,
    confidence: float,
    policy: RiskPolicy,
) -> RiskAssessment:
    blockers: list[str] = []
    warnings: list[str] = []
    checks: dict[str, object] = {
        "target_signal": target_signal,
        "confidence": round(confidence, 4),
        "min_confidence_to_trade": policy.min_confidence_to_trade,
        "risk_per_trade_pct": policy.risk_per_trade_pct,
    }

    if target_signal not in {BUY, SELL}:
        return RiskAssessment(
            allow_trade=False,
            risk_level="LOW",
            target_signal=target_signal,
            checks=checks,
        )

    if policy.kill_switch:
        blockers.append("Risk kill switch is active")

    if policy.news_lockout_active:
        blockers.append("Manual high-impact news lockout is active")

    if confidence < policy.min_confidence_to_trade:
        blockers.append(
            f"Confidence {confidence:.2f} is below {policy.min_confidence_to_trade:.2f}"
        )

    now_utc = state.now_utc
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    checks["utc_time"] = now_utc.isoformat()
    if policy.avoid_weekend and now_utc.weekday() >= 5:
        blockers.append("Weekend trading is blocked")

    if not _within_session(now_utc, policy):
        blockers.append(
            "Current UTC hour is outside configured trading session"
        )

    if policy.rollover_blackout_minutes > 0 and now_utc.hour == 21:
        if now_utc.minute < policy.rollover_blackout_minutes:
            blockers.append("Broker rollover blackout window is active")

    max_spread = float(
        policy.max_spread_points.get(
            state.symbol,
            state.profile.get("max_spread_points", 15.0),
        )
    )
    spread = _safe_float((state.tick or {}).get("spread_points"), default=-1.0)
    checks["spread_points"] = spread if spread >= 0 else None
    checks["max_spread_points"] = max_spread
    if spread < 0:
        blockers.append("Realtime spread is unavailable")
    elif spread > max_spread:
        blockers.append(f"Spread {spread:g} exceeds limit {max_spread:g}")
    elif spread > max_spread * 0.8:
        warnings.append(f"Spread {spread:g} is near limit {max_spread:g}")

    account = state.account or {}
    balance = _safe_float(account.get("balance"))
    equity = _safe_float(account.get("equity"))
    floating_profit = _safe_float(account.get("profit"))
    checks["balance"] = balance or None
    checks["equity"] = equity or None
    checks["floating_profit"] = floating_profit

    if balance <= 0 or equity <= 0:
        blockers.append("Account balance/equity is unavailable")
    else:
        max_daily_loss = balance * (policy.max_daily_loss_pct / 100)
        max_drawdown_equity = balance * (1 - policy.max_account_drawdown_pct / 100)
        checks["max_daily_loss_amount"] = round(max_daily_loss, 2)
        checks["min_equity_allowed"] = round(max_drawdown_equity, 2)

        if state.daily_realized_profit is None:
            warnings.append("Daily realized P/L is unavailable from MT5 history")
        elif state.daily_realized_profit <= -max_daily_loss:
            blockers.append(
                f"Daily realized loss {state.daily_realized_profit:.2f} exceeds limit"
            )

        if floating_profit <= -max_daily_loss:
            blockers.append(
                f"Floating loss {floating_profit:.2f} exceeds daily loss limit"
            )

        if equity <= max_drawdown_equity:
            blockers.append("Equity drawdown guard is active")

    symbol_positions = tuple(state.positions)
    all_positions = tuple(state.all_positions or state.positions)
    checks["symbol_position_count"] = len(symbol_positions)
    checks["open_position_count"] = len(all_positions)

    if len(symbol_positions) >= policy.max_positions_per_symbol:
        blockers.append(
            f"{state.symbol} already has {len(symbol_positions)} open position(s)"
        )

    if len(all_positions) >= policy.max_open_positions:
        blockers.append(
            f"Open position count {len(all_positions)} reached limit {policy.max_open_positions}"
        )

    if len(state.all_pending_orders) > policy.max_open_positions:
        warnings.append("Pending order count is above open-position limit")

    exposures: dict[str, float] = {}
    for position in all_positions:
        side = _position_side(position)
        symbol = str(position.get("symbol") or "")
        if side is None or symbol not in PAIR_PROFILES:
            continue
        for currency, units in _currency_exposure(PAIR_PROFILES[symbol], side).items():
            exposures[currency] = exposures.get(currency, 0.0) + units

    for currency, units in _currency_exposure(state.profile, target_signal).items():
        exposures[currency] = exposures.get(currency, 0.0) + units

    checks["projected_currency_exposure"] = {
        currency: round(units, 2)
        for currency, units in sorted(exposures.items())
    }
    crowded = [
        currency
        for currency, units in exposures.items()
        if abs(units) > policy.max_currency_exposure_units
    ]
    if crowded:
        blockers.append(
            "Projected currency exposure exceeds limit: " + ", ".join(sorted(crowded))
        )

    risk_level = "BLOCKED" if blockers else "MEDIUM" if warnings else "LOW"
    return RiskAssessment(
        allow_trade=not blockers,
        risk_level=risk_level,
        target_signal=target_signal,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        checks=checks,
    )


class IndicatorScoreStrategy:
    """
    Default EMA/RSI/MACD multi-timeframe strategy.

    Pair-specific strategy classes can subclass this and override either
    analyze_timeframe() or combine_timeframes(), while keeping the same
    StrategyState -> StrategyDecision interface.
    """

    name = "ema_rsi_macd_multi_timeframe"
    profile: Mapping[str, object] = {}
    timeframes = STRATEGY_TIMEFRAMES
    candle_count = 300
    min_candles = 80
    timeframe_weights = {
        "M5": 1.0,
        "M15": 1.4,
        "H1": 2.0,
    }
    rsi_buy_threshold = 54
    rsi_sell_threshold = 46
    rsi_overbought = 72
    rsi_oversold = 28
    adx_trend_threshold = 18
    strong_timeframe_score = 2.35
    weak_timeframe_score = 1.15
    final_score_threshold = 0.58
    confirming_timeframe = "H1"

    def __init__(
        self,
        profile: Mapping[str, object] | None = None,
        timeframes: tuple[str, ...] | None = None,
        risk_policy: RiskPolicy | None = None,
    ):
        profile_source = self.profile if profile is None else profile
        self.profile = dict(profile_source)
        self.timeframes = tuple(timeframes or self.timeframes)
        self.risk_policy = risk_policy or RiskPolicy()

    def evaluate(self, state: StrategyState) -> StrategyDecision:
        timeframes = {
            timeframe: self.analyze_timeframe(state, timeframe)
            for timeframe in self.timeframes
        }
        raw_signal, confidence, reasons, aggregate = self.combine_timeframes(timeframes)
        risk = assess_trade_risk(state, raw_signal, confidence, self.risk_policy)
        final_signal = raw_signal if risk.allow_trade else HOLD
        final_confidence = confidence if risk.allow_trade else min(confidence, 0.45)
        final_reasons = list(reasons)

        if risk.blockers:
            final_reasons.extend(risk.blockers)
        elif risk.warnings:
            final_reasons.extend(risk.warnings)

        return StrategyDecision(
            symbol=state.symbol,
            profile=state.profile,
            final_signal=final_signal,
            confidence=final_confidence,
            strategy_name=self.name,
            reasons=tuple(final_reasons),
            timeframes=timeframes,
            metadata={
                "raw_signal": raw_signal,
                "raw_confidence": round(confidence, 4),
                "risk": risk.to_dict(),
                "aggregate": aggregate,
            },
        )

    def analyze_timeframe(
        self,
        state: StrategyState,
        timeframe: str,
    ) -> TimeframeDecision:
        df = state.candles_for(timeframe)
        enriched = add_indicators(df) if not df.empty else df

        return TimeframeDecision(
            symbol=state.symbol,
            timeframe=timeframe,
            signal=self.timeframe_signal(enriched),
            latest=self.latest_snapshot(enriched),
        )

    def timeframe_signal(self, enriched: pd.DataFrame) -> TimeframeSignal:
        if enriched.empty or len(enriched) < self.min_candles:
            return TimeframeSignal(
                signal=HOLD,
                confidence=0.0,
                buy_score=0,
                sell_score=0,
                reasons=("Not enough candle data",),
            )

        last = enriched.iloc[-1]
        previous = enriched.iloc[-2]
        required = (
            "close",
            "ema20",
            "ema50",
            "rsi14",
            "macd",
            "macd_signal",
            "macd_hist",
            "atr14",
            "atr_pct",
            "adx14",
        )
        if any(pd.isna(last.get(column)) for column in required):
            return TimeframeSignal(
                signal=HOLD,
                confidence=0.0,
                buy_score=0,
                sell_score=0,
                reasons=("Indicator warmup is not ready",),
            )

        score = 0.0
        buy_score = 0.0
        sell_score = 0.0
        reasons: list[str] = []
        warnings: list[str] = []

        if last["ema20"] > last["ema50"]:
            score += 1.2
            buy_score += 1.2
            reasons.append("EMA20 above EMA50")
        else:
            score -= 1.2
            sell_score += 1.2
            reasons.append("EMA20 below EMA50")

        if last["close"] > last["ema20"]:
            score += 0.45
            buy_score += 0.45
            reasons.append("Close above EMA20")
        elif last["close"] < last["ema20"]:
            score -= 0.45
            sell_score += 0.45
            reasons.append("Close below EMA20")

        if last["rsi14"] > self.rsi_buy_threshold:
            score += 0.9
            buy_score += 0.9
            reasons.append(f"RSI above {self.rsi_buy_threshold}")
        elif last["rsi14"] < self.rsi_sell_threshold:
            score -= 0.9
            sell_score += 0.9
            reasons.append(f"RSI below {self.rsi_sell_threshold}")
        else:
            reasons.append("RSI neutral")

        if last["rsi14"] >= self.rsi_overbought:
            score -= 0.35
            warnings.append("RSI is overbought")
        elif last["rsi14"] <= self.rsi_oversold:
            score += 0.35
            warnings.append("RSI is oversold")

        if last["macd"] > last["macd_signal"]:
            score += 0.8
            buy_score += 0.8
            reasons.append("MACD bullish")
        else:
            score -= 0.8
            sell_score += 0.8
            reasons.append("MACD bearish")

        macd_hist_delta = _safe_float(last["macd_hist"]) - _safe_float(previous.get("macd_hist"))
        if macd_hist_delta > 0:
            score += 0.35
            buy_score += 0.35
            reasons.append("MACD histogram improving")
        elif macd_hist_delta < 0:
            score -= 0.35
            sell_score += 0.35
            reasons.append("MACD histogram weakening")

        adx_value = _safe_float(last["adx14"])
        if adx_value >= self.adx_trend_threshold:
            score *= 1.12
            reasons.append(f"ADX trend strength above {self.adx_trend_threshold}")
        else:
            score *= 0.72
            warnings.append("ADX shows weak trend strength")

        atr_pct = _safe_float(last["atr_pct"])
        min_atr_pct = _safe_float(self.profile.get("min_atr_pct"), 0.0)
        max_atr_pct = _safe_float(self.profile.get("max_atr_pct"), 1.0)
        volatility_factor = 1.0
        if min_atr_pct and atr_pct < min_atr_pct:
            volatility_factor = 0.82
            warnings.append("Volatility is compressed")
        elif max_atr_pct and atr_pct > max_atr_pct:
            volatility_factor = 0.78
            warnings.append("Volatility is unusually elevated")

        score *= volatility_factor
        abs_score = abs(score)
        base_confidence = min(0.92, 0.42 + abs_score / 4.2)
        if warnings:
            base_confidence = max(0.0, base_confidence - 0.08)

        if score >= self.strong_timeframe_score:
            signal = BUY
            confidence = max(base_confidence, 0.76)
        elif score <= -self.strong_timeframe_score:
            signal = SELL
            confidence = max(base_confidence, 0.76)
        elif score >= self.weak_timeframe_score:
            signal = WEAK_BUY
            confidence = max(0.52, min(base_confidence, 0.68))
        elif score <= -self.weak_timeframe_score:
            signal = WEAK_SELL
            confidence = max(0.52, min(base_confidence, 0.68))
        else:
            signal = HOLD
            confidence = 0.0
            reasons.append("Weighted score is neutral")

        return TimeframeSignal(
            signal=signal,
            confidence=confidence,
            buy_score=round(buy_score, 2),
            sell_score=round(sell_score, 2),
            reasons=tuple(reasons + warnings),
            metadata={
                "score": round(score, 4),
                "adx14": round(adx_value, 2),
                "atr_pct": round(atr_pct, 6),
                "volatility_factor": round(volatility_factor, 3),
                "warnings": warnings,
            },
        )

    def latest_snapshot(self, enriched: pd.DataFrame) -> dict:
        if enriched.empty:
            return {}

        last = enriched.iloc[-1]
        return {
            "time": str(last["time"]),
            "close": _clean_float(last["close"]),
            "ema20": _clean_float(last["ema20"]),
            "ema50": _clean_float(last["ema50"]),
            "rsi14": _clean_float(last["rsi14"]),
            "macd": _clean_float(last["macd"]),
            "macd_signal": _clean_float(last["macd_signal"]),
            "macd_hist": _clean_float(last.get("macd_hist")),
            "atr14": _clean_float(last["atr14"]),
            "atr_pct": _clean_float(last.get("atr_pct")),
            "adx14": _clean_float(last.get("adx14")),
        }

    def combine_timeframes(
        self,
        timeframes: Mapping[str, TimeframeDecision],
    ) -> tuple[str, float, tuple[str, ...], dict]:
        weighted_score = 0.0
        confidence_total = 0.0
        total_weight = 0.0
        strong_buy = 0
        strong_sell = 0

        for timeframe, decision in timeframes.items():
            weight = float(self.timeframe_weights.get(timeframe, 1.0))
            signal = decision.signal.signal
            signal_score = _safe_float(decision.signal.metadata.get("score"))
            weighted_score += signal_score * weight
            confidence_total += decision.signal.confidence * weight
            total_weight += weight
            if signal == BUY:
                strong_buy += 1
            elif signal == SELL:
                strong_sell += 1

        average_score = weighted_score / total_weight if total_weight else 0.0
        average_confidence = confidence_total / total_weight if total_weight else 0.0
        confirming = timeframes.get(self.confirming_timeframe)
        confirming_signal = confirming.signal.signal if confirming else HOLD
        confirming_score = (
            _safe_float(confirming.signal.metadata.get("score"))
            if confirming
            else 0.0
        )

        bullish_confirmation = confirming_signal in {BUY, WEAK_BUY} and confirming_score > 0
        bearish_confirmation = confirming_signal in {SELL, WEAK_SELL} and confirming_score < 0

        if (
            average_score >= self.final_score_threshold
            and bullish_confirmation
            and strong_sell == 0
        ):
            final_signal = BUY
        elif (
            average_score <= -self.final_score_threshold
            and bearish_confirmation
            and strong_buy == 0
        ):
            final_signal = SELL
        else:
            final_signal = HOLD

        confidence = min(
            0.95,
            max(0.0, 0.42 + abs(average_score) / 2.8 + average_confidence * 0.32),
        )
        if final_signal == HOLD:
            confidence = min(confidence, 0.52)

        reasons = (
            f"Weighted score {average_score:.2f}",
            f"{self.confirming_timeframe} confirmation: {confirming_signal}",
        )
        aggregate = {
            "weighted_score": round(weighted_score, 4),
            "average_score": round(average_score, 4),
            "average_timeframe_confidence": round(average_confidence, 4),
            "strong_buy_timeframes": strong_buy,
            "strong_sell_timeframes": strong_sell,
            "confirming_timeframe": self.confirming_timeframe,
            "confirming_score": round(confirming_score, 4),
        }
        return final_signal, confidence, reasons, aggregate


class EURUSDStrategy(IndicatorScoreStrategy):
    name = "eurusd_ema_rsi_macd"
    profile = PAIR_PROFILES["EURUSD"]


class GBPUSDStrategy(IndicatorScoreStrategy):
    name = "gbpusd_ema_rsi_macd"
    profile = PAIR_PROFILES["GBPUSD"]


class USDJPYStrategy(IndicatorScoreStrategy):
    name = "usdjpy_ema_rsi_macd"
    profile = PAIR_PROFILES["USDJPY"]


PAIR_STRATEGY_CLASSES = {
    "EURUSD": EURUSDStrategy,
    "GBPUSD": GBPUSDStrategy,
    "USDJPY": USDJPYStrategy,
}


def default_strategy_registry(
    risk_policy: RiskPolicy | None = None,
) -> dict[str, CurrencyPairStrategy]:
    return {
        symbol: strategy_class(risk_policy=risk_policy)
        for symbol, strategy_class in PAIR_STRATEGY_CLASSES.items()
    }


def timeframe_signal(df: pd.DataFrame) -> dict:
    """Backward-compatible helper for callers that only need one timeframe."""

    strategy = IndicatorScoreStrategy()
    enriched = add_indicators(df) if not df.empty else df
    return strategy.timeframe_signal(enriched).to_dict()


class StrategyEngine:
    def __init__(
        self,
        market_data: MarketDataService | None = None,
        strategies: Mapping[str, CurrencyPairStrategy] | None = None,
        default_strategy: CurrencyPairStrategy | None = None,
        risk_policy: RiskPolicy | None = None,
    ):
        self.market_data = market_data or MarketDataService()
        if risk_policy is None and hasattr(self.market_data, "connection"):
            risk_policy = RiskPolicy.from_settings(self.market_data.connection.settings)

        self.risk_policy = risk_policy or RiskPolicy()
        self.strategies = default_strategy_registry(self.risk_policy)
        self.default_strategy = default_strategy or IndicatorScoreStrategy(
            risk_policy=self.risk_policy,
        )

        for symbol, strategy in (strategies or {}).items():
            self.register_strategy(symbol, strategy)

    def register_strategy(self, symbol: str, strategy: CurrencyPairStrategy) -> None:
        self.strategies[symbol.upper()] = strategy

    def strategy_for_symbol(self, symbol: str) -> CurrencyPairStrategy:
        return self.strategies.get(symbol.upper(), self.default_strategy)

    @staticmethod
    def _optional_market_call(callback, default=None):
        try:
            return callback()
        except Exception:
            return default

    def build_state(self, symbol: str, strategy: CurrencyPairStrategy) -> StrategyState:
        symbol = symbol.upper()
        candles = {
            timeframe: self.market_data.candles(
                symbol,
                timeframe,
                count=strategy.candle_count,
            )
            for timeframe in strategy.timeframes
        }
        return StrategyState(
            symbol=symbol,
            profile=strategy.profile,
            candles=candles,
            tick=self._optional_market_call(
                lambda: self.market_data.tick_info(symbol),
            ),
            account=self._optional_market_call(self.market_data.account_snapshot),
            positions=tuple(
                self._optional_market_call(
                    lambda: self.market_data.positions(symbol),
                    [],
                )
            ),
            all_positions=tuple(
                self._optional_market_call(self.market_data.positions, [])
            ),
            pending_orders=tuple(
                self._optional_market_call(
                    lambda: self.market_data.pending_orders(symbol),
                    [],
                )
            ),
            all_pending_orders=tuple(
                self._optional_market_call(self.market_data.pending_orders, [])
            ),
            daily_realized_profit=self._optional_market_call(
                self.market_data.daily_realized_profit
            ),
            now_utc=datetime.now(timezone.utc),
        )

    def analyze_timeframe(self, symbol: str, timeframe: str) -> dict:
        symbol = symbol.upper()
        strategy = self.strategy_for_symbol(symbol)
        df = self.market_data.candles(symbol, timeframe, count=strategy.candle_count)
        state = StrategyState(
            symbol=symbol,
            profile=strategy.profile,
            candles={timeframe: df},
        )
        return strategy.analyze_timeframe(state, timeframe).to_dict()

    def analyze_symbol(self, symbol: str) -> dict:
        symbol = symbol.upper()
        strategy = self.strategy_for_symbol(symbol)
        state = self.build_state(symbol, strategy)
        return strategy.evaluate(state).to_dict()

    def snapshot(self, symbols: tuple[str, ...] = SYMBOLS) -> dict:
        return {
            "symbols": [self.analyze_symbol(symbol) for symbol in symbols],
        }
