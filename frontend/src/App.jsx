import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BarChart3,
  BriefcaseBusiness,
  CheckCircle2,
  CircleDollarSign,
  CreditCard,
  Gauge,
  History,
  Home,
  LockKeyhole,
  LogIn,
  LogOut,
  Power,
  RefreshCw,
  Send,
  ShieldCheck,
  TrendingUp,
  UserRound,
  Wallet,
} from "lucide-react";

const SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY"];
const MARKET_TICK_FRESH_MS = 5 * 60 * 1000;
const BASE_PRICES = {
  EURUSD: 1.08742,
  GBPUSD: 1.27411,
  USDJPY: 156.223,
};
const PLANS = [
  {
    name: "Starter",
    price: "$19",
    description: "Real-time account visibility with live charts and safe dry-run order practice.",
    features: ["Live quotes & candle charts", "Dry-run order practice", "Account & risk overview"],
  },
  {
    name: "Pro",
    price: "$49",
    description: "The full decision stack: multi-timeframe signals, real-time risk control, and live MT5 execution.",
    features: ["Multi-timeframe strategy signals", "Real-time risk guardrails", "Live MT5 execution console"],
  },
  {
    name: "Desk",
    price: "$129",
    description: "Desk-grade operations with complete trade-history reporting and priority support.",
    features: ["Operator workflow & controls", "Complete MT5 trade history", "Priority support workspace"],
  },
];

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "-";
  }
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatPrice(symbol, value) {
  return formatNumber(value, symbol === "USDJPY" ? 3 : 5);
}

function formatTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const HISTORY_ALL_DAYS = 3650;
const HISTORY_RANGES = [
  { label: "7D", days: 7 },
  { label: "30D", days: 30 },
  { label: "90D", days: 90 },
  { label: "1Y", days: 365 },
  { label: "All", days: HISTORY_ALL_DAYS },
];

function historyRangeLabel(days) {
  const match = HISTORY_RANGES.find((range) => range.days === days);
  if (match?.label === "All") return "all time";
  if (match) return `last ${match.label}`;
  return `last ${days} days`;
}

function summarizeTrades(trades = [], days = 30) {
  const closed = trades.filter((trade) => trade.closed !== false);
  let realized = 0;
  let wins = 0;
  let losses = 0;
  let grossProfit = 0;
  let grossLoss = 0;
  let best = null;
  let worst = null;
  let cumulative = 0;
  const bySymbol = new Map();
  const equity = [];

  closed
    .slice()
    .sort((a, b) => new Date(a.close_time || a.open_time || 0) - new Date(b.close_time || b.open_time || 0))
    .forEach((trade) => {
      const profit = Number(trade.net_profit || 0);
      realized += profit;
      if (profit > 0) {
        wins += 1;
        grossProfit += profit;
      } else if (profit < 0) {
        losses += 1;
        grossLoss += Math.abs(profit);
      }
      best = best === null ? profit : Math.max(best, profit);
      worst = worst === null ? profit : Math.min(worst, profit);

      const symbol = trade.symbol || "-";
      const bucket = bySymbol.get(symbol) || { symbol, net_profit: 0, trades: 0, wins: 0, losses: 0 };
      bucket.net_profit += profit;
      bucket.trades += 1;
      if (profit > 0) bucket.wins += 1;
      else if (profit < 0) bucket.losses += 1;
      bySymbol.set(symbol, bucket);

      cumulative += profit;
      equity.push({ time: trade.close_time || trade.open_time, profit, cumulative });
    });

  return {
    range: { days },
    summary: {
      realized_profit: realized,
      trade_count: closed.length,
      wins,
      losses,
      win_rate: closed.length ? wins / closed.length : null,
      gross_profit: grossProfit,
      gross_loss: grossLoss,
      profit_factor: grossLoss > 0 ? grossProfit / grossLoss : null,
      best_trade: best,
      worst_trade: worst,
      unavailable: false,
    },
    trades: closed,
    by_symbol: [...bySymbol.values()].sort((a, b) => Math.abs(b.net_profit) - Math.abs(a.net_profit)),
    equity_curve: equity,
  };
}

function tradeSide(deal) {
  if (deal?.side) return deal.side;
  const type = Number(deal?.type);
  if (type === 0) return "BUY";
  if (type === 1) return "SELL";
  return deal?.entry ? String(deal.entry).toUpperCase() : "-";
}

function dealProfit(deal) {
  const value =
    deal?.net_profit ??
    Number(deal?.profit || 0) +
      Number(deal?.commission || 0) +
      Number(deal?.swap || 0) +
      Number(deal?.fee || 0);
  return Number(value || 0);
}

function buildTodayTrades(deals = []) {
  const groups = new Map();
  deals.forEach((deal, index) => {
    const key = deal?.position_id || deal?.position || deal?.order || deal?.ticket || `deal-${index}`;
    const timeValue = deal.time_iso || (deal.time ? new Date(Number(deal.time) * 1000).toISOString() : null);
    const current = groups.get(key) || {
      id: key,
      ticket: deal.ticket || deal.order || key,
      symbol: deal.symbol || "-",
      side: tradeSide(deal),
      volume: 0,
      entry_price: null,
      exit_price: null,
      net_profit: 0,
      start_time: timeValue,
      end_time: timeValue,
      comment: deal.comment || "",
      deals: [],
    };

    current.symbol = current.symbol === "-" ? deal.symbol || "-" : current.symbol;
    current.side = current.side === "-" ? tradeSide(deal) : current.side;
    current.volume = Math.max(current.volume, Number(deal.volume || 0));
    current.entry_price = current.entry_price ?? deal.price ?? null;
    current.exit_price = deal.price ?? current.exit_price;
    current.net_profit += dealProfit(deal);
    current.comment = current.comment || deal.comment || "";
    current.deals.push(deal);

    if (timeValue) {
      if (!current.start_time || new Date(timeValue) < new Date(current.start_time)) {
        current.start_time = timeValue;
      }
      if (!current.end_time || new Date(timeValue) > new Date(current.end_time)) {
        current.end_time = timeValue;
      }
    }
    groups.set(key, current);
  });

  return [...groups.values()].sort((a, b) => new Date(a.end_time || 0) - new Date(b.end_time || 0));
}

function cssToken(value) {
  return String(value || "").toLowerCase().replaceAll("_", "-");
}

function storedSession() {
  try {
    const session = JSON.parse(localStorage.getItem("tradingSession") || "null");
    if (session?.accessGranted && session?.token) return session;
  } catch {
    // Ignore malformed localStorage from previous frontend versions.
  }
  localStorage.removeItem("tradingSession");
  return null;
}

function storedToken() {
  try {
    return JSON.parse(localStorage.getItem("tradingSession") || "null")?.token || null;
  } catch {
    return null;
  }
}

function mt5MarketStatus(payload) {
  if (payload?.market_status) {
    return {
      label: payload.market_status.label || (payload.market_status.is_open ? "Market open" : "Market closed"),
      isOpen: Boolean(payload.market_status.is_open),
      reason: payload.market_status.reason,
    };
  }

  const newestTickMs = Math.max(
    0,
    ...(payload?.symbols || []).map((report) => {
      const tick = report?.tick || {};
      if (tick.time_epoch) return Number(tick.time_epoch) * 1000;
      if (tick.time_iso) return new Date(tick.time_iso).getTime();
      if (tick.time) return new Date(tick.time).getTime();
      return 0;
    }),
  );
  const hasFreshTick =
    Number.isFinite(newestTickMs) && newestTickMs > 0 && Date.now() - newestTickMs <= MARKET_TICK_FRESH_MS;
  const now = new Date();
  const day = now.getUTCDay();
  const hour = now.getUTCHours();
  const sessionOpen = !(
    day === 6 ||
    (day === 0 && hour < 22) ||
    (day === 5 && hour >= 22)
  );

  return sessionOpen && hasFreshTick
    ? { label: "Market open", isOpen: true }
    : { label: "Market closed", isOpen: false };
}

