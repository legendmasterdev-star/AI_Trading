"""
Custom per-pair trading strategies (drop-in).

Each class keeps the project's standard contract:
    evaluate(StrategyState) -> StrategyDecision

They subclass ``IndicatorScoreStrategy`` so they reuse the existing
multi-timeframe machinery (analyze_timeframe -> timeframe_signal ->
combine_timeframes) and, importantly, the risk guardrails in
``assess_trade_risk`` (spread, drawdown, exposure, sessions, kill switch...).
Only the per-timeframe scoring is replaced with a different idea per pair:

  * EUR/USD  -> Trend + pullback. Trade WITH the higher-timeframe trend, but
               only enter on a pullback that resumes (buy the dip / sell the
               rally). EUR/USD trends smoothly and mean-reverts intraday.
  * GBP/USD  -> Momentum breakout. Cable is volatile and impulsive: trade
               breakouts of the recent range, confirmed by rising ADX and
               expanding ATR. Avoid chop when ADX is low.
  * USD/JPY  -> Aligned trend-follow. JPY trends persist: require EMA, price
               and MACD to all agree, weight the H1 timeframe heavily, and
               demand stronger ADX before committing.

How to use
----------
In ``trading_backend/api.py``, right after the strategy engine is created:

    strategy_engine = StrategyEngine(market_data)
    from .custom_strategies import register_custom_strategies
    register_custom_strategies(strategy_engine)   # <- activates these

Comment that last line out to fall back to the default strategies.

You can also tune any of the numbers below (thresholds, weights, lookbacks)
and just restart ``python backend.py`` to test the change.
"""

from __future__ import annotations

import pandas as pd

from .strategies import (
    BUY,
    HOLD,
    PAIR_PROFILES,
    SELL,
    WEAK_BUY,
    WEAK_SELL,
    IndicatorScoreStrategy,
    TimeframeSignal,
)

