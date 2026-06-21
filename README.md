# AI Trading Dashboard

Modular MT5 forex trading project for EURUSD, GBPUSD, and USDJPY.

## Structure

- `trading_backend/settings.py` - environment loading and checks.
- `trading_backend/mt5_client.py` - MT5 connection, symbol preparation, status.
- `trading_backend/market_data.py` - account, ticks, positions, orders, candles.
- `trading_backend/strategies.py` - EMA, RSI, MACD, ATR strategy signals.
- `trading_backend/execution.py` - buy, sell, close, cancel order execution.
- `trading_backend/ai_decision.py` - local decision layer for strategy and risk filters.
- `trading_backend/api.py` - FastAPI backend endpoints.
- `frontend/` - React/Vite trading dashboard source and production build.

## Strategy swapping

Strategies use a standard contract in `trading_backend/strategies.py`:

- input: `StrategyState` with the symbol, pair profile, and current candles by timeframe.
- output: `StrategyDecision` with `final_signal`, `confidence`, reasons, and per-timeframe details.

To change one pair without touching the rest of the system, create or update that
pair's strategy class (`EURUSDStrategy`, `GBPUSDStrategy`, or `USDJPYStrategy`) and
keep the `evaluate(StrategyState) -> StrategyDecision` interface. You can also
register a replacement at runtime:

```python
strategy_engine.register_strategy("EURUSD", MyEURUSDStrategy())
```

The current strategy engine uses weighted trend, momentum, volatility, and
multi-timeframe confirmation. Before a technical signal becomes executable, risk
guardrails check spread, confidence, account drawdown, daily realized P/L when MT5
history is available, floating loss, position limits, currency exposure, session
filters, rollover blackout, manual news lockout, and the kill switch.

## Run

```powershell
python -m pip install -r requirements.txt
cd frontend
npm install
npm run build
cd ..
python backend.py
```

Open `http://127.0.0.1:6400`.

For frontend-only development:

```powershell
cd frontend
npm run dev
```

## Production domain

The dashboard is prepared to run at:

```text
https://www.trademyfx.com
```

The React app uses relative API paths such as `/api/dashboard`, so the same FastAPI
server can serve both the frontend and backend through the domain.

### 1. Point DNS to the VPS

In the domain DNS panel, create these records:

```text
A     trademyfx.com       <VPS_PUBLIC_IP>
A     www.trademyfx.com   <VPS_PUBLIC_IP>
```

Replace `<VPS_PUBLIC_IP>` with the VPS IP you give to the client.

### 2. Build and run the app on the VPS

```powershell
python -m pip install -r requirements.txt
cd frontend
npm install
npm run build
cd ..
copy trading.env.example .env
python backend.py
```

For production behind Nginx, keep:

```text
HOST=127.0.0.1
PORT=6400
PUBLIC_BASE_URL=https://www.trademyfx.com
ALLOWED_HOSTS=www.trademyfx.com,trademyfx.com,127.0.0.1,localhost
```

### 3. Nginx reverse proxy

Use `deploy/nginx-trademyfx.conf` as the Nginx site config. It proxies:

```text
www.trademyfx.com -> 127.0.0.1:6400
```

After DNS resolves to the VPS, enable HTTPS:

```bash
sudo certbot --nginx -d trademyfx.com -d www.trademyfx.com
```

Then open:

```text
https://www.trademyfx.com
```

## Safety

The web order form uses dry-run mode by default. `auto_trader.py` also runs as a dry
run unless you set `AUTO_TRADE_ENABLED=true` in `.env`.