async function api(path, options = {}) {
  const token = storedToken();
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const error = new Error(payload.detail || response.statusText);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

function authRequest(mode, body) {
  const endpoint = mode === "register" ? "register" : "login";
  return api(`/api/auth/${endpoint}`, { method: "POST", body: JSON.stringify(body) });
}

function deterministicCandles(symbol, index) {
  const price = BASE_PRICES[symbol];
  const scale = symbol === "USDJPY" ? 0.08 : 0.0008;
  return Array.from({ length: 96 }, (_, i) => {
    const drift = (i - 48) * scale * 0.018 * (index === 2 ? 1 : -1);
    const wave = Math.sin(i / 8 + index) * scale * 1.4;
    const close = price + drift + wave;
    return {
      time: `2026-06-05T${String(Math.floor(i / 4)).padStart(2, "0")}:${String((i % 4) * 15).padStart(2, "0")}:00Z`,
      open: close - scale * 0.12,
      high: close + scale * 0.45,
      low: close - scale * 0.45,
      close,
    };
  });
}

function demoDashboard() {
  const today = new Date();
  const isoAt = (hour, minute) => {
    const value = new Date(today);
    value.setHours(hour, minute, 0, 0);
    return value.toISOString();
  };

  return {
    account: {
      balance: 10000,
      equity: 10042.35,
      margin_free: 9700.2,
      profit: 42.35,
      currency: "USD",
      leverage: 100,
    },
    positions: [],
    pending_orders: [],
    today_history: {
      date: today.toISOString().slice(0, 10),
      realized_profit: 42.35,
      trade_count: 5,
      wins: 3,
      losses: 2,
      deals: [
        historyDemo("EURUSD", "BUY", 0.03, 1.08742, 18.4, isoAt(8, 12), 100241),
        historyDemo("GBPUSD", "SELL", 0.02, 1.27411, -7.2, isoAt(9, 4), 100242),
        historyDemo("USDJPY", "BUY", 0.01, 156.223, 12.6, isoAt(10, 31), 100243),
        historyDemo("EURUSD", "SELL", 0.02, 1.08814, -5.8, isoAt(11, 22), 100244),
        historyDemo("GBPUSD", "BUY", 0.03, 1.27501, 24.35, isoAt(12, 16), 100245),
      ],
    },
    symbols: SYMBOLS.map((symbol, index) => {
      const candles = deterministicCandles(symbol, index);
      const last = candles.at(-1).close;
      return {
        symbol,
        tick: {
          bid: last,
          ask: last + (symbol === "USDJPY" ? 0.018 : 0.00018),
          spread_points: symbol === "EURUSD" ? 9.4 : 12.6,
        },
        timeframes: { M5: { candles } },
      };
    }),
    strategy: {
      symbols: [
        strategyDemo("EURUSD", "BUY", 0.82, 0.74, true),
        strategyDemo("GBPUSD", "SELL", 0.76, -0.68, true),
        strategyDemo("USDJPY", "HOLD", 0.44, 0.12, false),
      ],
    },
    ai: {
      decisions: [
        {
          symbol: "EURUSD",
          action: "BUY",
          risk_level: "LOW",
          reasons: ["BUY signal confirmed with no open position"],
        },
        {
          symbol: "GBPUSD",
          action: "SELL",
          risk_level: "LOW",
          reasons: ["SELL signal confirmed with no open position"],
        },
        {
          symbol: "USDJPY",
          action: "HOLD",
          risk_level: "LOW",
          reasons: ["Strategy agreement is not strong enough"],
        },
      ],
    },
  };
}

function historyDemo(symbol, side, volume, price, profit, time, ticket) {
  return {
    ticket,
    order: ticket + 9000,
    position_id: ticket + 3000,
    symbol,
    side,
    volume,
    price,
    profit,
    commission: 0,
    swap: 0,
    fee: 0,
    net_profit: profit,
    time_iso: time,
    comment: "Demo history",
  };
}

function strategyDemo(symbol, finalSignal, confidence, score, allowed) {
  return {
    symbol,
    final_signal: finalSignal,
    confidence,
    reasons: [`Weighted score ${score}`, `H1 confirmation: ${finalSignal}`],
    metadata: {
      raw_signal: finalSignal,
      risk: {
        allow_trade: allowed,
        risk_level: allowed ? "LOW" : "LOW",
        blockers: [],
        warnings: [],
        checks: {},
      },
      aggregate: { average_score: score },
    },
  };
}

function demoHistory(days = 30) {
  const symbols = ["EURUSD", "GBPUSD", "USDJPY"];
  const now = Date.now();
  const count = Math.min(46, Math.max(14, Math.round(days * 0.8)));
  const trades = [];

  for (let i = 0; i < count; i += 1) {
    const symbol = symbols[i % symbols.length];
    const side = i % 2 === 0 ? "BUY" : "SELL";
    const swing = Math.sin(i * 1.7) * 27 + Math.cos(i / 2.4) * 15;
    const profit = Math.round((swing + (i % 5 === 0 ? -24 : 9)) * 100) / 100;
    const closeMs = now - (count - i) * ((days / count) * 86400000);
    const openMs = closeMs - (35 + (i % 7) * 18) * 60000;
    const base = BASE_PRICES[symbol];
    const openPrice = base + Math.sin(i) * (symbol === "USDJPY" ? 0.4 : 0.004);

    trades.push({
      ticket: 500120 + i,
      position_id: 300120 + i,
      symbol,
      side,
      volume: Number((0.01 + (i % 3) * 0.01).toFixed(2)),
      open_time: new Date(openMs).toISOString(),
      close_time: new Date(closeMs).toISOString(),
      open_price: openPrice,
      close_price: openPrice + (side === "BUY" ? 1 : -1) * (profit / 1000),
      net_profit: profit,
      commission: 0,
      swap: 0,
      fee: 0,
      comment: i % 2 === 0 ? "auto_buy" : "manual",
      closed: true,
    });
  }

  return summarizeTrades(trades, days);
}

function Sparkline({ candles = [], symbol }) {
  const ref = useRef(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);

    const bg = ctx.createLinearGradient(0, 0, 0, height);
    bg.addColorStop(0, "#0b1322");
    bg.addColorStop(1, "#070c16");
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, width, height);
    ctx.strokeStyle = "rgba(148, 170, 205, 0.08)";
    ctx.lineWidth = 1;
    for (let i = 1; i < 5; i += 1) {
      const y = (height / 5) * i;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
    }

    const closes = candles.map((candle) => Number(candle.close)).filter(Number.isFinite);
    if (closes.length < 2) {
      ctx.fillStyle = "#7e8da6";
      ctx.font = "700 14px Inter, system-ui";
      ctx.fillText("No candle data", 16, 28);
      return;
    }

    const min = Math.min(...closes);
    const max = Math.max(...closes);
    const range = max - min || 1;
    const rising = closes.at(-1) >= closes[0];
    const stroke = rising ? "#2ee6a6" : "#fb5e72";
    const fill0 = rising ? "rgba(46, 230, 166, 0.28)" : "rgba(251, 94, 114, 0.26)";
    const xStep = width / Math.max(closes.length - 1, 1);
    const points = closes.map((value, index) => ({
      x: index * xStep,
      y: height - ((value - min) / range) * (height - 40) - 20,
      value,
    }));

    const area = ctx.createLinearGradient(0, 20, 0, height);
    area.addColorStop(0, fill0);
    area.addColorStop(1, "rgba(0, 0, 0, 0)");
    ctx.fillStyle = area;
    ctx.beginPath();
    points.forEach((point, index) => {
      if (index === 0) ctx.moveTo(point.x, point.y);
      else ctx.lineTo(point.x, point.y);
    });
    ctx.lineTo(width, height);
    ctx.lineTo(0, height);
    ctx.closePath();
    ctx.fill();

    ctx.strokeStyle = stroke;
    ctx.lineWidth = 2.5;
    ctx.shadowColor = stroke;
    ctx.shadowBlur = 12;
    ctx.beginPath();
    points.forEach((point, index) => {
      if (index === 0) ctx.moveTo(point.x, point.y);
      else ctx.lineTo(point.x, point.y);
    });
    ctx.stroke();
    ctx.shadowBlur = 0;

    const last = points.at(-1);
    ctx.fillStyle = stroke;
    ctx.beginPath();
    ctx.arc(last.x, last.y, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "rgba(255, 255, 255, 0.9)";
    ctx.beginPath();
    ctx.arc(last.x, last.y, 2, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = "#eaf1fb";
    ctx.font = "800 14px Inter, system-ui";
    ctx.fillText(`${symbol} ${formatPrice(symbol, last.value)}`, 14, 24);
  }, [candles, symbol]);

  return <canvas ref={ref} className="sparkline" width="540" height="260" />;
}

