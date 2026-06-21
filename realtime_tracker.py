import time

from trading_backend.market_data import MarketDataService
from trading_backend.mt5_client import MT5Connection
from trading_backend.settings import load_settings


def track_realtime_data(interval: int = 1) -> None:
    settings = load_settings()
    connection = MT5Connection(settings)
    market_data = MarketDataService(connection)

    connection.connect()
    connection.prepare_symbols(settings.symbols)

    print("\nTracking real-time forex data...")
    print("Press CTRL+C to stop.\n")

    while True:
        print("=" * 90)
        for symbol in settings.symbols:
            data = market_data.tick_info(symbol)
            print(
                f"{data['time']} | {data['symbol']} | "
                f"Bid: {data['bid']} | Ask: {data['ask']} | "
                f"Spread: {data['spread_points']} points | Volume: {data['volume']}"
            )
        time.sleep(interval)


if __name__ == "__main__":
    try:
        track_realtime_data(interval=1)
    except KeyboardInterrupt:
        print("\nStopped real-time tracking.")
    finally:
        MT5Connection().shutdown()
