const state = {
  session: JSON.parse(localStorage.getItem("tradingSession") || "null"),
  selectedPlan: localStorage.getItem("selectedPlan") || "Pro",
  dashboard: null,
  demoMode: false,
};

const els = {
  connectBtn: document.getElementById("connectBtn"),
  refreshBtn: document.getElementById("refreshBtn"),
  statusBadge: document.getElementById("statusBadge"),
  accountGrid: document.getElementById("accountGrid"),
  symbolsGrid: document.getElementById("symbolsGrid"),
  positionsTable: document.getElementById("positionsTable"),
  ordersTable: document.getElementById("ordersTable"),
  orderForm: document.getElementById("orderForm"),
  orderResult: document.getElementById("orderResult"),
  sessionState: document.getElementById("sessionState"),
  lastUpdated: document.getElementById("lastUpdated"),
  marketState: document.getElementById("marketState"),
  quoteSource: document.getElementById("quoteSource"),
  tapeEur: document.getElementById("tapeEur"),
  tapeGbp: document.getElementById("tapeGbp"),
  tapeJpy: document.getElementById("tapeJpy"),
  loginForm: document.getElementById("loginForm"),
  registerForm: document.getElementById("registerForm"),
};

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
  const digits = symbol === "USDJPY" ? 3 : 5;
  return formatNumber(value, digits);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || response.statusText);
  }
  return response.json();
}

function setStatus(online, text) {
  els.statusBadge.textContent = text || (online ? "Online" : "Offline");
  els.statusBadge.className = `status-badge ${online ? "online" : "offline"}`;
}

function forexMarketStatus(now = new Date()) {
  const day = now.getUTCDay();
  const hour = now.getUTCHours();
  if (day === 6 || day === 0 || (day === 5 && hour >= 22) || (day === 1 && hour < 22)) {
    return "Market closed";
  }
  return "Market open";
}

function updateSession() {
  const user = state.session?.email || "No active frontend session";
  els.sessionState.textContent = state.session
    ? `${user} | ${state.selectedPlan} plan`
    : `${user} | ${state.selectedPlan} plan selected`;
}

function cssToken(value) {
  return String(value || "").toLowerCase().replaceAll("_", "-");
}

function buildMetric(label, value, tone = "") {
  return `<div class="metric ${tone}"><span>${label}</span><strong>${value}</strong></div>`;
}

function renderAccount(account = {}) {
  const profit = Number(account.profit || 0);
  els.accountGrid.innerHTML = [
    buildMetric("Balance", `${formatNumber(account.balance)} ${account.currency || ""}`),
    buildMetric("Equity", formatNumber(account.equity)),
    buildMetric("Free margin", formatNumber(account.margin_free)),
    buildMetric("Profit", formatNumber(account.profit), profit > 0 ? "positive" : profit < 0 ? "negative" : ""),
    buildMetric("Leverage", account.leverage ? `1:${account.leverage}` : "-"),
  ].join("");
}

function renderMarketTape(payload) {
  const reports = new Map((payload.symbols || []).map((item) => [item.symbol, item]));
  const values = {
    EURUSD: reports.get("EURUSD")?.tick?.bid,
    GBPUSD: reports.get("GBPUSD")?.tick?.bid,
    USDJPY: reports.get("USDJPY")?.tick?.bid,
  };

  if (els.tapeEur) els.tapeEur.textContent = formatPrice("EURUSD", values.EURUSD);
  if (els.tapeGbp) els.tapeGbp.textContent = formatPrice("GBPUSD", values.GBPUSD);
  if (els.tapeJpy) els.tapeJpy.textContent = formatPrice("USDJPY", values.USDJPY);

  const marketStatus = forexMarketStatus();
  if (els.marketState) {
    els.marketState.textContent = marketStatus;
    els.marketState.className = `market-state ${marketStatus === "Market open" ? "open" : "closed"}`;
  }
  if (els.quoteSource) {
    els.quoteSource.textContent = state.demoMode
      ? "Demo snapshot. Prices are frozen until refresh data changes."
      : `${marketStatus}. Quotes come from MT5 dashboard snapshots.`;
  }
}