function LandingChart() {
  const ref = useRef(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);

    const background = ctx.createLinearGradient(0, 0, width, height);
    background.addColorStop(0, "#060b15");
    background.addColorStop(0.5, "#0a1424");
    background.addColorStop(1, "#0c1a2c");
    ctx.fillStyle = background;
    ctx.fillRect(0, 0, width, height);

    ctx.strokeStyle = "rgba(56, 189, 248, 0.06)";
    ctx.lineWidth = 1;
    for (let x = 0; x <= width; x += 64) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, height);
      ctx.stroke();
    }
    for (let y = 0; y <= height; y += 52) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
    }

    const series = Array.from({ length: 84 }, (_, index) => {
      const trend = index * 2.2;
      const wave = Math.sin(index / 5) * 26 + Math.cos(index / 11) * 18;
      return 430 - trend - wave;
    });
    const xStep = width / (series.length - 1);
    const points = series.map((value, index) => ({
      x: index * xStep,
      y: Math.max(82, Math.min(height - 82, value)),
    }));

    const area = ctx.createLinearGradient(0, 110, 0, height);
    area.addColorStop(0, "rgba(34, 211, 238, 0.34)");
    area.addColorStop(1, "rgba(34, 211, 238, 0.01)");
    ctx.fillStyle = area;
    ctx.beginPath();
    points.forEach((point, index) => {
      if (index === 0) ctx.moveTo(point.x, point.y);
      else ctx.lineTo(point.x, point.y);
    });
    ctx.lineTo(width, height);
    ctx.lineTo(0, height);
    ctx.closePath();
    ctx.fill();

    ctx.strokeStyle = "#2ee6a6";
    ctx.lineWidth = 4;
    ctx.shadowColor = "rgba(46, 230, 166, 0.7)";
    ctx.shadowBlur = 18;
    ctx.beginPath();
    points.forEach((point, index) => {
      if (index === 0) ctx.moveTo(point.x, point.y);
      else ctx.lineTo(point.x, point.y);
    });
    ctx.stroke();
    ctx.shadowBlur = 0;

    const markers = [
      { x: width * 0.64, y: height * 0.31, label: "BUY", color: "#10b981" },
      { x: width * 0.78, y: height * 0.43, label: "RISK OK", color: "#3b82f6" },
      { x: width * 0.47, y: height * 0.52, label: "SPREAD", color: "#f7b955" },
    ];
    markers.forEach((marker) => {
      ctx.fillStyle = marker.color;
      ctx.beginPath();
      ctx.roundRect(marker.x, marker.y, 104, 34, 8);
      ctx.fill();
      ctx.fillStyle = "#ffffff";
      ctx.font = "900 13px Inter, system-ui";
      ctx.fillText(marker.label, marker.x + 14, marker.y + 22);
    });
  }, []);

  return <canvas ref={ref} className="landing-chart" width="1440" height="640" aria-hidden="true" />;
}

