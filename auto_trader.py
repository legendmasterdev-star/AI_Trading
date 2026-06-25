import time
from datetime import datetime

from trading_backend.ai_decision import AIDecisionEngine
from trading_backend.execution import OrderExecutor
from trading_backend.market_data import MarketDataService
from trading_backend.mt5_client import MT5Connection
from trading_backend.settings import load_settings
from trading_backend.custom_strategies import register_custom_strategies
from trading_backend.strategies import StrategyEngine


def print_account(account: dict) -> None:
    print(
        f"\nACCOUNT | Balance: {account.get('balance')} {account.get('currency')} | "
        f"Equity: {account.get('equity')} | Profit: {account.get('profit')} | "
        f"Free Margin: {account.get('margin_free')}"
    )


def manage_symbol(
    symbol: str,
    market_data: MarketDataService,
    executor: OrderExecutor,
    ai_engine: AIDecisionEngine,
    live_enabled: bool,
) -> None:
    decision = ai_engine.decide_symbol(symbol)
    action = decision["action"]
    target_side = decision["target_side"]
    dry_run = not live_enabled

    print("=" * 100)
    print(f"{datetime.now()} | {symbol}")
    print(
        f"AI action: {action} | Target: {target_side or '-'} | "
        f"Confidence: {decision['confidence']} | Risk: {decision['risk_level']}"
    )
    for reason in decision["reasons"]:
        print(f"- {reason}")

    positions = market_data.positions(symbol)
    if action in {"BUY", "SELL"}:
        result = executor.strategy_order(symbol, action, dry_run=dry_run)
        print(result)
        return

    if action == "CLOSE_AND_REVERSE" and target_side:
        for position in positions:
            result = executor.close_position(position["ticket"], dry_run=dry_run)
            print(result)
            time.sleep(1)

        result = executor.strategy_order(symbol, target_side, dry_run=dry_run)
        print(result)
        return

    if positions:
        for position in positions:
            direction = "BUY" if position.get("type") == 0 else "SELL"
            print(
                f"Existing position ticket={position.get('ticket')} "
                f"direction={direction} volume={position.get('volume')} "
                f"profit={position.get('profit')}"
            )
    else:
        print(f"{symbol}: no order placed.")


def run_auto_trader() -> None:
    settings = load_settings()
    connection = MT5Connection(settings)
    market_data = MarketDataService(connection)
    strategy_engine = StrategyEngine(market_data)
    # Use the custom per-pair strategies (same as the dashboard in api.py).
    # Comment out to fall back to the default EMA/RSI/MACD strategies.
    register_custom_strategies(strategy_engine)
    ai_engine = AIDecisionEngine(strategy_engine, market_data)
    executor = OrderExecutor(connection, market_data)

    connection.connect()
    connection.prepare_symbols(settings.symbols)

    print("Auto trader started.")
    print(f"Live order execution: {'ON' if settings.auto_trade_enabled else 'OFF - dry run'}")
    print("Press CTRL+C to stop.")

    while True:
        print_account(market_data.account_snapshot())

        for symbol in settings.symbols:
            try:
                manage_symbol(symbol, market_data, executor, ai_engine, settings.auto_trade_enabled)
            except Exception as error:
                print(f"{symbol}: {error}")

        time.sleep(settings.check_interval_seconds)


if __name__ == "__main__":
    try:
        run_auto_trader()
    except KeyboardInterrupt:
        print("\nAuto trader stopped by user.")
    finally:
        MT5Connection().shutdown()
