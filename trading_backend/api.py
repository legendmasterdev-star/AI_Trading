from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .ai_decision import AIDecisionEngine
from .auth import AuthError, AuthService
from .execution import OrderExecutor
from .market_data import MarketDataService
from .mt5_client import MT5Connection
from .settings import SYMBOLS, check_environment, load_settings
from .strategies import StrategyEngine


settings = load_settings()
connection = MT5Connection(settings)
market_data = MarketDataService(connection)
strategy_engine = StrategyEngine(market_data)
ai_engine = AIDecisionEngine(strategy_engine, market_data)
executor = OrderExecutor(connection, market_data)
auth_service = AuthService()

app = FastAPI(title="AI Trading Dashboard", version="1.0.0")
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=list(settings.allowed_hosts),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class MarketOrderRequest(BaseModel):
    symbol: str = Field(..., examples=["EURUSD"])
    side: str = Field(..., examples=["BUY"])
    volume: float = 0.01
    sl_points: int | None = None
    tp_points: int | None = None
    dry_run: bool = True


class StrategyOrderRequest(BaseModel):
    symbol: str = Field(..., examples=["EURUSD"])
    side: str = Field(..., examples=["BUY"])
    volume: float | None = None
    dry_run: bool = True


class ClosePositionRequest(BaseModel):
    ticket: int
    dry_run: bool = True


class RegisterRequest(BaseModel):
    email: str = Field(..., examples=["trader@example.com"])
    password: str = Field(..., min_length=6)
    name: str | None = None
    plan: str | None = None


class LoginRequest(BaseModel):
    email: str = Field(..., examples=["trader@example.com"])
    password: str


def api_error(error: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(error))


def require_user(authorization: str | None = Header(default=None)) -> dict:
    """FastAPI dependency: validate the bearer token and return the user."""
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    try:
        return auth_service.verify_token(token)
    except AuthError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error))


@app.post("/api/auth/register")
def register(request: RegisterRequest):
    try:
        return auth_service.register(
            email=request.email,
            password=request.password,
            name=request.name,
            plan=request.plan,
        )
    except AuthError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error))


@app.post("/api/auth/login")
def login(request: LoginRequest):
    try:
        return auth_service.login(email=request.email, password=request.password)
    except AuthError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error))


@app.get("/api/auth/me")
def me(user: dict = Depends(require_user)):
    return {"user": user}


@app.post("/api/auth/logout")
def logout(user: dict = Depends(require_user)):
    # Tokens are stateless and signed, so logout is handled client-side by
    # discarding the token. This endpoint just confirms the caller is valid.
    return {"ok": True}


@app.get("/api/environment")
def environment_check(user: dict = Depends(require_user)):
    return {
        "environment": check_environment(settings),
        "connection": connection.status(),
    }


@app.post("/api/connect")
def connect(user: dict = Depends(require_user)):
    try:
        account = connection.connect()
        prepared = connection.prepare_symbols(settings.symbols)
        return {
            "connected": True,
            "account": account,
            "prepared_symbols": prepared,
        }
    except Exception as error:
        raise api_error(error)


@app.post("/api/shutdown")
def shutdown(user: dict = Depends(require_user)):
    connection.shutdown()
    return {"connected": False}


@app.get("/api/status")
def status(user: dict = Depends(require_user)):
    return connection.status()


@app.get("/api/dashboard")
def dashboard(user: dict = Depends(require_user)):
    try:
        connection.ensure_connected()
        return {
            **market_data.dashboard_snapshot(settings.symbols),
            "strategy": strategy_engine.snapshot(settings.symbols),
            "ai": ai_engine.decide_all(settings.symbols),
        }
    except Exception as error:
        raise api_error(error)


@app.get("/api/history")
def trade_history(days: int = 30, user: dict = Depends(require_user)):
    try:
        connection.ensure_connected()
        return market_data.trade_history(days=days)
    except Exception as error:
        raise api_error(error)


@app.get("/api/symbols/{symbol}/report")
def symbol_report(symbol: str, user: dict = Depends(require_user)):
    try:
        connection.ensure_connected()
        symbol = symbol.upper()
        return {
            "report": market_data.symbol_report(symbol),
            "strategy": strategy_engine.analyze_symbol(symbol),
            "ai": ai_engine.decide_symbol(symbol),
        }
    except Exception as error:
        raise api_error(error)


@app.get("/api/strategies")
def strategies(user: dict = Depends(require_user)):
    try:
        connection.ensure_connected()
        return strategy_engine.snapshot(settings.symbols)
    except Exception as error:
        raise api_error(error)


@app.get("/api/ai-decisions")
def ai_decisions(user: dict = Depends(require_user)):
    try:
        connection.ensure_connected()
        return ai_engine.decide_all(settings.symbols)
    except Exception as error:
        raise api_error(error)


@app.post("/api/orders/market")
def market_order(request: MarketOrderRequest, user: dict = Depends(require_user)):
    try:
        connection.ensure_connected()
        return executor.market_order(
            symbol=request.symbol.upper(),
            side=request.side,
            volume=request.volume,
            sl_points=request.sl_points,
            tp_points=request.tp_points,
            dry_run=request.dry_run,
        )
    except Exception as error:
        raise api_error(error)


@app.post("/api/orders/strategy")
def strategy_order(request: StrategyOrderRequest, user: dict = Depends(require_user)):
    try:
        connection.ensure_connected()
        return executor.strategy_order(
            symbol=request.symbol.upper(),
            side=request.side,
            volume=request.volume,
            dry_run=request.dry_run,
        )
    except Exception as error:
        raise api_error(error)


@app.post("/api/orders/close")
def close_position(request: ClosePositionRequest, user: dict = Depends(require_user)):
    try:
        connection.ensure_connected()
        return executor.close_position(ticket=request.ticket, dry_run=request.dry_run)
    except Exception as error:
        raise api_error(error)


FRONTEND_ROOT = Path(__file__).resolve().parent.parent / "frontend"
FRONTEND_DIST = FRONTEND_ROOT / "dist"
FRONTEND_DIR = FRONTEND_DIST if FRONTEND_DIST.exists() else FRONTEND_ROOT


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


if (FRONTEND_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")
