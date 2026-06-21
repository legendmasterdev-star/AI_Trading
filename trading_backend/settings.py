import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY")
MARKET_TIMEFRAMES = ("M1", "M5", "M15", "H1")
STRATEGY_TIMEFRAMES = ("M5", "M15", "H1")

DEFAULT_MAX_SPREAD_POINTS = {
    "EURUSD": 12.0,
    "GBPUSD": 15.0,
    "USDJPY": 15.0,
}

DEFAULT_ALLOWED_ORIGINS = (
    "https://www.trademyfx.com",
    "https://trademyfx.com",
    "http://www.trademyfx.com",
    "http://trademyfx.com",
    "http://127.0.0.1:6400",
    "http://localhost:6400",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
)
DEFAULT_ALLOWED_HOSTS = (
    "www.trademyfx.com",
    "trademyfx.com",
    "127.0.0.1",
    "localhost",
)


@dataclass(frozen=True)
class Settings:
    mt5_login: int | None
    mt5_password: str | None
    mt5_server: str | None
    mt5_path: str | None
    symbols: tuple[str, ...] = SYMBOLS
    lot_size: float = 0.01
    magic_number: int = 20260604
    check_interval_seconds: int = 30
    max_spread_points: dict[str, float] = field(
        default_factory=lambda: DEFAULT_MAX_SPREAD_POINTS.copy()
    )
    auto_trade_enabled: bool = False
    risk_per_trade_pct: float = 1.0
    min_strategy_confidence: float = 0.68
    max_daily_loss_pct: float = 3.0
    max_account_drawdown_pct: float = 8.0
    max_open_positions: int = 3
    max_positions_per_symbol: int = 1
    max_currency_exposure_units: float = 2.0
    risk_kill_switch: bool = False
    news_lockout_active: bool = False
    trade_session_start_hour_utc: int = 0
    trade_session_end_hour_utc: int = 24
    rollover_blackout_minutes: int = 15
    public_base_url: str = "https://www.trademyfx.com"
    allowed_origins: tuple[str, ...] = DEFAULT_ALLOWED_ORIGINS
    allowed_hosts: tuple[str, ...] = DEFAULT_ALLOWED_HOSTS


def _optional_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _int_or_default(value: str | None, default: int) -> int:
    parsed = _optional_int(value)
    return default if parsed is None else parsed


def _optional_float(value: str | None, default: float) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _optional_bool(value: str | None, default: bool = False) -> bool:
    if value in (None, ""):
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv_tuple(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if not value:
        return default
    items = tuple(item.strip() for item in value.split(",") if item.strip())
    return items or default


def _bounded_int(value: str | None, default: int, minimum: int, maximum: int) -> int:
    parsed = _int_or_default(value, default)
    return max(minimum, min(maximum, parsed))


def load_settings() -> Settings:
    load_dotenv()

    return Settings(
        mt5_login=_optional_int(os.getenv("MT5_LOGIN")),
        mt5_password=os.getenv("MT5_PASSWORD"),
        mt5_server=os.getenv("MT5_SERVER"),
        mt5_path=os.getenv("MT5_PATH"),
        lot_size=_optional_float(os.getenv("LOT_SIZE"), 0.01),
        magic_number=_int_or_default(os.getenv("MAGIC_NUMBER"), 20260604),
        check_interval_seconds=_int_or_default(os.getenv("CHECK_INTERVAL_SECONDS"), 30),
        auto_trade_enabled=_optional_bool(os.getenv("AUTO_TRADE_ENABLED"), False),
        risk_per_trade_pct=_optional_float(os.getenv("RISK_PER_TRADE_PCT"), 1.0),
        min_strategy_confidence=_optional_float(
            os.getenv("MIN_STRATEGY_CONFIDENCE"),
            0.68,
        ),
        max_daily_loss_pct=_optional_float(os.getenv("MAX_DAILY_LOSS_PCT"), 3.0),
        max_account_drawdown_pct=_optional_float(
            os.getenv("MAX_ACCOUNT_DRAWDOWN_PCT"),
            8.0,
        ),
        max_open_positions=_int_or_default(os.getenv("MAX_OPEN_POSITIONS"), 3),
        max_positions_per_symbol=_int_or_default(
            os.getenv("MAX_POSITIONS_PER_SYMBOL"),
            1,
        ),
        max_currency_exposure_units=_optional_float(
            os.getenv("MAX_CURRENCY_EXPOSURE_UNITS"),
            2.0,
        ),
        risk_kill_switch=_optional_bool(os.getenv("RISK_KILL_SWITCH"), False),
        news_lockout_active=_optional_bool(os.getenv("NEWS_LOCKOUT_ACTIVE"), False),
        trade_session_start_hour_utc=_bounded_int(
            os.getenv("TRADE_SESSION_START_HOUR_UTC"),
            0,
            0,
            23,
        ),
        trade_session_end_hour_utc=_bounded_int(
            os.getenv("TRADE_SESSION_END_HOUR_UTC"),
            24,
            1,
            24,
        ),
        rollover_blackout_minutes=_bounded_int(
            os.getenv("ROLLOVER_BLACKOUT_MINUTES"),
            15,
            0,
            120,
        ),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "https://www.trademyfx.com"),
        allowed_origins=_csv_tuple(os.getenv("ALLOWED_ORIGINS"), DEFAULT_ALLOWED_ORIGINS),
        allowed_hosts=_csv_tuple(os.getenv("ALLOWED_HOSTS"), DEFAULT_ALLOWED_HOSTS),
    )