function renderSymbols(payload) {
  const strategies = new Map((payload.strategy?.symbols || []).map((item) => [item.symbol, item]));
  const decisions = new Map((payload.ai?.decisions || []).map((item) => [item.symbol, item]));

  els.symbolsGrid.innerHTML = (payload.symbols || [])
    .map((report) => {
      const symbol = report.symbol;
      const tick = report.tick || {};
      const strategy = strategies.get(symbol) || {};
      const decision = decisions.get(symbol) || {};
      const signal = strategy.final_signal || "HOLD";
      const risk = strategy.metadata?.risk || {};
      const aggregate = strategy.metadata?.aggregate || {};
      const rawSignal = strategy.metadata?.raw_signal || signal;
      const signalClass = cssToken(signal);
      const confidence = Number(strategy.confidence || 0);
      const confidencePct = Math.max(0, Math.min(100, confidence * 100));
      const riskLevel = cssToken(risk.risk_level || decision.risk_level || "LOW");
      const riskGate = risk.allow_trade ? "allowed" : rawSignal === "HOLD" ? "waiting" : "blocked";
      const notes = [
        ...(risk.blockers || []),
        ...(risk.warnings || []),
        ...(strategy.reasons || []),
        ...(decision.reasons || []),
      ];
      const reasons = (notes.length ? notes : ["Waiting for strategy data"])
        .slice(0, 3)
        .map((reason) => `<li>${reason}</li>`)
        .join("");

      return `
        <article class="symbol-card">
          <div class="symbol-header">
            <div>
              <h3>${symbol}</h3>
              <p class="eyebrow">${decision.action || "HOLD"} | raw ${rawSignal}</p>
            </div>
            <span class="signal ${signalClass}">${signal}</span>
          </div>
          <div class="quote-row">
            <div><span>Bid</span><strong>${formatPrice(symbol, tick.bid)}</strong></div>
            <div><span>Ask</span><strong>${formatPrice(symbol, tick.ask)}</strong></div>
            <div><span>Spread</span><strong>${formatNumber(tick.spread_points, 1)}</strong></div>
          </div>
          <canvas id="chart-${symbol}" class="pair-chart" width="520" height="260"></canvas>
          <div class="confidence">
            <span>Confidence</span>
            <div class="confidence-track"><i style="width: ${confidencePct}%"></i></div>
            <strong>${formatNumber(confidencePct, 0)}%</strong>
          </div>
          <div class="risk-row">
            <span class="risk-chip ${riskLevel}">${(risk.risk_level || decision.risk_level || "LOW").toUpperCase()}</span>
            <span class="risk-chip ${riskGate}">${riskGate.toUpperCase()}</span>
            <span class="risk-chip">Score ${formatNumber(aggregate.average_score, 2)}</span>
          </div>
          <ul class="decision-list">${reasons}</ul>
        </article>
      `;
    })
    .join("");

  (payload.symbols || []).forEach((report) => {
    drawChart(`chart-${report.symbol}`, report.timeframes?.M5?.candles || [], report.symbol);
  });
}

