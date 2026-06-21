from __future__ import annotations

from .market_data import MarketDataService
from .settings import DEFAULT_MAX_SPREAD_POINTS, SYMBOLS
from .strategies import StrategyEngine


class AIDecisionEngine:
    """Local decision layer that scores strategy, spread, and position context."""

    def __init__(
        self,
        strategy_engine: StrategyEngine | None = None,
        market_data: MarketDataService | None = None,
    ):
        self.market_data = market_data or MarketDataService()
        self.strategy_engine = strategy_engine or StrategyEngine(self.market_data)

    def decide_symbol(self, symbol: str) -> dict:
        strategy = self.strategy_engine.analyze_symbol(symbol)
        tick = self.market_data.tick_info(symbol)
        positions = self.market_data.positions(symbol)
        final_signal = strategy["final_signal"]
        confidence = strategy["confidence"]
        strategy_risk = strategy.get("metadata", {}).get("risk", {})
        spread_limit = strategy_risk.get(
            "checks",
            {},
        ).get("max_spread_points", DEFAULT_MAX_SPREAD_POINTS.get(symbol, 15.0))
        spread = tick["spread_points"] if tick else None
        reasons = []

        action = "HOLD"
        risk_level = "LOW"

        if spread is None:
            reasons.append("No realtime tick is available")
        elif spread > spread_limit:
            reasons.append(f"Spread {spread} is above limit {spread_limit}")
            risk_level = "HIGH"

        if final_signal == "HOLD":
            risk_blockers = strategy_risk.get("blockers", [])
            risk_warnings = strategy_risk.get("warnings", [])
            raw_signal = strategy.get("metadata", {}).get("raw_signal")
            if raw_signal in {"BUY", "SELL"} and risk_blockers:
                reasons.extend(risk_blockers)
                risk_level = "HIGH"
            elif raw_signal in {"BUY", "SELL"} and risk_warnings:
                reasons.extend(risk_warnings)
                risk_level = "MEDIUM"
            else:
                reasons.append("Strategy agreement is not strong enough")
        elif confidence < 0.65:
            reasons.append(f"Confidence {confidence} is below execution threshold")
        elif spread is not None and spread <= spread_limit:
            existing_direction = self._current_direction(positions)
            if existing_direction is None:
                action = final_signal
                reasons.append(f"{final_signal} signal confirmed with no open position")
            elif existing_direction == final_signal:
                action = "HOLD_MANAGE"
                reasons.append(f"Existing {existing_direction} position matches signal")
            else:
                action = "CLOSE_AND_REVERSE"
                risk_level = "MEDIUM"
                reasons.append(
                    f"Existing {existing_direction} position conflicts with {final_signal}"
                )

        if not reasons:
            reasons.append("Risk filters blocked execution")

        return {
            "symbol": symbol,
            "action": action,
            "target_side": final_signal if final_signal in {"BUY", "SELL"} else None,
            "confidence": confidence,
            "risk_level": risk_level,
            "spread_points": spread,
            "position_count": len(positions),
            "reasons": reasons,
            "strategy": strategy,
            "order_plan": {
                "symbol": symbol,
                "side": final_signal if action in {"BUY", "SELL", "CLOSE_AND_REVERSE"} else None,
                "volume": 0.01,
                "source": "ai_decision",
            },
        }

    def decide_all(self, symbols: tuple[str, ...] = SYMBOLS) -> dict:
        return {
            "decisions": [self.decide_symbol(symbol) for symbol in symbols],
        }

    @staticmethod
    def _current_direction(positions: list[dict]) -> str | None:
        if not positions:
            return None
        first = positions[0]
        position_type = first.get("type")
        if position_type == 0:
            return "BUY"
        if position_type == 1:
            return "SELL"
        return "UNKNOWN"