# Columns produced by indicators.add_indicators that every strategy below uses.
_REQUIRED_COLUMNS = (
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


def _num(value, default: float = 0.0) -> float:
    """Safe float: turn NaN / None / bad values into a default."""
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


class _TunedStrategy(IndicatorScoreStrategy):
    """Shared scaffolding for the pair strategies below.

    Subclasses only implement ``timeframe_signal`` and produce a single signed
    ``score`` (positive = bullish, negative = bearish). ``_finalize`` converts
    that score into the standard ``TimeframeSignal`` the rest of the engine
    expects, and ``combine_timeframes`` (inherited) aggregates across M5/M15/H1
    with the H1 confirmation rule.
    """

    def _latest(self, enriched: pd.DataFrame):
        """Return (last_row, prev_row) once indicators are warm, else None."""
        if enriched is None or enriched.empty or len(enriched) < self.min_candles:
            return None
        last = enriched.iloc[-1]
        if any(pd.isna(last.get(column)) for column in _REQUIRED_COLUMNS):
            return None
        return last, enriched.iloc[-2]

    def _warmup_signal(self, enriched: pd.DataFrame) -> TimeframeSignal:
        too_short = enriched is None or enriched.empty or len(enriched) < self.min_candles
        reason = "Not enough candle data" if too_short else "Indicator warmup is not ready"
        return TimeframeSignal(signal=HOLD, confidence=0.0, buy_score=0, sell_score=0, reasons=(reason,))

    def _volatility_adjust(self, score: float, atr_pct: float, warnings: list[str]) -> float:
        """Dampen the score when volatility is outside the pair's healthy band."""
        low = _num(self.profile.get("min_atr_pct"), 0.0)
        high = _num(self.profile.get("max_atr_pct"), 1.0)
        if low and atr_pct < low:
            warnings.append("Volatility is compressed")
            return score * 0.82
        if high and atr_pct > high:
            warnings.append("Volatility is unusually elevated")
            return score * 0.80
        return score

    def _finalize(
        self,
        score: float,
        reasons: list[str],
        warnings: list[str],
        extra: dict | None = None,
    ) -> TimeframeSignal:
        score = float(score)
        abs_score = abs(score)
        base_confidence = min(0.92, 0.42 + abs_score / 4.2)
        if warnings:
            base_confidence = max(0.0, base_confidence - 0.08)

        if score >= self.strong_timeframe_score:
            signal, confidence = BUY, max(base_confidence, 0.76)
        elif score <= -self.strong_timeframe_score:
            signal, confidence = SELL, max(base_confidence, 0.76)
        elif score >= self.weak_timeframe_score:
            signal, confidence = WEAK_BUY, max(0.52, min(base_confidence, 0.68))
        elif score <= -self.weak_timeframe_score:
            signal, confidence = WEAK_SELL, max(0.52, min(base_confidence, 0.68))
        else:
            signal, confidence = HOLD, 0.0
            reasons = list(reasons) + ["Weighted score is neutral"]

        metadata = {"score": round(score, 4), "warnings": list(warnings)}
        if extra:
            metadata.update(extra)

        return TimeframeSignal(
            signal=signal,
            confidence=confidence,
            buy_score=round(max(0.0, score), 2),
            sell_score=round(max(0.0, -score), 2),
            reasons=tuple(list(reasons) + list(warnings)),
            metadata=metadata,
        )


class EURUSDPullbackStrategy(_TunedStrategy):
    """EUR/USD: trade with the trend, enter on resuming pullbacks."""

    name = "eurusd_trend_pullback"
    profile = PAIR_PROFILES["EURUSD"]
    timeframe_weights = {"M5": 1.0, "M15": 1.5, "H1": 2.1}
    adx_trend_threshold = 18
    strong_timeframe_score = 2.2
    weak_timeframe_score = 1.0
    final_score_threshold = 0.55
    pullback_rsi = 45  # how deep a dip counts as a pullback in an uptrend

    def timeframe_signal(self, enriched: pd.DataFrame) -> TimeframeSignal:
        rows = self._latest(enriched)
        if rows is None:
            return self._warmup_signal(enriched)
        last, prev = rows

        close = _num(last["close"])
        ema20, ema50 = _num(last["ema20"]), _num(last["ema50"])
        ema20_prev = _num(prev["ema20"])
        close_prev = _num(prev["close"])
        rsi, rsi_prev = _num(last["rsi14"]), _num(prev["rsi14"])
        macd, macd_signal = _num(last["macd"]), _num(last["macd_signal"])
        hist, hist_prev = _num(last["macd_hist"]), _num(prev["macd_hist"])
        adx, atr_pct = _num(last["adx14"]), _num(last["atr_pct"])

        reasons: list[str] = []
        warnings: list[str] = []
        score = 0.0

        trend_up = ema20 > ema50 and ema20 >= ema20_prev
        trend_down = ema20 < ema50 and ema20 <= ema20_prev

        if trend_up:
            score += 1.0
            reasons.append("Uptrend: EMA20 above EMA50")
            pulled_back = close_prev < ema20_prev or rsi_prev < self.pullback_rsi
            reclaimed = close >= ema20 and rsi > rsi_prev
            if pulled_back and reclaimed:
                score += 1.3
                reasons.append("Bullish pullback reclaiming EMA20")
            if macd > macd_signal and hist > hist_prev:
                score += 0.6
                reasons.append("MACD turning up")
            if 55 <= rsi <= 70:
                score += 0.3
                reasons.append("Momentum resuming higher")
            if rsi > 72:
                score -= 0.4
                warnings.append("Overbought - avoid chasing")
        elif trend_down:
            score -= 1.0
            reasons.append("Downtrend: EMA20 below EMA50")
            pulled_back = close_prev > ema20_prev or rsi_prev > (100 - self.pullback_rsi)
            rejected = close <= ema20 and rsi < rsi_prev
            if pulled_back and rejected:
                score -= 1.3
                reasons.append("Bearish pullback rejecting EMA20")
            if macd < macd_signal and hist < hist_prev:
                score -= 0.6
                reasons.append("MACD turning down")
            if 30 <= rsi <= 45:
                score -= 0.3
                reasons.append("Momentum resuming lower")
            if rsi < 28:
                score += 0.4
                warnings.append("Oversold - avoid chasing")
        else:
            reasons.append("No clear EMA trend")

        if adx >= self.adx_trend_threshold:
            score *= 1.12
            reasons.append(f"ADX {adx:.0f} confirms trend strength")
        else:
            score *= 0.72
            warnings.append("Weak ADX - choppy conditions")

        score = self._volatility_adjust(score, atr_pct, warnings)
        return self._finalize(
            score,
            reasons,
            warnings,
            {"adx14": round(adx, 2), "atr_pct": round(atr_pct, 6)},
        )


class GBPUSDBreakoutStrategy(_TunedStrategy):
    """GBP/USD: momentum breakouts of the recent range, ADX/ATR confirmed."""

    name = "gbpusd_momentum_breakout"
    profile = PAIR_PROFILES["GBPUSD"]
    timeframe_weights = {"M5": 1.1, "M15": 1.4, "H1": 1.9}
    adx_trend_threshold = 20
    strong_timeframe_score = 2.1
    weak_timeframe_score = 1.0
    final_score_threshold = 0.50
    breakout_lookback = 20  # bars of range to break out of (excludes current bar)

    def timeframe_signal(self, enriched: pd.DataFrame) -> TimeframeSignal:
        rows = self._latest(enriched)
        if rows is None or len(enriched) < self.breakout_lookback + 2:
            return self._warmup_signal(enriched)
        last, prev = rows

        window = enriched.iloc[-(self.breakout_lookback + 1):-1]
        recent_high = _num(window["high"].max())
        recent_low = _num(window["low"].min())

        close = _num(last["close"])
        macd, macd_signal = _num(last["macd"]), _num(last["macd_signal"])
        adx, adx_prev = _num(last["adx14"]), _num(prev["adx14"])
        atr, atr_prev = _num(last["atr14"]), _num(prev["atr14"])
        atr_pct, rsi = _num(last["atr_pct"]), _num(last["rsi14"])

        reasons: list[str] = []
        warnings: list[str] = []
        score = 0.0

        adx_rising = adx > adx_prev
        atr_expanding = atr > atr_prev

        if recent_high > 0 and close > recent_high:
            score += 1.7
            reasons.append(f"Breakout above {self.breakout_lookback}-bar high")
            if macd > macd_signal:
                score += 0.4
                reasons.append("MACD bullish")
            if adx >= self.adx_trend_threshold and adx_rising:
                score += 0.5
                reasons.append("Rising ADX backs the breakout")
            if atr_expanding:
                score += 0.3
                reasons.append("Volatility expanding")
            if rsi > 78:
                score -= 0.3
                warnings.append("Extended - late breakout risk")
        elif recent_low > 0 and close < recent_low:
            score -= 1.7
            reasons.append(f"Breakout below {self.breakout_lookback}-bar low")
            if macd < macd_signal:
                score -= 0.4
                reasons.append("MACD bearish")
            if adx >= self.adx_trend_threshold and adx_rising:
                score -= 0.5
                reasons.append("Rising ADX backs the breakdown")
            if atr_expanding:
                score -= 0.3
                reasons.append("Volatility expanding")
            if rsi < 22:
                score += 0.3
                warnings.append("Extended - late breakdown risk")
        else:
            # No fresh breakout: only ride clear, trend-backed momentum.
            if macd > macd_signal and adx >= self.adx_trend_threshold:
                score += 0.6
                reasons.append("Bullish momentum inside range")
            elif macd < macd_signal and adx >= self.adx_trend_threshold:
                score -= 0.6
                reasons.append("Bearish momentum inside range")
            else:
                reasons.append("Inside range - waiting for a breakout")

        if adx < self.adx_trend_threshold:
            score *= 0.6
            warnings.append("Low ADX - rangebound / chop")

        score = self._volatility_adjust(score, atr_pct, warnings)
        return self._finalize(
            score,
            reasons,
            warnings,
            {
                "adx14": round(adx, 2),
                "atr_pct": round(atr_pct, 6),
                "recent_high": round(recent_high, 5),
                "recent_low": round(recent_low, 5),
            },
        )


class USDJPYTrendStrategy(_TunedStrategy):
    """USD/JPY: strict aligned trend-following, heavy H1 weighting."""

    name = "usdjpy_trend_follow"
    profile = PAIR_PROFILES["USDJPY"]
    timeframe_weights = {"M5": 0.9, "M15": 1.4, "H1": 2.3}
    adx_trend_threshold = 22
    strong_timeframe_score = 2.3
    weak_timeframe_score = 1.1
    final_score_threshold = 0.60

    def timeframe_signal(self, enriched: pd.DataFrame) -> TimeframeSignal:
        rows = self._latest(enriched)
        if rows is None:
            return self._warmup_signal(enriched)
        last, prev = rows

        close = _num(last["close"])
        ema20, ema50 = _num(last["ema20"]), _num(last["ema50"])
        macd, macd_signal = _num(last["macd"]), _num(last["macd_signal"])
        hist, hist_prev = _num(last["macd_hist"]), _num(prev["macd_hist"])
        adx, rsi, atr_pct = _num(last["adx14"]), _num(last["rsi14"]), _num(last["atr_pct"])

        reasons: list[str] = []
        warnings: list[str] = []
        score = 0.0

        bull_aligned = ema20 > ema50 and close > ema20 and macd > macd_signal
        bear_aligned = ema20 < ema50 and close < ema20 and macd < macd_signal

        if bull_aligned:
            score += 1.5
            reasons.append("Aligned uptrend (EMA + price + MACD)")
            if adx >= self.adx_trend_threshold:
                score += min(1.0, 0.5 + (adx - self.adx_trend_threshold) / 20)
                reasons.append(f"Strong ADX {adx:.0f}")
            else:
                warnings.append("Trend strength still building")
            if hist > 0 and hist > hist_prev:
                score += 0.4
                reasons.append("MACD accelerating")
            if 50 <= rsi <= 72:
                score += 0.3
            elif rsi > 78:
                score -= 0.4
                warnings.append("Overbought")
        elif bear_aligned:
            score -= 1.5
            reasons.append("Aligned downtrend (EMA + price + MACD)")
            if adx >= self.adx_trend_threshold:
                score -= min(1.0, 0.5 + (adx - self.adx_trend_threshold) / 20)
                reasons.append(f"Strong ADX {adx:.0f}")
            else:
                warnings.append("Trend strength still building")
            if hist < 0 and hist < hist_prev:
                score -= 0.4
                reasons.append("MACD accelerating lower")
            if 28 <= rsi <= 50:
                score -= 0.3
            elif rsi < 22:
                score += 0.4
                warnings.append("Oversold")
        else:
            reasons.append("Trend not aligned across EMA / price / MACD")

        score = self._volatility_adjust(score, atr_pct, warnings)
        return self._finalize(
            score,
            reasons,
            warnings,
            {"adx14": round(adx, 2), "atr_pct": round(atr_pct, 6)},
        )


# Symbol -> strategy class, mirrors strategies.PAIR_STRATEGY_CLASSES.
CUSTOM_PAIR_STRATEGIES = {
    "EURUSD": EURUSDPullbackStrategy,
    "GBPUSD": GBPUSDBreakoutStrategy,
    "USDJPY": USDJPYTrendStrategy,
}


def register_custom_strategies(engine) -> object:
    """Register these strategies on a StrategyEngine, reusing its risk policy.

    Returns the same engine so it can be chained. Safe to call once at startup.
    """
    risk_policy = getattr(engine, "risk_policy", None)
    for symbol, strategy_class in CUSTOM_PAIR_STRATEGIES.items():
        engine.register_strategy(symbol, strategy_class(risk_policy=risk_policy))
    return engine
