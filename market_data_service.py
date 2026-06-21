import time

from trading_backend.market_data import MarketDataService
from trading_backend.mt5_client import MT5Connection
from trading_backend.settings import load_settings
from trading_backend.strategies import StrategyEngine


def print_report(report: dict, strategy: dict) -> None:
    symbol = report["symbol"]
    tick = report.get("tick") or {}

    print("=" * 110)
    print(f"SYMBOL: {symbol}")
    print(
        f"Tick: {tick.get('time')} | Bid: {tick.get('bid')} | "
        f"Ask: {tick.get('ask')} | Spread: {tick.get('spread_points')} points"
    )
    print(f"Open Positions: {len(report.get('positions', []))}")
    print(f"Pending Orders: {len(report.get('pending_orders', []))}")
    print(
        f"Final Strategy: {strategy['final_signal']} | "
        f"Confidence: {strategy['confidence']}"
    )

    for timeframe, data in report["timeframes"].items():
        latest = data.get("latest")
        if latest is None:
            print(f"{timeframe}: No data")
            continue

        print(
            f"{timeframe} | Close: {latest.get('close')} | "
            f"EMA20: {latest.get('ema20')} | EMA50: {latest.get('ema50')} | "
            f"RSI14: {latest.get('rsi14')} | MACD: {latest.get('macd')} | "
            f"ATR14: {latest.get('atr14')}"
        )


def run_market_data_loop(interval_seconds: int = 10) -> None:
    settings = load_settings()
    connection = MT5Connection(settings)
    market_data = MarketDataService(connection)
    strategy_engine = StrategyEngine(market_data)

    connection.connect()
    connection.prepare_symbols(settings.symbols)

    while True:
        account = market_data.account_snapshot()
        print("\n\nACCOUNT")
        print(
            f"Balance: {account['balance']} {account['currency']} | "
            f"Equity: {account['equity']} | Free Margin: {account['margin_free']} | "
            f"Profit: {account['profit']}"
        )

        for symbol in settings.symbols:
            report = market_data.symbol_report(symbol)
            strategy = strategy_engine.analyze_symbol(symbol)
            print_report(report, strategy)

        time.sleep(interval_seconds)


if __name__ == "__main__":
    try:
        run_market_data_loop(interval_seconds=10)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        MT5Connection().shutdown()
