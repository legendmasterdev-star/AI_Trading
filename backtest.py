"""
Backtester for the custom per-pair strategies.

It replays historical MetaTrader 5 candles bar-by-bar through the same
strategy code the live app uses (custom_strategies.py), simulating ATR-based
stop-loss / take-profit exits, and reports realistic performance metrics so you
can judge whether an idea actually makes money before risking capital.

What it measures per pair (and combined):
  - trades, win rate
  - gross win / gross loss (in pips) and profit factor
  - net pips and average R-multiple (reward measured in units of risk)
  - max drawdown (in R) on the equity curve
  - a simple return estimate at a chosen risk-per-trade %

Honest limitations (read these):
  * It uses each bar's high/low to detect SL/TP hits. If both are touched in the
    same bar, it assumes the STOP hit first (conservative).
  * Entries fill at the signal bar's close; spread, slippage and commission are
    NOT modelled, so live results will be worse than the backtest.
  * Multi-timeframe values are computed on the full series then sliced to each
    point in time. Rolling/EWM indicators only look backwards, so this is
    look-ahead-free, but it is still in-sample on whatever window you fetch.
  * Past performance does not predict future performance.

Usage:
    python backtest.py                 # all pairs, ~3000 M15 bars (~1 month)
    python backtest.py --bars 6000     # longer window
    python backtest.py --symbol EURUSD --risk-pct 1.0
"""

from __future__ import annotations

import argparse

import pandas as pd

from trading_backend.custom_strategies import CUSTOM_PAIR_STRATEGIES
from trading_backend.indicators import add_indicators
from trading_backend.market_data import MarketDataService
from trading_backend.mt5_client import MT5Connection
from trading_backend.settings import load_settings
from trading_backend.strategies import BUY, HOLD, SELL, StrategyState, TimeframeDecision

PIP_SIZE = {"EURUSD": 0.0001, "GBPUSD": 0.0001, "USDJPY": 0.01}
STEP_TIMEFRAME = "M15"  # cadence we evaluate signals and manage trades on
SL_ATR_MULTIPLE = 2.0   # matches execution.strategy_order
TP_ATR_MULTIPLE = 3.0


def pip_size(symbol: str) -> float:
    return PIP_SIZE.get(symbol, 0.0001)