function renderTable(target, rows, columns) {
  if (!rows || rows.length === 0) {
    target.innerHTML = `<div class="empty-state">No records</div>`;
    return;
  }

  const head = columns.map((column) => `<th>${column.label}</th>`).join("");
  const body = rows
    .map((row) => {
      const cells = columns
        .map((column) => `<td>${column.render ? column.render(row) : row[column.key] ?? "-"}</td>`)
        .join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");

  target.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function renderTables(payload) {
  renderTable(els.positionsTable, payload.positions || [], [
    { key: "ticket", label: "Ticket" },
    { key: "symbol", label: "Pair" },
    { key: "volume", label: "Volume" },
    {
      key: "type",
      label: "Side",
      render: (row) => (row.type === 0 ? "BUY" : row.type === 1 ? "SELL" : row.type),
    },
    { key: "price_open", label: "Open", render: (row) => formatPrice(row.symbol, row.price_open) },
    { key: "profit", label: "Profit", render: (row) => formatNumber(row.profit) },
  ]);

  renderTable(els.ordersTable, payload.pending_orders || [], [
    { key: "ticket", label: "Ticket" },
    { key: "symbol", label: "Pair" },
    { key: "volume_current", label: "Volume" },
    { key: "price_open", label: "Price", render: (row) => formatPrice(row.symbol, row.price_open) },
    { key: "comment", label: "Comment" },
  ]);
}

function renderDashboard(payload) {
  state.dashboard = payload;
  renderAccount(payload.account || {});
  renderMarketTape(payload);
  renderSymbols(payload);
  renderTables(payload);
  setStatus(!state.demoMode, state.demoMode ? "Demo data" : "Online");
  if (els.lastUpdated) {
    els.lastUpdated.textContent = `Updated ${new Date().toLocaleTimeString()}`;
  }
}

function demoDashboard() {
  const symbols = ["EURUSD", "GBPUSD", "USDJPY"];
  const prices = { EURUSD: 1.08742, GBPUSD: 1.27411, USDJPY: 156.223 };

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
    symbols: symbols.map((symbol, index) => {
      const candles = Array.from({ length: 90 }, (_, i) => {
        const base = prices[symbol] + Math.sin(i / 8 + index) * (symbol === "USDJPY" ? 0.12 : 0.0012);
        return {
          time: new Date(Date.now() - (90 - i) * 60000).toISOString(),
          open: base,
          high: base + (symbol === "USDJPY" ? 0.08 : 0.0008),
          low: base - (symbol === "USDJPY" ? 0.08 : 0.0008),
          close: base + Math.cos(i / 5) * (symbol === "USDJPY" ? 0.04 : 0.0004),
        };
      });
      const last = candles[candles.length - 1].close;
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
        {
          symbol: "EURUSD",
          final_signal: "BUY",
          confidence: 0.82,
          reasons: ["Weighted score 0.74", "H1 confirmation: BUY"],
          metadata: {
            raw_signal: "BUY",
            risk: { allow_trade: true, risk_level: "LOW", blockers: [], warnings: [], checks: {} },
            aggregate: { average_score: 0.74 },
          },
        },
        {
          symbol: "GBPUSD",
          final_signal: "SELL",
          confidence: 0.76,
          reasons: ["Weighted score -0.68", "H1 confirmation: SELL"],
          metadata: {
            raw_signal: "SELL",
            risk: { allow_trade: true, risk_level: "LOW", blockers: [], warnings: ["Spread is near limit"], checks: {} },
            aggregate: { average_score: -0.68 },
          },
        },
        {
          symbol: "USDJPY",
          final_signal: "HOLD",
          confidence: 0.44,
          reasons: ["Weighted score 0.12", "H1 confirmation: HOLD"],
          metadata: {
            raw_signal: "HOLD",
            risk: { allow_trade: false, risk_level: "LOW", blockers: [], warnings: [], checks: {} },
            aggregate: { average_score: 0.12 },
          },
        },
      ],
    },
    ai: {
      decisions: [
        { symbol: "EURUSD", action: "BUY", risk_level: "LOW", reasons: ["BUY signal confirmed with no open position"] },
        { symbol: "GBPUSD", action: "SELL", risk_level: "LOW", reasons: ["SELL signal confirmed with no open position"] },
        { symbol: "USDJPY", action: "HOLD", risk_level: "LOW", reasons: ["Strategy agreement is not strong enough"] },
      ],
    },
  };
}

async function loadDashboard() {
  try {
    state.demoMode = false;
    const payload = await api("/api/dashboard");
    renderDashboard(payload);
  } catch (error) {
    state.demoMode = true;
    renderDashboard(demoDashboard());
    els.orderResult.textContent = `MT5 dashboard fallback: ${error.message}`;
  }
}

async function connectMT5() {
  els.connectBtn.disabled = true;
  els.connectBtn.textContent = "Connecting";
  try {
    await api("/api/connect", { method: "POST" });
    await loadDashboard();
  } catch (error) {
    state.demoMode = true;
    setStatus(false, "Connection error");
    els.orderResult.textContent = error.message;
  } finally {
    els.connectBtn.disabled = false;
    els.connectBtn.textContent = "Connect MT5";
  }
}

function drawChart(id, candles, symbol = "") {
  const canvas = document.getElementById(id);
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);

  ctx.fillStyle = "#fbfcfe";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#e1e7ee";
  ctx.lineWidth = 1;
  for (let i = 1; i < 5; i += 1) {
    const y = (height / 5) * i;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }

  if (!candles || candles.length < 2) {
    ctx.fillStyle = "#667174";
    ctx.fillText("No candle data", 18, 28);
    return;
  }

  const closes = candles.map((candle) => Number(candle.close)).filter(Number.isFinite);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;
  const xStep = width / Math.max(closes.length - 1, 1);
  const points = closes.map((value, index) => ({
    x: index * xStep,
    y: height - ((value - min) / range) * (height - 42) - 21,
    value,
  }));

  const area = ctx.createLinearGradient(0, 18, 0, height);
  area.addColorStop(0, "rgba(13, 138, 126, 0.24)");
  area.addColorStop(1, "rgba(13, 138, 126, 0.02)");
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

  ctx.strokeStyle = "#0d8a7e";
  ctx.lineWidth = 3;
  ctx.beginPath();
  points.forEach((point, index) => {
    if (index === 0) ctx.moveTo(point.x, point.y);
    else ctx.lineTo(point.x, point.y);
  });
  ctx.stroke();

  const last = closes[closes.length - 1];
  const lastPoint = points[points.length - 1];
  ctx.fillStyle = "#0d8a7e";
  ctx.beginPath();
  ctx.arc(lastPoint.x, lastPoint.y, 5, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = "#15191f";
  ctx.font = "700 16px system-ui";
  ctx.fillText(`${symbol} ${formatPrice(symbol, last)}`, 14, 25);
}

function bindAuth() {
  document.querySelectorAll("[data-auth-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll("[data-auth-tab]").forEach((tab) => tab.classList.remove("active"));
      button.classList.add("active");
      const mode = button.dataset.authTab;
      els.loginForm.classList.toggle("hidden", mode !== "login");
      els.registerForm.classList.toggle("hidden", mode !== "register");
    });
  });

  [els.loginForm, els.registerForm].forEach((form) => {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const data = new FormData(form);
      state.session = {
        email: data.get("email"),
        name: data.get("name") || data.get("email"),
      };
      localStorage.setItem("tradingSession", JSON.stringify(state.session));
      updateSession();
      window.location.hash = "#dashboard";
    });
  });
}

function bindPlans() {
  document.querySelectorAll(".plan-btn").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedPlan = button.dataset.plan;
      localStorage.setItem("selectedPlan", state.selectedPlan);
      updateSession();
    });
  });
}

function bindOrders() {
  els.orderForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(els.orderForm);
    const payload = {
      symbol: data.get("symbol"),
      side: data.get("side"),
      volume: Number(data.get("volume") || 0.01),
      sl_points: data.get("sl_points") ? Number(data.get("sl_points")) : null,
      tp_points: data.get("tp_points") ? Number(data.get("tp_points")) : null,
      dry_run: data.get("dry_run") === "on",
    };

    els.orderResult.textContent = "Sending order request...";
    try {
      const result = await api("/api/orders/market", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      els.orderResult.textContent = JSON.stringify(result, null, 2);
      await loadDashboard();
    } catch (error) {
      els.orderResult.textContent = error.message;
    }
  });
}

els.connectBtn.addEventListener("click", connectMT5);
els.refreshBtn.addEventListener("click", loadDashboard);

bindAuth();
bindPlans();
bindOrders();
updateSession();
loadDashboard();
setInterval(loadDashboard, 10000);