function LandingPage({ session, selectedPlan, setSelectedPlan, onSession, onEnterDashboard, onLogout }) {
  const [mode, setMode] = useState("login");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const signedIn = Boolean(session);

  function choosePlan(plan) {
    localStorage.setItem("selectedPlan", plan);
    setSelectedPlan(plan);
    document.getElementById("access")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function switchMode(nextMode) {
    setMode(nextMode);
    setError("");
  }

  async function submit(event) {
    event.preventDefault();
    setError("");
    const data = new FormData(event.currentTarget);
    const body = {
      email: (data.get("email") || "").trim(),
      password: data.get("password") || "",
    };
    if (mode === "register") {
      body.name = (data.get("name") || "").trim() || undefined;
      body.plan = selectedPlan;
    }

    setBusy(true);
    try {
      const result = await authRequest(mode, body);
      const nextSession = {
        token: result.token,
        email: result.user?.email || body.email,
        name: result.user?.name || result.user?.email || body.email,
        plan: result.user?.plan || selectedPlan,
        accessGranted: true,
      };
      localStorage.setItem("tradingSession", JSON.stringify(nextSession));
      onSession(nextSession);
      window.location.hash = "#dashboard";
    } catch (err) {
      setError(err.message || "Authentication failed. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="landing-page">
      <header className="landing-nav">
        <a className="brand landing-brand" href="#top" aria-label="AI Trading home">
          <span className="brand-mark">FX</span>
          <span>
            <strong>AI Trading</strong>
            <small>MT5 workstation</small>
          </span>
        </a>
        <nav>
          <a href="#plans">Plans</a>
          {signedIn ? (
            <>
              <a
                href="#dashboard"
                onClick={(event) => {
                  event.preventDefault();
                  onEnterDashboard?.();
                }}
              >
                Dashboard
              </a>
              <a
                href="#top"
                onClick={(event) => {
                  event.preventDefault();
                  onLogout?.();
                }}
              >
                Log out
              </a>
            </>
          ) : (
            <>
              <a href="#access">Login</a>
              <a href="#access">Register</a>
            </>
          )}
        </nav>
      </header>

      <main id="top">
        <section className="landing-hero">
          <LandingChart />
          <div className="landing-hero-content">
            <p className="eyebrow">MetaTrader 5 Trading Platform</p>
            <h1>Disciplined forex automation, under your command.</h1>
            <p>
              Connect your MT5 account to one workspace that scores multi-timeframe strategy
              signals, enforces your risk limits in real time, and executes only the trades that
              clear every guardrail.
            </p>
            <div className="landing-actions">
              {signedIn ? (
                <button className="primary-button" onClick={() => onEnterDashboard?.()}>
                  Open dashboard
                  <ArrowRight size={16} />
                </button>
              ) : (
                <a className="primary-button" href="#access">
                  Get started
                  <ArrowRight size={16} />
                </a>
              )}
              <a className="secondary-button" href="#plans">
                {signedIn ? <BarChart3 size={16} /> : <LockKeyhole size={16} />}
                View plans
              </a>
            </div>
          </div>
          <div className="landing-ticker" aria-label="Market snapshot">
            {SYMBOLS.map((symbol, index) => (
              <div key={symbol}>
                <span>{symbol}</span>
                <strong>{formatPrice(symbol, deterministicCandles(symbol, index).at(-1).close)}</strong>
              </div>
            ))}
          </div>
        </section>

        <section className="landing-band">
          <div className="landing-section-header">
            <p className="eyebrow">The Trading Stack</p>
            <h2>Signals, risk, and execution — unified in one workspace.</h2>
          </div>
          <div className="feature-grid">
            {[
              [
                TrendingUp,
                "Multi-timeframe conviction",
                "Weighted EMA, RSI, and MACD agreement across M5 to H1 turns market noise into a clear, scored signal for every pair.",
              ],
              [
                ShieldCheck,
                "Risk enforced before entry",
                "Spread, drawdown, exposure, session, and news guardrails are checked on every signal — nothing reaches the market without clearing your limits.",
              ],
              [
                BarChart3,
                "Live account intelligence",
                "Balance, equity, open positions, and complete MT5 trade history — including trades placed manually — updated in real time.",
              ],
            ].map(([Icon, title, copy]) => (
              <article className="feature-card" key={title}>
                <div className="metric-icon">
                  <Icon size={18} />
                </div>
                <h3>{title}</h3>
                <p>{copy}</p>
              </article>
            ))}
          </div>
        </section>

        <section id="plans" className="landing-band">
          <div className="landing-section-header">
            <p className="eyebrow">Subscription</p>
            <h2>Choose your operating level.</h2>
          </div>
          <div className="landing-plans">
            {PLANS.map((plan) => (
              <article
                key={plan.name}
                className={`plan-card landing-plan ${selectedPlan === plan.name ? "featured" : ""}`}
              >
                <h3>{plan.name}</h3>
                <p className="price">
                  {plan.price}
                  <span>/mo</span>
                </p>
                <p>{plan.description}</p>
                <ul className="plan-feature-list">
                  {plan.features.map((feature) => (
                    <li key={feature}>
                      <CheckCircle2 size={15} />
                      {feature}
                    </li>
                  ))}
                </ul>
                <button
                  className={selectedPlan === plan.name ? "primary-button wide" : "secondary-button wide"}
                  onClick={() => choosePlan(plan.name)}
                >
                  {selectedPlan === plan.name ? "Selected" : "Select"}
                </button>
              </article>
            ))}
          </div>
        </section>

        <section id="access" className="landing-band access-band">
          <div className="landing-section-header">
            <p className="eyebrow">Secure Access</p>
            <h2>{signedIn ? "Welcome back." : "Step into your trading workspace."}</h2>
          </div>
          <div className="access-layout">
            {signedIn ? (
              <div className="auth-panel landing-auth signed-in-panel">
                <span className="status-chip online">Signed in</span>
                <h3>{session.name || session.email}</h3>
                <p>
                  Your command center is ready — strategy signals, live risk, and execution in one
                  place.
                </p>
                <button className="primary-button wide" onClick={() => onEnterDashboard?.()}>
                  Open dashboard
                  <ArrowRight size={16} />
                </button>
                <button className="logout-button" onClick={() => onLogout?.()}>
                  <LogOut size={15} />
                  Log out
                </button>
              </div>
            ) : (
            <form className="auth-panel landing-auth" onSubmit={submit}>
              <div className="tabs">
                <button
                  type="button"
                  className={mode === "login" ? "active" : ""}
                  onClick={() => switchMode("login")}
                >
                  <LogIn size={15} />
                  Login
                </button>
                <button
                  type="button"
                  className={mode === "register" ? "active" : ""}
                  onClick={() => switchMode("register")}
                >
                  <UserRound size={15} />
                  Register
                </button>
              </div>
              {mode === "register" && (
                <label>
                  Name
                  <input name="name" type="text" autoComplete="name" required />
                </label>
              )}
              <label>
                Email
                <input name="email" type="email" autoComplete="email" required />
              </label>
              <label>
                Password
                <input
                  name="password"
                  type="password"
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  minLength={6}
                  required
                />
              </label>
              {error && <p className="auth-error">{error}</p>}
              <button className="primary-button wide" type="submit" disabled={busy}>
                {busy
                  ? "Please wait…"
                  : mode === "login"
                    ? "Login to dashboard"
                    : "Create account"}
                <ArrowRight size={16} />
              </button>
            </form>
            )}
            <aside className="access-summary">
              <span className="status-chip online">{selectedPlan} plan</span>
              <h3>Built for confident execution</h3>
              <p>
                Every signal is scored across timeframes and cleared against your risk limits before
                it can reach the market — so you stay in control of the desk.
              </p>
              <div className="access-stats">
                <div>
                  <strong>3</strong>
                  <span>Major pairs</span>
                </div>
                <div>
                  <strong>10s</strong>
                  <span>Live refresh</span>
                </div>
              </div>
            </aside>
          </div>
        </section>
      </main>
    </div>
  );
}

function MetricCard({ icon: Icon, label, value, tone = "" }) {
  return (
    <article className={`metric-card ${tone}`}>
      <div className="metric-icon">
        <Icon size={18} />
      </div>
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function MarketCard({ report, strategy, decision }) {
  const symbol = report.symbol;
  const signal = strategy?.final_signal || "HOLD";
  const rawSignal = strategy?.metadata?.raw_signal || signal;
  const risk = strategy?.metadata?.risk || {};
  const aggregate = strategy?.metadata?.aggregate || {};
  const confidence = Number(strategy?.confidence || 0);
  const confidencePct = Math.max(0, Math.min(100, confidence * 100));
  const riskLevel = cssToken(risk.risk_level || decision?.risk_level || "LOW");
  const riskGate = risk.allow_trade ? "allowed" : rawSignal === "HOLD" ? "waiting" : "blocked";
  const notes = [
    ...(risk.blockers || []),
    ...(risk.warnings || []),
    ...(strategy?.reasons || []),
    ...(decision?.reasons || []),
  ].slice(0, 3);
  const candles = report.timeframes?.M5?.candles || [];

  return (
    <article className="market-card">
      <header className="market-card-header">
        <div>
          <h3>{symbol}</h3>
          <p>
            {decision?.action || "HOLD"} | raw {rawSignal}
          </p>
        </div>
        <span className={`signal-pill ${cssToken(signal)}`}>{signal}</span>
      </header>

      <div className="quote-grid">
        <Quote label="Bid" value={formatPrice(symbol, report.tick?.bid)} />
        <Quote label="Ask" value={formatPrice(symbol, report.tick?.ask)} />
        <Quote label="Spread" value={formatNumber(report.tick?.spread_points, 1)} />
      </div>

      <Sparkline candles={candles} symbol={symbol} />

      <div className="confidence-row">
        <span>Confidence</span>
        <div className="confidence-track">
          <i style={{ width: `${confidencePct}%` }} />
        </div>
        <strong>{formatNumber(confidencePct, 0)}%</strong>
      </div>

      <div className="risk-row">
        <span className={`risk-chip ${riskLevel}`}>
          {(risk.risk_level || decision?.risk_level || "LOW").toUpperCase()}
        </span>
        <span className={`risk-chip ${riskGate}`}>{riskGate.toUpperCase()}</span>
        <span className="risk-chip neutral">
          Score {formatNumber(aggregate.average_score, 2)}
        </span>
      </div>

      <ul className="reason-list">
        {(notes.length ? notes : ["Waiting for strategy data"]).map((reason) => (
          <li key={reason}>{reason}</li>
        ))}
      </ul>
    </article>
  );
}

function Quote({ label, value }) {
  return (
    <div className="quote-cell">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function OrderConsole({ onRefresh }) {
  const [result, setResult] = useState("Order response will appear here.");
  const [sending, setSending] = useState(false);

  async function submitOrder(event) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const payload = {
      symbol: data.get("symbol"),
      side: data.get("side"),
      volume: Number(data.get("volume") || 0.01),
      sl_points: data.get("sl_points") ? Number(data.get("sl_points")) : null,
      tp_points: data.get("tp_points") ? Number(data.get("tp_points")) : null,
      dry_run: data.get("dry_run") === "on",
    };

    setSending(true);
    setResult("Sending order request...");
    try {
      const response = await api("/api/orders/market", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setResult(JSON.stringify(response, null, 2));
      await onRefresh();
    } catch (error) {
      setResult(error.message);
    } finally {
      setSending(false);
    }
  }

  return (
    <section className="order-console" id="orders">
      <header className="panel-header">
        <div>
          <p className="eyebrow">Execution Console</p>
          <h2>Manual order</h2>
        </div>
        <ShieldCheck size={20} />
      </header>

      <div className="order-layout">
        <form className="order-form" onSubmit={submitOrder}>
          <label>
            Pair
            <select name="symbol">
              {SYMBOLS.map((symbol) => (
                <option key={symbol}>{symbol}</option>
              ))}
            </select>
          </label>
          <label>
            Side
            <select name="side">
              <option>BUY</option>
              <option>SELL</option>
            </select>
          </label>
          <label>
            Volume
            <input name="volume" type="number" min="0.01" step="0.01" defaultValue="0.01" />
          </label>
          <label>
            SL points
            <input name="sl_points" type="number" min="1" step="1" placeholder="optional" />
          </label>
          <label>
            TP points
            <input name="tp_points" type="number" min="1" step="1" placeholder="optional" />
          </label>
          <label className="check-label">
            <input name="dry_run" type="checkbox" defaultChecked />
            Dry run
          </label>
          <button className="primary-button" type="submit" disabled={sending}>
            <Send size={16} />
            {sending ? "Sending" : "Send"}
          </button>
        </form>
        <pre className="order-result">{result}</pre>
      </div>
    </section>
  );
}

function DataTable({ title, rows, columns }) {
  return (
    <section className="table-panel">
      <header className="panel-header compact">
        <h2>{title}</h2>
      </header>
      {!rows?.length ? (
        <div className="empty-state">No records</div>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column.label}>{column.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={row.ticket || row.order || index}>
                  {columns.map((column) => (
                    <td key={column.label}>
                      {column.render ? column.render(row) : row[column.key] ?? "-"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function TodayHistoryChart({ deals }) {
  const ref = useRef(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);

    const bg = ctx.createLinearGradient(0, 0, 0, height);
    bg.addColorStop(0, "#0b1322");
    bg.addColorStop(1, "#070c16");
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, width, height);
    ctx.strokeStyle = "rgba(148, 170, 205, 0.08)";
    ctx.lineWidth = 1;
    for (let i = 1; i < 5; i += 1) {
      const y = (height / 5) * i;
      ctx.beginPath();
      ctx.moveTo(24, y);
      ctx.lineTo(width - 16, y);
      ctx.stroke();
    }

    if (!deals.length) {
      ctx.fillStyle = "#c3cfe0";
      ctx.font = "800 18px Inter, system-ui";
      ctx.fillText("No closed trades yet today", 26, 42);
      ctx.fillStyle = "#7e8da6";
      ctx.font = "700 13px Inter, system-ui";
      ctx.fillText("Completed MT5 deals will appear here after trading activity.", 26, 66);
      return;
    }

    const profits = deals.map(dealProfit);
    const cumulative = profits.reduce((items, value) => {
      items.push((items.at(-1) || 0) + value);
      return items;
    }, []);
    const extent = Math.max(1, Math.max(...cumulative.map(Math.abs), ...profits.map(Math.abs)));
    const zeroY = height / 2;
    const barGap = 12;
    const barWidth = Math.max(18, (width - 64 - barGap * (deals.length - 1)) / deals.length);
    const maxBar = height * 0.34;

    ctx.strokeStyle = "rgba(148, 170, 205, 0.22)";
    ctx.beginPath();
    ctx.moveTo(24, zeroY);
    ctx.lineTo(width - 16, zeroY);
    ctx.stroke();

    profits.forEach((profit, index) => {
      const x = 32 + index * (barWidth + barGap);
      const barHeight = Math.max(3, Math.abs(profit / extent) * maxBar);
      const y = profit >= 0 ? zeroY - barHeight : zeroY;
      ctx.fillStyle = profit >= 0 ? "#2ee6a6" : "#fb5e72";
      ctx.beginPath();
      ctx.roundRect(x, y, barWidth, barHeight, 7);
      ctx.fill();
    });

    const xStep = deals.length > 1 ? (width - 96) / (deals.length - 1) : 1;
    const points = cumulative.map((value, index) => ({
      x: 48 + index * xStep,
      y: zeroY - (value / extent) * maxBar,
      value,
    }));

    ctx.strokeStyle = "#22d3ee";
    ctx.lineWidth = 3;
    ctx.shadowColor = "rgba(34, 211, 238, 0.6)";
    ctx.shadowBlur = 12;
    ctx.beginPath();
    points.forEach((point, index) => {
      if (index === 0) ctx.moveTo(point.x, point.y);
      else ctx.lineTo(point.x, point.y);
    });
    ctx.stroke();
    ctx.shadowBlur = 0;

    points.forEach((point) => {
      ctx.fillStyle = "#081120";
      ctx.beginPath();
      ctx.arc(point.x, point.y, 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = "#22d3ee";
      ctx.lineWidth = 2;
      ctx.stroke();
    });

    const last = points.at(-1);
    ctx.fillStyle = "#eaf1fb";
    ctx.font = "900 15px Inter, system-ui";
    ctx.fillText(`Cumulative ${formatNumber(last.value)}`, 26, 28);
  }, [deals]);

  return <canvas ref={ref} className="history-chart" width="980" height="330" />;
}

function TodayHistory({ history = {} }) {
  const deals = useMemo(
    () =>
      [...(history?.deals || [])].sort((a, b) => {
        const first = new Date(a.time_iso || (a.time ? Number(a.time) * 1000 : 0)).getTime();
        const second = new Date(b.time_iso || (b.time ? Number(b.time) * 1000 : 0)).getTime();
        return first - second;
      }),
    [history],
  );
  const trades = useMemo(() => buildTodayTrades(deals), [deals]);
  const realized =
    history?.realized_profit === null || history?.realized_profit === undefined
      ? trades.reduce((sum, trade) => sum + Number(trade.net_profit || 0), 0)
      : Number(history.realized_profit || 0);
  const wins = trades.filter((trade) => Number(trade.net_profit || 0) > 0).length;
  const losses = trades.filter((trade) => Number(trade.net_profit || 0) < 0).length;
  const symbolTotals = useMemo(() => {
    const totals = new Map();
    trades.forEach((trade) => {
      const symbol = trade.symbol || "Other";
      totals.set(symbol, (totals.get(symbol) || 0) + Number(trade.net_profit || 0));
    });
    return [...totals.entries()].sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  }, [trades]);
  const maxSymbolProfit = Math.max(1, ...symbolTotals.map(([, value]) => Math.abs(value)));

  return (
    <section className="history-section" id="today-history">
      <header className="section-header">
        <div>
          <p className="eyebrow">Today&apos;s History</p>
          <h2>Trading result</h2>
        </div>
        <History size={20} />
      </header>

      <div className="history-summary">
        <MetricCard
          icon={CircleDollarSign}
          label="Realized P/L"
          value={history?.unavailable ? "Unavailable" : formatNumber(realized)}
          tone={realized > 0 ? "positive" : realized < 0 ? "negative" : ""}
        />
        <MetricCard icon={BriefcaseBusiness} label="Trades" value={formatNumber(trades.length, 0)} />
        <MetricCard icon={TrendingUp} label="Wins" value={formatNumber(wins, 0)} tone="positive" />
        <MetricCard icon={AlertTriangle} label="Losses" value={formatNumber(losses, 0)} tone="negative" />
      </div>

      <div className="history-layout">
        <article className="history-visual">
          <header className="panel-header compact">
            <h3>Cumulative P/L</h3>
          </header>
          <TodayHistoryChart deals={trades} />
        </article>

        <article className="symbol-breakdown">
          <header className="panel-header compact">
            <h3>By pair</h3>
          </header>
          {!symbolTotals.length ? (
            <div className="empty-state">No closed trade result by pair yet.</div>
          ) : (
            <div className="breakdown-list">
              {symbolTotals.map(([symbol, value]) => (
                <div className="breakdown-row" key={symbol}>
                  <div>
                    <span>{symbol}</span>
                    <strong className={value >= 0 ? "profit-positive" : "profit-negative"}>
                      {formatNumber(value)}
                    </strong>
                  </div>
                  <i
                    className={value >= 0 ? "positive" : "negative"}
                    style={{ width: `${Math.max(8, (Math.abs(value) / maxSymbolProfit) * 100)}%` }}
                  />
                </div>
              ))}
            </div>
          )}
        </article>
      </div>

      <section className="history-details">
        <header className="panel-header compact">
          <h3>Per trade details</h3>
        </header>
        {!trades.length ? (
          <div className="empty-state">
            {history?.unavailable
              ? "Today's MT5 history is unavailable right now."
              : "No completed trades have been recorded today."}
          </div>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Ticket</th>
                  <th>Pair</th>
                  <th>Side</th>
                  <th>Volume</th>
                  <th>Price</th>
                  <th>Profit</th>
                  <th>Comment</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((trade, index) => {
                  const profit = Number(trade.net_profit || 0);
                  const symbol = trade.symbol || "-";
                  return (
                    <tr key={trade.id || `${symbol}-${index}`}>
                      <td>{formatTime(trade.end_time)}</td>
                      <td>{trade.ticket || "-"}</td>
                      <td>{symbol}</td>
                      <td>{trade.side}</td>
                      <td>{formatNumber(trade.volume, 2)}</td>
                      <td>
                        {symbol === "-"
                          ? formatNumber(trade.exit_price, 5)
                          : formatPrice(symbol, trade.exit_price)}
                      </td>
                      <td className={profit >= 0 ? "profit-positive" : "profit-negative"}>
                        {formatNumber(profit)}
                      </td>
                      <td>{trade.comment || "-"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </section>
  );
}

function EquityCurveChart({ curve = [] }) {
  const ref = useRef(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);

    const bg = ctx.createLinearGradient(0, 0, 0, height);
    bg.addColorStop(0, "#0b1322");
    bg.addColorStop(1, "#070c16");
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, width, height);
    ctx.strokeStyle = "rgba(148, 170, 205, 0.08)";
    ctx.lineWidth = 1;
    for (let i = 1; i < 5; i += 1) {
      const y = (height / 5) * i;
      ctx.beginPath();
      ctx.moveTo(24, y);
      ctx.lineTo(width - 16, y);
      ctx.stroke();
    }

    const values = curve.map((point) => Number(point.cumulative)).filter(Number.isFinite);
    if (values.length < 1) {
      ctx.fillStyle = "#c3cfe0";
      ctx.font = "800 18px Inter, system-ui";
      ctx.fillText("No closed trades in this range", 28, 44);
      ctx.fillStyle = "#7e8da6";
      ctx.font = "700 13px Inter, system-ui";
      ctx.fillText("MT5 trade history will plot a running P/L curve here.", 28, 68);
      return;
    }

    const min = Math.min(0, ...values);
    const max = Math.max(0, ...values);
    const range = max - min || 1;
    const padX = 36;
    const padY = 30;
    const plotW = width - padX - 18;
    const plotH = height - padY * 2;
    const xStep = values.length > 1 ? plotW / (values.length - 1) : 0;
    const yFor = (value) => padY + plotH - ((value - min) / range) * plotH;

    const zeroY = yFor(0);
    ctx.strokeStyle = "rgba(148, 170, 205, 0.22)";
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(padX, zeroY);
    ctx.lineTo(width - 18, zeroY);
    ctx.stroke();
    ctx.setLineDash([]);

    const points = values.map((value, index) => ({ x: padX + index * xStep, y: yFor(value), value }));
    const last = points.at(-1);
    const positive = last.value >= 0;
    const stroke = positive ? "#2ee6a6" : "#fb5e72";

    const area = ctx.createLinearGradient(0, padY, 0, height);
    area.addColorStop(0, positive ? "rgba(46, 230, 166, 0.3)" : "rgba(251, 94, 114, 0.28)");
    area.addColorStop(1, "rgba(0, 0, 0, 0)");
    ctx.fillStyle = area;
    ctx.beginPath();
    points.forEach((point, index) => {
      if (index === 0) ctx.moveTo(point.x, point.y);
      else ctx.lineTo(point.x, point.y);
    });
    ctx.lineTo(last.x, zeroY);
    ctx.lineTo(points[0].x, zeroY);
    ctx.closePath();
    ctx.fill();

    ctx.strokeStyle = stroke;
    ctx.lineWidth = 3;
    ctx.shadowColor = stroke;
    ctx.shadowBlur = 14;
    ctx.beginPath();
    points.forEach((point, index) => {
      if (index === 0) ctx.moveTo(point.x, point.y);
      else ctx.lineTo(point.x, point.y);
    });
    ctx.stroke();
    ctx.shadowBlur = 0;

    ctx.fillStyle = stroke;
    ctx.beginPath();
    ctx.arc(last.x, last.y, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "rgba(255, 255, 255, 0.9)";
    ctx.beginPath();
    ctx.arc(last.x, last.y, 2, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = "#eaf1fb";
    ctx.font = "900 15px Inter, system-ui";
    ctx.fillText(`Cumulative ${formatNumber(last.value)}`, 28, 26);
  }, [curve]);

  return <canvas ref={ref} className="history-chart" width="980" height="330" />;
}

function TradeHistory({ demoMode }) {
  const [days, setDays] = useState(HISTORY_ALL_DAYS);
  const [payload, setPayload] = useState(null);
  const [loading, setLoading] = useState(false);
  const [unavailable, setUnavailable] = useState(false);

  const loadHistory = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api(`/api/history?days=${days}`);
      setPayload(data);
      setUnavailable(Boolean(data?.unavailable || data?.summary?.unavailable));
    } catch {
      setPayload(demoHistory(days));
      setUnavailable(false);
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  const summary = payload?.summary || {};
  const trades = useMemo(
    () =>
      [...(payload?.trades || [])].sort(
        (a, b) =>
          new Date(b.close_time || b.open_time || 0) - new Date(a.close_time || a.open_time || 0),
      ),
    [payload],
  );
  const bySymbol = payload?.by_symbol || [];
  const curve = payload?.equity_curve || [];
  const maxSymbol = Math.max(1, ...bySymbol.map((item) => Math.abs(item.net_profit || 0)));
  const realized = Number(summary.realized_profit || 0);
  const winRate = summary.win_rate === null || summary.win_rate === undefined ? null : summary.win_rate;

  return (
    <section className="history-section" id="history">
      <header className="section-header">
        <div>
          <p className="eyebrow">MetaTrader 5 History</p>
          <h2>Trade history</h2>
        </div>
        <div className="header-actions">
          <div className="range-tabs">
            {HISTORY_RANGES.map((range) => (
              <button
                key={range.days}
                className={days === range.days ? "active" : ""}
                onClick={() => setDays(range.days)}
              >
                {range.label}
              </button>
            ))}
          </div>
          <button className="secondary-button" onClick={loadHistory} disabled={loading}>
            <RefreshCw size={16} className={loading ? "spin" : ""} />
            Refresh
          </button>
        </div>
      </header>

      <div className="history-summary">
        <MetricCard
          icon={CircleDollarSign}
          label="Net realized P/L"
          value={unavailable ? "Unavailable" : formatNumber(realized)}
          tone={realized > 0 ? "positive" : realized < 0 ? "negative" : ""}
        />
        <MetricCard icon={BriefcaseBusiness} label="Closed trades" value={formatNumber(summary.trade_count || 0, 0)} />
        <MetricCard
          icon={Gauge}
          label="Win rate"
          value={winRate === null ? "-" : `${formatNumber(winRate * 100, 0)}%`}
        />
        <MetricCard
          icon={TrendingUp}
          label="Profit factor"
          value={
            summary.profit_factor === null || summary.profit_factor === undefined
              ? "-"
              : formatNumber(summary.profit_factor, 2)
          }
          tone={Number(summary.profit_factor) >= 1 ? "positive" : ""}
        />
      </div>

      <div className="history-layout">
        <article className="history-visual">
          <header className="panel-header compact">
            <h3>Equity curve ({historyRangeLabel(days)})</h3>
            <span className="risk-chip neutral">
              {demoMode ? "Demo history" : "Live MT5 deals"}
            </span>
          </header>
          <EquityCurveChart curve={curve} />
        </article>

        <article className="symbol-breakdown">
          <header className="panel-header compact">
            <h3>By pair</h3>
          </header>
          {!bySymbol.length ? (
            <div className="empty-state">No closed trades in this range.</div>
          ) : (
            <div className="breakdown-list">
              {bySymbol.map((item) => {
                const value = Number(item.net_profit || 0);
                return (
                  <div className="breakdown-row" key={item.symbol}>
                    <div>
                      <span>
                        {item.symbol} · {item.trades} trades
                      </span>
                      <strong className={value >= 0 ? "profit-positive" : "profit-negative"}>
                        {formatNumber(value)}
                      </strong>
                    </div>
                    <i
                      className={value >= 0 ? "positive" : "negative"}
                      style={{ width: `${Math.max(8, (Math.abs(value) / maxSymbol) * 100)}%` }}
                    />
                  </div>
                );
              })}
            </div>
          )}
        </article>
      </div>

      <section className="history-details">
        <header className="panel-header compact">
          <h3>Per trade details</h3>
        </header>
        {!trades.length ? (
          <div className="empty-state">
            {unavailable
              ? "MT5 trade history is unavailable right now."
              : "No closed trades were found in this range."}
          </div>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Opened</th>
                  <th>Closed</th>
                  <th>Ticket</th>
                  <th>Pair</th>
                  <th>Side</th>
                  <th>Volume</th>
                  <th>Open</th>
                  <th>Close</th>
                  <th>Profit</th>
                  <th>Comment</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((trade, index) => {
                  const profit = Number(trade.net_profit || 0);
                  const symbol = trade.symbol || "-";
                  return (
                    <tr key={trade.position_id || trade.ticket || index}>
                      <td>{formatDate(trade.open_time)}</td>
                      <td>{formatDate(trade.close_time)}</td>
                      <td>{trade.ticket || "-"}</td>
                      <td>{symbol}</td>
                      <td>
                        <span className={`signal-pill ${cssToken(trade.side)}`}>{trade.side || "-"}</span>
                      </td>
                      <td>{formatNumber(trade.volume, 2)}</td>
                      <td>{symbol === "-" ? formatNumber(trade.open_price, 5) : formatPrice(symbol, trade.open_price)}</td>
                      <td>{symbol === "-" ? formatNumber(trade.close_price, 5) : formatPrice(symbol, trade.close_price)}</td>
                      <td className={profit >= 0 ? "profit-positive" : "profit-negative"}>
                        {formatNumber(profit)}
                      </td>
                      <td>{trade.comment || "-"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </section>
  );
}

function SessionPanel({ session, selectedPlan, setSelectedPlan, onSession }) {
  const [mode, setMode] = useState("login");

  function submit(event) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const nextSession = {
      email: data.get("email"),
      name: data.get("name") || data.get("email"),
    };
    localStorage.setItem("tradingSession", JSON.stringify(nextSession));
    onSession(nextSession);
    window.location.hash = "#dashboard";
  }

  return (
    <section id="session" className="workspace-section">
      <header className="section-header">
        <div>
          <p className="eyebrow">Operator Session</p>
          <h2>Access</h2>
        </div>
        <UserRound size={20} />
      </header>
      <div className="session-grid">
        <div className="auth-panel">
          <div className="tabs">
            <button className={mode === "login" ? "active" : ""} onClick={() => setMode("login")}>
              <LogIn size={15} />
              Login
            </button>
            <button
              className={mode === "register" ? "active" : ""}
              onClick={() => setMode("register")}
            >
              <UserRound size={15} />
              Register
            </button>
          </div>
          <form className="auth-form" onSubmit={submit}>
            {mode === "register" && (
              <label>
                Name
                <input name="name" type="text" autoComplete="name" required />
              </label>
            )}
            <label>
              Email
              <input name="email" type="email" autoComplete="email" required />
            </label>
            <label>
              Password
              <input
                name="password"
                type="password"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                required
              />
            </label>
            <button className="primary-button wide" type="submit">
              {mode === "login" ? "Login" : "Create account"}
            </button>
          </form>
        </div>
        <div className="workspace-note">
          <h3>{session ? session.email : "No active frontend session"}</h3>
          <p>{selectedPlan} plan selected</p>
          <div className="plan-buttons">
            {["Starter", "Pro", "Desk"].map((plan) => (
              <button
                key={plan}
                className={selectedPlan === plan ? "selected" : ""}
                onClick={() => {
                  localStorage.setItem("selectedPlan", plan);
                  setSelectedPlan(plan);
                }}
              >
                {plan}
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function Plans({ selectedPlan, setSelectedPlan }) {
  return (
    <section id="plans" className="workspace-section">
      <header className="section-header">
        <div>
          <p className="eyebrow">Plans</p>
          <h2>Subscription workspace</h2>
        </div>
        <CreditCard size={20} />
      </header>
      <div className="plans-grid">
        {PLANS.map((plan) => (
          <article key={plan.name} className={`plan-card ${selectedPlan === plan.name ? "featured" : ""}`}>
            <h3>{plan.name}</h3>
            <p className="price">
              {plan.price}
              <span>/mo</span>
            </p>
            <p>{plan.description}</p>
            <button
              className={selectedPlan === plan.name ? "primary-button" : "secondary-button"}
              onClick={() => {
                localStorage.setItem("selectedPlan", plan.name);
                setSelectedPlan(plan.name);
              }}
            >
              Select
            </button>
          </article>
        ))}
      </div>
    </section>
  );
}

function Sidebar({ dashboard, demoMode, session, selectedPlan, status, onConnect, onLogout, onHome }) {
  const reports = useMemo(
    () => new Map((dashboard?.symbols || []).map((item) => [item.symbol, item])),
    [dashboard],
  );

  return (
    <aside className="sidebar">
      <div className="sidebar-inner">
        <a
          className="brand"
          href="#top"
          aria-label="AI Trading home"
          onClick={(event) => {
            event.preventDefault();
            onHome?.();
          }}
        >
          <span className="brand-mark">FX</span>
          <span>
            <strong>AI Trading</strong>
            <small>MT5 workstation</small>
          </span>
        </a>
        <nav className="nav">
          <a
            href="#top"
            onClick={(event) => {
              event.preventDefault();
              onHome?.();
            }}
          >
            <Home size={17} />
            Homepage
          </a>
          <a href="#dashboard">
            <BarChart3 size={17} />
            Dashboard
          </a>
          <a href="#today-history">
            <History size={17} />
            Today&apos;s history
          </a>
          <a href="#history">
            <BarChart3 size={17} />
            Trade history
          </a>
          <a href="#markets">
            <TrendingUp size={17} />
            Markets
          </a>
          <a href="#orders">
            <BriefcaseBusiness size={17} />
            Orders
          </a>
        </nav>
        <section className="connection-panel">
          <div className="status-row">
            <span className={`status-chip ${demoMode ? "demo" : "online"}`}>
              {demoMode ? "Demo data" : "Online"}
            </span>
            <span className={`market-chip ${status.isOpen ? "open" : "closed"}`}>{status.label}</span>
          </div>
          <button className="primary-button wide" onClick={onConnect}>
            <Power size={16} />
            Connect MT5
          </button>
          <p>{session ? session.email : "No active frontend session"} | {selectedPlan} plan</p>
          <button className="logout-button" onClick={onLogout}>
            <LogOut size={15} />
            Logout
          </button>
        </section>
        <section className="watchlist">
          <h2>Watchlist</h2>
          {SYMBOLS.map((symbol) => (
            <div className="watch-row" key={symbol}>
              <span>{symbol}</span>
              <strong>{formatPrice(symbol, reports.get(symbol)?.tick?.bid)}</strong>
            </div>
          ))}
          <small>
            {demoMode
              ? "Demo snapshot. Quotes are static."
              : `${status.label}${status.reason ? `: ${status.reason}` : ""}. Quotes update from MT5 snapshots.`}
          </small>
        </section>
      </div>
    </aside>
  );
}

export default function App() {
  const [dashboard, setDashboard] = useState(null);
  const [demoMode, setDemoMode] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [session, setSession] = useState(() => storedSession());
  const [selectedPlan, setSelectedPlan] = useState(
    () => localStorage.getItem("selectedPlan") || "Pro",
  );
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState({ label: "Market closed", isOpen: false });
  const [view, setView] = useState("dashboard");

  const goHome = useCallback(() => {
    setView("landing");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const goDashboard = useCallback(() => {
    setView("dashboard");
    window.location.hash = "#dashboard";
  }, []);

  const forceLogout = useCallback((silent) => {
    if (!silent) {
      api("/api/auth/logout", { method: "POST" }).catch(() => {});
    }
    localStorage.removeItem("tradingSession");
    setSession(null);
    setDashboard(null);
    setLastUpdated(null);
    setDemoMode(false);
    setStatus({ label: "Market closed", isOpen: false });
    setView("dashboard");
    window.location.hash = "#top";
  }, []);

  const loadDashboard = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    try {
      const payload = await api("/api/dashboard");
      setDemoMode(false);
      setDashboard(payload);
      setStatus(mt5MarketStatus(payload));
    } catch (error) {
      if (error?.status === 401) {
        forceLogout(true);
        return;
      }
      setDemoMode(true);
      setDashboard(demoDashboard());
      setStatus({ label: "Market closed", isOpen: false });
    } finally {
      setLastUpdated(new Date());
      setLoading(false);
    }
  }, [session, forceLogout]);

  const connectMT5 = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    try {
      await api("/api/connect", { method: "POST" });
      await loadDashboard();
    } catch (error) {
      if (error?.status === 401) {
        forceLogout(true);
        return;
      }
      setDemoMode(true);
      setDashboard(demoDashboard());
      setStatus({ label: "Market closed", isOpen: false });
      setLastUpdated(new Date());
    } finally {
      setLoading(false);
    }
  }, [loadDashboard, session, forceLogout]);

  useEffect(() => {
    if (!session) return undefined;
    loadDashboard();
    return undefined;
  }, [loadDashboard, session]);

  useEffect(() => {
    if (!session) return undefined;
    const timer = window.setInterval(loadDashboard, 10000);
    return () => window.clearInterval(timer);
  }, [loadDashboard, session]);

  function handleSession(nextSession) {
    setSession(nextSession);
    setView("dashboard");
    if (nextSession?.plan) {
      setSelectedPlan(nextSession.plan);
    }
  }

  function handleLogout() {
    forceLogout(false);
  }

  const account = dashboard?.account || {};
  const strategies = useMemo(
    () => new Map((dashboard?.strategy?.symbols || []).map((item) => [item.symbol, item])),
    [dashboard],
  );
  const decisions = useMemo(
    () => new Map((dashboard?.ai?.decisions || []).map((item) => [item.symbol, item])),
    [dashboard],
  );
  const profit = Number(account.profit || 0);

  if (!session) {
    return (
      <LandingPage
        session={null}
        selectedPlan={selectedPlan}
        setSelectedPlan={setSelectedPlan}
        onSession={handleSession}
      />
    );
  }

  if (view === "landing") {
    return (
      <LandingPage
        session={session}
        selectedPlan={selectedPlan}
        setSelectedPlan={setSelectedPlan}
        onEnterDashboard={goDashboard}
        onLogout={handleLogout}
      />
    );
  }

  return (
    <div className="app-shell">
      <Sidebar
        dashboard={dashboard}
        demoMode={demoMode}
        session={session}
        selectedPlan={selectedPlan}
        status={status}
        onConnect={connectMT5}
        onLogout={handleLogout}
        onHome={goHome}
      />
      <main className="workspace" id="dashboard">
        <header className="hero-panel">
          <div>
            <p className="eyebrow">Live Operations</p>
            <h1>Trading command center</h1>
            <p>
              Strategy, risk, execution, and account health — monitored and managed from a single
              MT5 workstation.
            </p>
          </div>
          <div className="header-actions">
            <span className="updated-chip">
              {lastUpdated ? `Updated ${lastUpdated.toLocaleTimeString()}` : "Waiting for data"}
            </span>
            <button className="secondary-button" onClick={loadDashboard} disabled={loading}>
              <RefreshCw size={16} className={loading ? "spin" : ""} />
              Refresh
            </button>
          </div>
        </header>

        <section className="metrics-grid">
          <MetricCard
            icon={Wallet}
            label="Balance"
            value={`${formatNumber(account.balance)} ${account.currency || ""}`}
          />
          <MetricCard icon={Gauge} label="Equity" value={formatNumber(account.equity)} />
          <MetricCard
            icon={CircleDollarSign}
            label="Free margin"
            value={formatNumber(account.margin_free)}
          />
          <MetricCard
            icon={Activity}
            label="Profit"
            value={formatNumber(account.profit)}
            tone={profit > 0 ? "positive" : profit < 0 ? "negative" : ""}
          />
          <MetricCard
            icon={AlertTriangle}
            label="Leverage"
            value={account.leverage ? `1:${account.leverage}` : "-"}
          />
        </section>

        <TodayHistory history={dashboard?.today_history} />

        <TradeHistory demoMode={demoMode} />

        <OrderConsole onRefresh={loadDashboard} />

        <section className="markets-grid" id="markets">
          {(dashboard?.symbols || []).map((report) => (
            <MarketCard
              key={report.symbol}
              report={report}
              strategy={strategies.get(report.symbol)}
              decision={decisions.get(report.symbol)}
            />
          ))}
        </section>

        <section className="tables-grid">
          <DataTable
            title="Open positions"
            rows={dashboard?.positions || []}
            columns={[
              { key: "ticket", label: "Ticket" },
              { key: "symbol", label: "Pair" },
              { key: "volume", label: "Volume" },
              {
                key: "type",
                label: "Side",
                render: (row) => (row.type === 0 ? "BUY" : row.type === 1 ? "SELL" : row.type),
              },
              {
                key: "price_open",
                label: "Open",
                render: (row) => formatPrice(row.symbol, row.price_open),
              },
              { key: "profit", label: "Profit", render: (row) => formatNumber(row.profit) },
            ]}
          />
          <DataTable
            title="Pending orders"
            rows={dashboard?.pending_orders || []}
            columns={[
              { key: "ticket", label: "Ticket" },
              { key: "symbol", label: "Pair" },
              { key: "volume_current", label: "Volume" },
              {
                key: "price_open",
                label: "Price",
                render: (row) => formatPrice(row.symbol, row.price_open),
              },
              { key: "comment", label: "Comment" },
            ]}
          />
        </section>

      </main>
    </div>
  );
}