def check_environment(settings: Settings | None = None) -> dict:
    settings = settings or load_settings()
    required = {
        "MT5_LOGIN": settings.mt5_login,
        "MT5_PASSWORD": settings.mt5_password,
        "MT5_SERVER": settings.mt5_server,
        "MT5_PATH": settings.mt5_path,
    }
    missing = [key for key, value in required.items() if value in (None, "")]

    invalid = []
    if os.getenv("MT5_LOGIN") and settings.mt5_login is None:
        invalid.append("MT5_LOGIN must be an integer")
    if os.getenv("MAGIC_NUMBER") and _optional_int(os.getenv("MAGIC_NUMBER")) is None:
        invalid.append("MAGIC_NUMBER must be an integer")
    if (
        os.getenv("CHECK_INTERVAL_SECONDS")
        and _optional_int(os.getenv("CHECK_INTERVAL_SECONDS")) is None
    ):
        invalid.append("CHECK_INTERVAL_SECONDS must be an integer")
    integer_variables = {
        "MAX_OPEN_POSITIONS": os.getenv("MAX_OPEN_POSITIONS"),
        "MAX_POSITIONS_PER_SYMBOL": os.getenv("MAX_POSITIONS_PER_SYMBOL"),
        "TRADE_SESSION_START_HOUR_UTC": os.getenv("TRADE_SESSION_START_HOUR_UTC"),
        "TRADE_SESSION_END_HOUR_UTC": os.getenv("TRADE_SESSION_END_HOUR_UTC"),
        "ROLLOVER_BLACKOUT_MINUTES": os.getenv("ROLLOVER_BLACKOUT_MINUTES"),
    }
    for name, value in integer_variables.items():
        if value and _optional_int(value) is None:
            invalid.append(f"{name} must be an integer")

    terminal_path_exists = False
    if settings.mt5_path:
        terminal_path_exists = Path(settings.mt5_path).exists()

    try:
        import MetaTrader5  # noqa: F401

        mt5_installed = True
    except ImportError:
        mt5_installed = False

    return {
        "ok": not missing and not invalid and mt5_installed and terminal_path_exists,
        "missing": missing,
        "invalid": invalid,
        "mt5_installed": mt5_installed,
        "terminal_path_exists": terminal_path_exists,
        "symbols": list(settings.symbols),
        "auto_trade_enabled": settings.auto_trade_enabled,
        "variables": {
            "MT5_LOGIN": settings.mt5_login is not None,
            "MT5_PASSWORD": bool(settings.mt5_password),
            "MT5_SERVER": bool(settings.mt5_server),
            "MT5_PATH": bool(settings.mt5_path),
        },
    }