def fetch_data(market_data: MarketDataService, symbol: str, strategy, bars: int) -> dict:
    """Pull raw candles per timeframe, sized so each spans a similar period."""
    per_tf = {"M5": bars * 3, "M15": bars, "H1": max(300, bars // 4)}
    data = {}
    for timeframe in strategy.timeframes:
        count = per_tf.get(timeframe, bars)
        df = market_data.candles(symbol, timeframe, count=count)
        if df is None or df.empty:
            raise RuntimeError(f"No {timeframe} candles returned for {symbol}")
        data[timeframe] = df.reset_index(drop=True)
    return data


def _signal_at(strategy, enriched: dict, symbol: str, when):
    """Raw (pre-risk) signal + confidence + M15 ATR at a point in time."""
    decisions = {}
    atr = None
    for timeframe in strategy.timeframes:
        sliced = enriched[timeframe][enriched[timeframe]["time"] <= when]
        signal = strategy.timeframe_signal(sliced)
        snapshot = strategy.latest_snapshot(sliced)
        decisions[timeframe] = TimeframeDecision(
            symbol=symbol, timeframe=timeframe, signal=signal, latest=snapshot,
        )
        if timeframe == STEP_TIMEFRAME:
            atr = snapshot.get("atr14")
    raw_signal, confidence, _reasons, _aggregate = strategy.combine_timeframes(decisions)
    return raw_signal, confidence, atr


def simulate(symbol: str, strategy, data: dict, risk_pct: float = 1.0) -> dict:
    """Replay the strategy over history and return performance metrics."""
    enriched = {tf: add_indicators(df) for tf, df in data.items()}
    step = enriched[STEP_TIMEFRAME].reset_index(drop=True)
    pip = pip_size(symbol)
    warmup = max(strategy.min_candles, getattr(strategy, "breakout_lookback", 0) + 2)

    # Start only once every timeframe has enough history to be valid.
    start_time = max(
        enriched[tf]["time"].iloc[min(warmup, len(enriched[tf]) - 1)]
        for tf in strategy.timeframes
    )

    position = None
    trades = []

    for i in range(len(step)):
        bar = step.iloc[i]
        when = bar["time"]
        if when < start_time:
            continue

        high, low, close = float(bar["high"]), float(bar["low"]), float(bar["close"])

        # 1) Manage an open position against this bar's range (stop checked first).
        if position is not None:
            exit_price = None
            reason = None
            if position["side"] == BUY:
                if low <= position["sl"]:
                    exit_price, reason = position["sl"], "SL"
                elif high >= position["tp"]:
                    exit_price, reason = position["tp"], "TP"
            else:
                if high >= position["sl"]:
                    exit_price, reason = position["sl"], "SL"
                elif low <= position["tp"]:
                    exit_price, reason = position["tp"], "TP"
            if exit_price is not None:
                trades.append(_close(position, exit_price, pip, reason))
                position = None

        # 2) Evaluate the strategy at this bar.
        raw_signal, _confidence, atr = _signal_at(strategy, enriched, symbol, when)

        # 3) Opposite signal closes an open trade at the bar close.
        if position is not None and raw_signal in (BUY, SELL) and raw_signal != position["side"]:
            trades.append(_close(position, close, pip, "signal"))
            position = None

        # 4) Open a fresh trade on a directional signal.
        if position is None and raw_signal in (BUY, SELL) and atr and atr > 0:
            risk = atr * SL_ATR_MULTIPLE
            reward = atr * TP_ATR_MULTIPLE
            position = {
                "side": raw_signal,
                "entry": close,
                "entry_time": when,
                "sl": close - risk if raw_signal == BUY else close + risk,
                "tp": close + reward if raw_signal == BUY else close - reward,
                "risk_pips": risk / pip,
            }

    return _summarize(symbol, strategy, trades, risk_pct)


def _close(position: dict, exit_price: float, pip: float, reason: str) -> dict:
    if position["side"] == BUY:
        pips = (exit_price - position["entry"]) / pip
    else:
        pips = (position["entry"] - exit_price) / pip
    risk_pips = position["risk_pips"] or 1.0
    return {
        "side": position["side"],
        "entry": position["entry"],
        "exit": exit_price,
        "pips": pips,
        "r": pips / risk_pips,
        "exit_reason": reason,
    }


def _summarize(symbol: str, strategy, trades: list[dict], risk_pct: float) -> dict:
    wins = [t for t in trades if t["pips"] > 0]
    losses = [t for t in trades if t["pips"] < 0]
    gross_win = sum(t["pips"] for t in wins)
    gross_loss = sum(-t["pips"] for t in losses)
    net_pips = sum(t["pips"] for t in trades)
    total_r = sum(t["r"] for t in trades)

    # Equity curve in R to derive max drawdown.
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        equity += t["r"]
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    return {
        "symbol": symbol,
        "strategy": strategy.name,
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(trades)) if trades else 0.0,
        "gross_win_pips": gross_win,
        "gross_loss_pips": gross_loss,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else None,
        "net_pips": net_pips,
        "total_r": total_r,
        "avg_r": (total_r / len(trades)) if trades else 0.0,
        "max_drawdown_r": max_dd,
        "return_pct_est": total_r * risk_pct,
    }


def _print_report(result: dict) -> None:
    pf = result["profit_factor"]
    print(f"\n{'=' * 64}")
    print(f"{result['symbol']}  |  {result['strategy']}")
    print(f"{'-' * 64}")
    print(f"  Trades        : {result['trades']}  (W {result['wins']} / L {result['losses']})")
    print(f"  Win rate      : {result['win_rate'] * 100:5.1f}%")
    print(f"  Profit factor : {'n/a' if pf is None else f'{pf:.2f}'}")
    print(f"  Net pips      : {result['net_pips']:+.1f}")
    print(f"  Total R       : {result['total_r']:+.2f}   (avg {result['avg_r']:+.2f} R/trade)")
    print(f"  Max drawdown  : {result['max_drawdown_r']:.2f} R")
    print(f"  Est. return   : {result['return_pct_est']:+.1f}%  (at chosen risk-per-trade)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest the custom strategies on MT5 history.")
    parser.add_argument("--symbol", help="Limit to one symbol, e.g. EURUSD")
    parser.add_argument("--bars", type=int, default=3000, help="M15 bars to test (default 3000)")
    parser.add_argument("--risk-pct", type=float, default=1.0, help="Risk per trade %% for return estimate")
    args = parser.parse_args()

    settings = load_settings()
    connection = MT5Connection(settings)
    market_data = MarketDataService(connection)
    connection.connect()
    connection.prepare_symbols(settings.symbols)

    symbols = [args.symbol.upper()] if args.symbol else list(CUSTOM_PAIR_STRATEGIES)
    results = []

    print(f"Backtesting {', '.join(symbols)} on ~{args.bars} {STEP_TIMEFRAME} bars")
    print("NOTE: spread/slippage/commission are not modelled; live results will be worse.")

    for symbol in symbols:
        strategy_class = CUSTOM_PAIR_STRATEGIES.get(symbol)
        if strategy_class is None:
            print(f"\n{symbol}: no custom strategy registered, skipping.")
            continue
        strategy = strategy_class()
        try:
            data = fetch_data(market_data, symbol, strategy, args.bars)
            result = simulate(symbol, strategy, data, risk_pct=args.risk_pct)
        except Exception as error:  # noqa: BLE001 - report and continue
            print(f"\n{symbol}: backtest failed: {error}")
            continue
        results.append(result)
        _print_report(result)

    if len(results) > 1:
        print(f"\n{'=' * 64}")
        print("PORTFOLIO (sum across pairs)")
        print(f"{'-' * 64}")
        total_trades = sum(r["trades"] for r in results)
        total_r = sum(r["total_r"] for r in results)
        net_pips = sum(r["net_pips"] for r in results)
        print(f"  Trades   : {total_trades}")
        print(f"  Net pips : {net_pips:+.1f}")
        print(f"  Total R  : {total_r:+.2f}")
        print(f"  Est ret  : {total_r * args.risk_pct:+.1f}%")

    connection.shutdown()


if __name__ == "__main__":
    main()
