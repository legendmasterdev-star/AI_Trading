from __future__ import annotations

from datetime import datetime
from typing import Any

from .settings import Settings, load_settings

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover - depends on local workstation setup.
    mt5 = None


def mt5_available() -> bool:
    return mt5 is not None


def require_mt5():
    if mt5 is None:
        raise RuntimeError("MetaTrader5 package is not installed.")
    return mt5


def as_dict(value: Any) -> dict:
    if value is None:
        return {}
    if hasattr(value, "_asdict"):
        return value._asdict()
    if isinstance(value, dict):
        return value
    return dict(value)


class MT5Connection:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or load_settings()
        self.connected = False

    def connect(self) -> dict:
        module = require_mt5()

        if self.settings.mt5_login is None:
            raise RuntimeError("MT5_LOGIN is missing or invalid.")
        if not self.settings.mt5_password:
            raise RuntimeError("MT5_PASSWORD is missing.")
        if not self.settings.mt5_server:
            raise RuntimeError("MT5_SERVER is missing.")

        params = {
            "login": self.settings.mt5_login,
            "password": self.settings.mt5_password,
            "server": self.settings.mt5_server,
        }
        if self.settings.mt5_path:
            params["path"] = self.settings.mt5_path

        ok = module.initialize(**params)
        if not ok:
            raise RuntimeError(f"MT5 initialize failed: {module.last_error()}")

        account = module.account_info()
        if account is None:
            raise RuntimeError(f"MT5 account_info failed: {module.last_error()}")

        self.connected = True
        return as_dict(account)

    def ensure_connected(self) -> None:
        if self.connected and self.account_info(optional=True):
            return
        self.connect()

    def shutdown(self) -> None:
        if mt5 is not None:
            mt5.shutdown()
        self.connected = False

    def status(self) -> dict:
        if mt5 is None:
            return {
                "connected": False,
                "mt5_installed": False,
                "last_error": "MetaTrader5 package is not installed.",
            }

        account = mt5.account_info()
        return {
            "connected": account is not None,
            "mt5_installed": True,
            "last_error": None if account is not None else str(mt5.last_error()),
            "account": as_dict(account) if account is not None else None,
        }

    def account_info(self, optional: bool = False) -> dict | None:
        module = require_mt5()
        account = module.account_info()
        if account is None:
            if optional:
                return None
            raise RuntimeError(f"account_info failed: {module.last_error()}")
        return as_dict(account)

    def prepare_symbol(self, symbol: str) -> Any:
        module = require_mt5()
        if not module.symbol_select(symbol, True):
            raise RuntimeError(f"symbol_select failed for {symbol}: {module.last_error()}")

        info = module.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"symbol_info failed for {symbol}")
        return info

    def prepare_symbols(self, symbols: tuple[str, ...] | list[str] | None = None) -> list[dict]:
        self.ensure_connected()
        prepared = []
        for symbol in symbols or self.settings.symbols:
            prepared.append(as_dict(self.prepare_symbol(symbol)))
        return prepared

    def timeframe(self, name: str):
        module = require_mt5()
        attr = f"TIMEFRAME_{name.upper()}"
        if not hasattr(module, attr):
            raise ValueError(f"Unsupported timeframe: {name}")
        return getattr(module, attr)

    def symbol_info(self, symbol: str) -> Any:
        self.prepare_symbol(symbol)
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"symbol_info failed for {symbol}")
        return info

    def tick(self, symbol: str) -> Any:
        self.prepare_symbol(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"symbol_info_tick failed for {symbol}: {mt5.last_error()}")
        return tick

    def copy_rates(self, symbol: str, timeframe_name: str, count: int = 300):
        self.prepare_symbol(symbol)
        rates = mt5.copy_rates_from_pos(symbol, self.timeframe(timeframe_name), 0, count)
        return rates

    def positions(self, symbol: str | None = None, ticket: int | None = None) -> list:
        self.ensure_connected()
        if ticket is not None:
            positions = mt5.positions_get(ticket=ticket)
        elif symbol:
            positions = mt5.positions_get(symbol=symbol)
        else:
            positions = mt5.positions_get()
        return list(positions or [])

    def pending_orders(self, symbol: str | None = None) -> list:
        self.ensure_connected()
        orders = mt5.orders_get(symbol=symbol) if symbol else mt5.orders_get()
        return list(orders or [])

    def history_deals(self, date_from: datetime, date_to: datetime) -> list:
        self.ensure_connected()
        deals = mt5.history_deals_get(date_from, date_to)
        return list(deals or [])

    def order_send(self, request: dict):
        self.ensure_connected()
        result = mt5.order_send(request)
        if result is None:
            raise RuntimeError(f"order_send returned None: {mt5.last_error()}")
        return result

    @property
    def module(self):
        return require_mt5()
