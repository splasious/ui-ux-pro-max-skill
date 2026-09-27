/* Swing Master -- execution screens: trade setup / decision, active trades, risk. */
(function () {
  "use strict";
  const SM = window.SM, ui = SM.ui, esc = SM.esc;
  SM.parts = SM.parts || {};

  // ------------------------------------------------------------------ shared: plan side panel
  function planKv(p) {
    if (!p || !p.valid) return ui.empty("No valid plan", p && p.reason ? p.reason : "");
    const legs = p.allocation.qty;
    return ui.kv([
      ["Capital", SM.inr(p.capital)], ["Risk per trade", `${SM.fmt(p.risk_pct, 2)}% <span class="muted">(${SM.inr(p.risk_amount)})</span>`],
      ["Entry", SM.fmt(p.entry)], ["Stop loss", `<span class="down">${SM.fmt(p.stop)}</span>`], ["Risk / share", SM.fmt(p.risk_per_share)],
      ["Quantity", `${SM.fmt(p.quantity, 0)}${p.lot_size > 1 ? ` <span class="muted">(lot ${p.lot_size})</span>` : ""}`],
      ["Position value", SM.inr(p.position_value)],
      ["Target 1", `<span class="up">${SM.fmt(p.t1)}</span> <span class="muted">${SM.pct(p.allocation.t1, 0)} · ${legs[0]}</span>`],
      ["Target 2", `<span class="up">${SM.fmt(p.t2)}</span> <span class="muted">${SM.pct(p.allocation.t2, 0)} · ${legs[1]}</span>`],
      ["Target 3", `<span class="up">${SM.fmt(p.t3)}</span> <span class="muted">runner ${SM.pct(p.allocation.runner, 0)} · ${legs[2]}</span>`],
      ["R:R (T1 / T2 / T3)", p.rr.map((r) => (SM.isNum(r) ? "1:" + SM.fmt(r, 1) : "—")).join(" / ")],
      ["After T1", esc(SM.title(p.breakeven_mode))], ["Structural trail", esc(p.trail)],
    ]) + (p.size_notes && p.size_notes.length ? ui.notice(esc(p.size_notes.join("; "))) : "");
  }
  SM.parts.planKv = planKv;

  function activeTradeCards(el, t, compact) {
    const long = t.direction === "LONG", risk = Math.abs(t.entry - t.initial_stop);
    const rr = t.targets.map((v) => (risk ? Math.abs(v - t.entry) / risk : null));
    const plan = { valid: true, direction: t.direction, entry: t.entry, stop: t.current_stop, t1: t.targets[0], t2: t.targets[1], t3: t.targets[2], rr };
    el.innerHTML = ui.card({ title: `Active trade · ${esc(t.symbol)} <small>${esc(t.direction)}</small>`, actions: ui.status("ACTIVE"),
      body: `<div id="pc-ladder"></div>${ui.kv([
        ["Entry", `${SM.fmt(t.entry)} <span class="muted">${SM.dateShort(t.entry_time)}</span>`], ["Initial / current SL", `<span class="down">${SM.fmt(t.initial_stop)}</span> → <b>${SM.fmt(t.current_stop)}</b>`],
        ["Targets hit", t.targets_hit.map((h, i) => `T${i + 1} ${h ? '<span class="up">✓</span>' : '<span class="muted">·</span>'}`).join(" ")],
        ["Quantity (open / booked)", `${t.remaining_qty} / ${t.booked_qty}`], ["Current R", `<b class="${SM.dir(t.current_r)}">${SM.signed(t.current_r, 2)}R</b>`],
        ["P&L", ui.money(t.net_pnl + t.unrealized_pnl)], ["Structural trail", t.last_confirmed_pivot ? `${esc(t.last_confirmed_pivot.label)} ${SM.fmt(t.last_confirmed_pivot.price)}` : "awaiting confirmed " + (long ? "HL" : "LH")]])}`,
      note: compact ? `<a href="#trades">Manage trade →</a>` : "" })
      + ui.card({ title: "Why this trade?", sub: "rules at entry", body: ui.checklist((t.snapshot.why || []).map((w) => ({ ok: w.ok, text: w.text }))) });
    SM.charts.ladder(el.querySelector("#pc-ladder"), plan);
  }

  SM.parts.planCards = async function (el, symbol, compact) {
    el.innerHTML = ui.card({ title: "Trade plan", body: ui.loading() });
    const ov = SM.state.overview;
    const active = ov && ov.active_trades.find((t) => t.symbol === symbol);
    if (active) { activeTradeCards(el, active, compact); return; }
    try {
      const d = await SM.api.get("/api/setup", { symbol, tf: "1D" });
      const ev = d.evaluation;
      const status = d.mode === "EVALUATED" ? ev.decision.status : "NO TRIGGER";
      const head = `${esc(d.symbol)} <small>${d.mode === "EVALUATED" ? esc(ev.direction) : "Watching"}</small>`;
      const plan = d.plan;
      const whyItems = d.mode === "EVALUATED"
        ? d.why.map((w) => ({ ok: w.ok, text: w.text }))
        : d.checklist.flatMap((c) => c.items.map((it) => ({ ok: it.ok, text: `${c.direction}: ${it.text}` }))).slice(0, 8);
      el.innerHTML = ui.card({ title: `Trade plan · ${head}`, actions: ui.status(status === "CANDIDATE" ? "READY" : status) + (plan && plan.projected ? ui.badge("Projected", "b-warn") : ""),
        body: plan ? `<div id="pc-ladder"></div>${compact ? "" : planKv(plan)}` : ui.empty("No plan", "Price is not near a qualified zone."),
        note: compact ? `<a href="#setup">Full decision breakdown →</a>` : "" })
        + ui.card({ title: d.mode === "EVALUATED" && ev.decision.accepted ? "Why this trade?" : "Why no trade?",
          body: ui.checklist(whyItems.slice(0, compact ? 8 : 40)) });
      if (plan) SM.charts.ladder(el.querySelector("#pc-ladder"), plan);
    } catch (err) { el.innerHTML = ui.card({ title: "Trade plan", body: ui.error(err) }); }
  };

  // ------------------------------------------------------------------ Trade Setup / Decision
  SM.views.setup = {
    title: "Trade Setup", icon: "setup", group: "Execution",
    async render(el) {
      el.innerHTML = `<div class="view-head"><div><h1>Trade decision</h1><p>Every rule, every factor, every point. Accepted and rejected setups expose the same rule-by-rule path.</p></div>
        <div class="actions"><div class="ctx-field"><label for="su-sym">Symbol</label>${ui.symbolSelect("su-sym", SM.state.symbol)}</div></div></div><div id="su"></div>`;
      el.querySelector("#su-sym").addEventListener("change", (e) => { SM.setState({ symbol: e.target.value }); draw(); });
      const body = el.querySelector("#su");
      const draw = () => ui.load(body, async () => {
        const d = await SM.api.get("/api/setup", { symbol: SM.state.symbol, tf: "1D" });
        if (d.mode === "EVALUATED") renderEvaluated(body, d); else renderNoTrigger(body, d);
      });
      draw();
    },
  };

  function breakdown(rows, weights) {
    return `<div class="brk">${rows.map((r) => {
      const src = r.source || "";
      return `<span>${esc(r.name)} <span class="src">${src ? ui.status(src) : ""}</span></span>${ui.bar(r.fraction, r.fraction == null ? "" : r.fraction >= 0.66 ? "up" : r.fraction >= 0.4 ? "warn" : "down")}
        <span class="val">${r.points == null ? '<span class="muted">n/a</span>' : SM.fmt(r.points, 1)}<span class="muted">/${r.weight}</span></span>`;
    }).join("")}</div>`;
  }

  function renderEvaluated(body, d) {
    const ev = d.evaluation, dec = ev.decision, conf = dec.confluence;
    const accepted = dec.accepted;
    const rows = conf.rows.map((r) => ({ ...r, source: (ev.factor_meta[r.key] || {}).source }));
    const verdict = accepted ? `${esc(ev.direction)} CANDIDATE` : `${esc(ev.direction)} REJECTED`;
    body.innerHTML = `
      <div class="grid g-main-l">
        ${ui.card({ title: `${esc(d.symbol)} — ${verdict}`, actions: ui.status(accepted ? "READY" : "REJECTED"), body: `
          <div class="big-score"><span class="n ${accepted ? "up" : ""}">${SM.fmt(conf.score, 0)}</span><span class="d">/ 100</span>
            <div style="display:grid;gap:4px;font-size:12.5px">
              <span>Minimum ${dec.min_confluence}${ui.tip("Confluence is a weighted 0-100 score. Every factor's points are listed below; unavailable data is excluded and the rest renormalised.")} · ${conf.score >= dec.min_confluence ? '<b class="up">pass</b>' : '<b class="down">below</b>'}</span>
              <span>Zone score ${ui.scoreChip(dec.zone_score.score, dec.min_zone_score)} <span class="muted">min ${dec.min_zone_score}</span></span>
              <span class="muted">Data coverage ${SM.pct(conf.coverage, 0)} · raw ${SM.fmt(conf.raw_points, 1)}/${SM.fmt(conf.available_points, 0)} pts</span></div></div>
          <div style="margin-top:14px">${breakdown(rows)}</div>`,
          note: "Unavailable factors are excluded and the score is renormalised over the available weight (policy: RENORMALIZE)." })}
        <div class="grid">
          ${ui.card({ title: accepted ? "Why this trade?" : "Why no trade?", body: ui.checklist(d.why.map((w) => ({ ok: w.ok, text: w.text }))) })}
        </div>
      </div>
      <div class="grid g-2">
        ${ui.card({ title: "Visual trade plan", sub: `${esc(ev.entry_mode.replace(/_/g, " ").toLowerCase())} entry`, body: '<div id="su-ladder"></div>' })}
        ${ui.card({ title: "Position sizing", body: planKv(d.plan) })}
      </div>
      <div class="grid g-3">
        ${ui.card({ title: "Zone at decision", body: ui.kv([
          ["Zone", `<b class="${ev.zone.type === "DEMAND" ? "up" : "down"}">${esc(SM.title(ev.zone.type))} ${esc(ev.zone.pattern)}</b>`],
          ["Proximal / distal", `${SM.fmt(ev.zone.proximal)} / ${SM.fmt(ev.zone.distal)}`], ["Status", ui.status(ev.zone.status)],
          ["Prior tests", String(ev.prior_tests)], ["Departure", SM.fmt(ev.zone.departure_atr, 2) + " ATR"], ["Created", SM.date(ev.zone.creation_time)],
          ["Stop reference", esc(ev.stop_note)]]) })}
        ${ui.card({ title: "Context at decision", body: ui.kv([
          ["Trend / HTF", `${ui.trendBadge(ev.trend)} ${ui.trendBadge(ev.htf_trend)}`],
          ["Last pivot", ev.last_pivot ? `${esc(ev.last_pivot.label || ev.last_pivot.type)} ${SM.fmt(ev.last_pivot.price)} <span class="muted">conf. ${SM.dateShort(ev.last_pivot.confirmation_time)}</span>` : "—"],
          ["Structure event", ev.last_event ? `${esc(SM.title(ev.last_event.direction))} ${ev.last_event.type === "CHOCH" ? "CHoCH" : "BOS"}` : "—"],
          ["POC / VAH / VAL", ev.vp ? `${SM.fmt(ev.vp.poc, 0)} / ${SM.fmt(ev.vp.vah, 0)} / ${SM.fmt(ev.vp.val, 0)}` : "—"],
          ["Price vs value", esc(ev.vp ? ev.vp.location : "—")],
          ["Futures OI", ev.oi ? `${esc(ev.oi.state)} ${ui.status("PROXY")}` : ui.status("UNAVAILABLE")],
          ["PCR / ΔOI PCR", ev.pcr ? `${SM.fmt(ev.pcr.pcr, 2)} / ${SM.isNum(ev.pcr.change_oi_pcr) ? SM.fmt(ev.pcr.change_oi_pcr, 2) : "—"}` : ui.status("UNAVAILABLE")],
          ["Positioning", ui.status(ev.positioning.COMMERCIAL.status)],
          ["Decision time", SM.dateTime(ev.decision_time)]]) })}
        ${ui.card({ title: "Reversal candle", body: ev.pattern ? ui.kv([
          ["Pattern", `<b>${esc(SM.title(ev.pattern.pattern))}</b>`], ["Confidence", SM.pct(ev.pattern.confidence, 0)],
          ["Body", SM.pct(ev.pattern.metrics.body_ratio, 0)], ["Upper / lower wick", `${SM.pct(ev.pattern.metrics.upper_wick_ratio, 0)} / ${SM.pct(ev.pattern.metrics.lower_wick_ratio, 0)}`],
          ["Range / ATR", SM.fmt(ev.pattern.metrics.atr_range, 2)], ["Close location", SM.pct(ev.pattern.metrics.close_location, 0)],
          ["Previous candle", esc(ev.pattern.metrics.previous_relationship)]]) : ui.empty("No reversal candle on the decision bar") })}
      </div>
      ${historyCard(d)}`;
    SM.charts.ladder(body.querySelector("#su-ladder"), { ...d.plan, zone: ev.zone });
    bindHistory(body, d);
  }

  function renderNoTrigger(body, d) {
    body.innerHTML = `
      <div class="grid g-main-l">
        ${ui.card({ title: `${esc(d.symbol)} — why no trade?`, actions: ui.status("WAIT"), body: `
          <p class="muted" style="margin-top:0">Price ${SM.fmt(d.price)} did not trade into a qualified zone on the latest bar, so the decision engine had nothing to evaluate. Here is what each direction still needs.</p>
          ${d.checklist.map((c) => `<h3 class="section-title">${esc(c.direction)}</h3>${ui.checklist(c.items)}`).join("")}
          ${d.reasons.length ? `<h3 class="section-title">Scanner</h3>${d.reasons.map((r) => `<div style="margin:4px 0">${ui.dirBadge(r.direction)} ${ui.status(r.status)} <span class="muted">${esc(r.reason || "")}</span></div>`).join("")}` : ""}` })}
        <div class="grid">
          ${d.plan ? ui.card({ title: "Projected plan", sub: "if price reaches the nearest qualified zone", actions: ui.badge("Projected", "b-warn"), body: '<div id="su-ladder"></div>' + planKv(d.plan) }) : ui.card({ title: "Projected plan", body: ui.empty("No qualified zone nearby") })}
        </div>
      </div>
      ${historyCard(d)}`;
    if (d.plan) SM.charts.ladder(body.querySelector("#su-ladder"), d.plan);
    bindHistory(body, d);
  }

  function historyCard(d) {
    return `<div class="grid g-2"><div id="su-mtf"></div>${ui.card({ title: "Recent evaluations", sub: "zone touches on this symbol", body: '<div id="su-hist"></div>', flush: true })}</div>`;
  }
  function bindHistory(body, d) {
    SM.parts.mtfCard(body.querySelector("#su-mtf"), d.symbol);
    ui.table(body.querySelector("#su-hist"), { compact: true, rows: d.history, empty: ui.empty("No zone interactions yet"), columns: [
      { key: "time", label: "Date", render: (h) => SM.date(h.time) }, { key: "direction", label: "Dir", render: (h) => ui.dirBadge(h.direction) },
      { key: "score", label: "Score", num: true, render: (h) => ui.scoreChip(h.score, d.min_confluence) },
      { key: "status", label: "Status", render: (h) => ui.status(h.status === "CANDIDATE" ? "ACCEPTED" : h.status) },
      { key: "reason", label: "Reason", cls: "wrap", render: (h) => esc(h.reason || "All rules passed") },
    ] });
  }

  // ------------------------------------------------------------------ trades table (shared)
  SM.parts.tradesTable = function (el, trades, compact) {
    ui.table(el, { rows: trades, compact, rowKey: (t) => t.trade_id, empty: ui.empty("No open positions", "The engine has no qualifying trade open right now."),
      expand: compact ? null : (t) => tradeDetail(t),
      onRow: compact ? (t) => SM.openSymbol(t.symbol, "trades") : null,
      columns: [
        { key: "symbol", label: "Symbol", render: (t) => `<span class="sym">${esc(t.symbol)}</span>` },
        { key: "direction", label: "Direction", render: (t) => ui.dirBadge(t.direction) },
        { key: "entry", label: "Entry", num: true, render: (t) => SM.fmt(t.entry) },
        { key: "current_price", label: "Current", num: true, render: (t) => SM.fmt(t.current_price) },
        { key: "initial_stop", label: "Initial SL", num: true, render: (t) => `<span class="down">${SM.fmt(t.initial_stop)}</span>` },
        { key: "current_stop", label: "Current SL", num: true, render: (t) => `<b>${SM.fmt(t.current_stop)}</b>` },
        { key: "targets", label: "T1 / T2 / T3", sort: false, render: (t) => t.targets.map((v, i) => `<span class="${t.targets_hit[i] ? "up" : "muted"}" title="${t.targets_hit[i] ? "hit" : "open"}">${t.targets_hit[i] ? "✓" : ""}${SM.fmt(v, 0)}</span>`).join(" / ") },
        { key: "booked_qty", label: "Booked", num: true }, { key: "runner_qty", label: "Runner", num: true },
        { key: "remaining_qty", label: "Open qty", num: true },
        { key: "current_r", label: "Current R", num: true, render: (t) => `<b class="${SM.dir(t.current_r)}">${SM.isNum(t.current_r) ? SM.signed(t.current_r, 2) + "R" : "—"}</b>` },
        { key: "unrealized_pnl", label: "P&L", num: true, sortValue: (t) => t.net_pnl + t.unrealized_pnl, render: (t) => ui.money(t.net_pnl + t.unrealized_pnl) },
        { key: "last_confirmed_pivot", label: "Last HL/LH", render: (t) => t.last_confirmed_pivot ? `${esc(t.last_confirmed_pivot.label)} ${SM.fmt(t.last_confirmed_pivot.price)}` : '<span class="muted">none yet</span>' },
        { key: "trail", label: "Trail", sort: false, render: (t) => `${t.trail_history.length - 1} moves` },
      ] });
  };

  function tradeDetail(t) {
    return `<div class="grid g-2">
      <div><h3 class="section-title">Trailing-stop history</h3>${t.trail_history.map((h) => `<div style="display:flex;gap:10px;font-size:12.5px;padding:3px 0;border-bottom:1px dashed var(--border)">
        <span class="muted num" style="min-width:86px">${SM.date(h.time)}</span><span class="num">${h.old == null ? "—" : SM.fmt(h.old)} → <b>${SM.fmt(h.new)}</b></span><span class="muted">${esc(h.reason)}</span></div>`).join("")}</div>
      <div><h3 class="section-title">Fills</h3>${t.fills.map((f) => `<div style="display:flex;gap:10px;font-size:12.5px;padding:3px 0;border-bottom:1px dashed var(--border)">
        <span class="muted num" style="min-width:86px">${SM.date(f.time)}</span><b>${esc(f.side)}</b><span class="num">${f.qty} @ ${SM.fmt(f.price)}</span><span class="muted">${esc(f.reason)}</span></div>`).join("")}
        <h3 class="section-title" style="margin-top:12px">Decision snapshot</h3>
        <div class="muted" style="font-size:12.5px">Zone ${esc(t.snapshot.zone_pattern || "")} score ${SM.fmt(t.snapshot.zone_score, 0)} · confluence ${SM.fmt(t.snapshot.confluence, 0)} · ${esc(SM.title(t.snapshot.candlestick || "no pattern"))} · OI ${esc(t.snapshot.oi_state || "—")}</div></div></div>`;
  }

  // ------------------------------------------------------------------ Active trades
  SM.views.trades = {
    title: "Active Trades", icon: "briefcase", group: "Execution",
    async render(el) {
      const d = await SM.api.get("/api/trades");
      el.innerHTML = `<div class="view-head"><div><h1>Active trade management</h1><p>${esc(d.note)} Session started ${SM.date(d.session_start)}.</p></div></div>
        ${ui.card({ title: `Open positions <span class="badge b-solid-accent">${d.open.length}</span>`, sub: "click a row for trail history and fills", body: '<div id="tr-open"></div>', flush: true })}
        <div id="tr-props"></div>
        <div class="grid g-2">
          ${ui.card({ title: "Recently closed", body: '<div id="tr-closed"></div>', flush: true })}
          ${ui.card({ title: "Paper broker orders", sub: "via the safety gateway", body: '<div id="tr-orders"></div>', flush: true })}
        </div>`;
      SM.parts.tradesTable(el.querySelector("#tr-open"), d.open, false);
      renderProposals(el.querySelector("#tr-props"));
      ui.table(el.querySelector("#tr-closed"), { compact: true, rows: d.closed, maxHeight: 380, rowKey: (t) => t.trade_id, expand: tradeDetail, empty: ui.empty("No closed trades in this session"), columns: [
        { key: "symbol", label: "Symbol", render: (t) => `<span class="sym">${esc(t.symbol)}</span>` }, { key: "direction", label: "Dir", render: (t) => ui.dirBadge(t.direction) },
        { key: "entry_time", label: "Entry", render: (t) => SM.dateShort(t.entry_time) }, { key: "exit_time", label: "Exit", render: (t) => SM.dateShort(t.exit_time) },
        { key: "exit_reason", label: "Reason", render: (t) => esc(SM.title(t.exit_reason)) },
        { key: "r_multiple", label: "R", num: true, render: (t) => `<b class="${SM.dir(t.r_multiple)}">${SM.signed(t.r_multiple, 2)}R</b>` },
        { key: "net_pnl", label: "Net P&L", num: true, render: (t) => ui.money(t.net_pnl) },
      ] });
      ui.table(el.querySelector("#tr-orders"), { compact: true, rows: d.orders, maxHeight: 380, empty: ui.empty("No orders"), columns: [
        { key: "order_id", label: "Order" }, { key: "symbol", label: "Symbol", sortValue: (o) => o.request.symbol, render: (o) => esc(o.request.symbol) },
        { key: "side", label: "Side", sortValue: (o) => o.request.side, render: (o) => `<b class="${o.request.side === "BUY" ? "up" : "down"}">${esc(o.request.side)}</b>` },
        { key: "qty", label: "Qty", num: true, sortValue: (o) => o.request.quantity, render: (o) => SM.fmt(o.request.quantity, 0) },
        { key: "average_price", label: "Avg price", num: true, render: (o) => SM.fmt(o.average_price) }, { key: "status", label: "Status", render: (o) => ui.status(o.status) },
      ] });
    },
  };

  async function renderProposals(box) {
    let d;
    try { d = await SM.api.get("/api/proposals", {}, { fresh: true }); } catch (err) { box.innerHTML = ui.card({ title: "Order proposals", body: ui.error(err) }); return; }
    box.innerHTML = ui.card({ title: "Order proposals" + ui.tip("MANUAL: analysis only. SEMI_AUTO: the system proposes, you confirm. PAPER: READY setups are sent automatically. Change the mode in Settings."),
      actions: `${ui.badge("Mode: " + SM.title(d.mode), "b-accent")}`,
      body: `<p class="muted" style="margin:0 0 8px">${esc(d.help)}</p><div id="pr-now"></div>
        <details class="more" style="margin-top:10px"><summary>Proposal history (${d.history.length})</summary><div id="pr-hist" style="margin-top:8px"></div></details>` });
    ui.table(box.querySelector("#pr-now"), { compact: true, rows: d.items, rowKey: (p) => p.id, empty: ui.empty("No proposals right now", "Only READY or WAIT setups on the latest bar become proposals."), columns: [
      { key: "symbol", label: "Symbol", render: (p) => `<span class="sym">${esc(p.symbol)}</span>` }, { key: "direction", label: "Dir", render: (p) => ui.dirBadge(p.direction) },
      { key: "entry", label: "Entry", num: true, render: (p) => SM.fmt(p.entry) }, { key: "stop", label: "SL", num: true, render: (p) => SM.fmt(p.stop) },
      { key: "t2", label: "T2", num: true, render: (p) => SM.fmt(p.t2) }, { key: "score", label: "Score", num: true, render: (p) => ui.scoreChip(p.score, SM.state.meta.min_conf) },
      { key: "status", label: "Status", cls: "wrap", render: (p) => ui.status(p.status) + (p.order_id ? ` <span class="muted">${esc(p.order_id)}</span>` : "") },
      { key: "act", label: "Action", sort: false, render: (p) => p.confirmable
        ? `<button class="btn btn-primary" type="button" data-pa="confirm" data-id="${esc(p.id)}">Confirm</button> <button class="btn" type="button" data-pa="reject" data-id="${esc(p.id)}">Reject</button>`
        : '<span class="muted">—</span>' },
    ] });
    ui.table(box.querySelector("#pr-hist"), { compact: true, rows: d.history, empty: ui.empty("No proposals yet"), columns: [
      { key: "id", label: "Id" }, { key: "symbol", label: "Symbol" }, { key: "direction", label: "Dir", render: (p) => ui.dirBadge(p.direction) },
      { key: "qty", label: "Qty", num: true }, { key: "status", label: "Status", render: (p) => ui.status(p.status) }, { key: "order_id", label: "Order" },
    ] });
    box.querySelectorAll("[data-pa]").forEach((b) => b.addEventListener("click", async () => {
      b.disabled = true;
      try { await SM.api.post(`/api/proposals/${b.dataset.pa}`, { id: b.dataset.id }); SM.toast(b.dataset.pa === "confirm" ? "Order sent to the paper broker" : "Proposal rejected"); renderProposals(box); }
      catch (err) { SM.toast(err.message); b.disabled = false; }
    }));
  }

  // ------------------------------------------------------------------ Risk
  SM.views.risk = {
    title: "Risk", icon: "shield", group: "Execution",
    async render(el) {
      const d = await SM.api.get("/api/risk");
      const a = d.account, x = d.exposure, L = d.limits;
      const riskFrac = a.equity ? a.open_risk / (L.max_portfolio_risk * a.equity) : 0;
      el.innerHTML = `<div class="view-head"><div><h1>Risk dashboard</h1><p>The risk engine sits after the signal engine and can veto a technically valid setup.</p></div></div>
        <div class="kpi-row">
          ${ui.kpi({ label: "Capital", value: SM.inr(a.capital), cls: "compact" })}${ui.kpi({ label: "Equity", value: SM.inr(a.equity), cls: "compact" })}
          ${ui.kpi({ label: "Cash", value: SM.inr(a.cash), cls: "compact" })}${ui.kpi({ label: "Invested", value: SM.inr(a.invested), cls: "compact" })}
          ${ui.kpi({ label: "Open P&L", value: ui.money(a.open_pnl), cls: "compact" })}${ui.kpi({ label: "Realized P&L", value: ui.money(a.realized_pnl), cls: "compact" })}
        </div>
        <div class="grid g-3">
          ${ui.card({ title: "Open risk", body: `<div class="big-score"><span class="n" style="font-size:40px">${SM.fmt(a.open_risk_pct, 2)}%</span><span class="d">of equity</span></div>
            <div style="margin:10px 0 6px">${ui.bar(riskFrac, riskFrac > 0.8 ? "down" : riskFrac > 0.5 ? "warn" : "up")}</div>
            <div class="muted" style="font-size:12.5px">${SM.inr(a.open_risk)} at risk · cap ${SM.pct(L.max_portfolio_risk, 1)} (${SM.inr(L.max_portfolio_risk * a.equity)})</div>` })}
          ${ui.card({ title: "Exposure", body: ui.kv([["Open positions", `${a.open_positions} / ${L.max_positions}`], ["Long exposure", `${SM.inr(x.long_exposure)} <span class="muted">${SM.pct(x.long_pct, 1)}</span>`],
            ["Short exposure", `${SM.inr(x.short_exposure)} <span class="muted">${SM.pct(x.short_pct, 1)}</span>`], ["Gross", SM.inr(x.gross_exposure)], ["Net", SM.inr(x.net_exposure)]]) })}
          ${ui.card({ title: "Limits", body: ui.kv([["Risk per trade", SM.pct(L.risk_per_trade, 1)], ["Max position size", SM.pct(L.max_position_pct, 0)],
            ["Max portfolio risk", SM.pct(L.max_portfolio_risk, 1)], ["Max sector exposure", SM.pct(L.max_sector_exposure, 0)],
            ["Max positions / sector", String(L.max_positions_per_sector)], ["Max daily loss", SM.pct(L.max_daily_loss, 1)]]) })}
        </div>
        <div class="grid g-3">
          ${ui.card({ title: "Sector exposure", body: x.sectors.length ? `<div class="brk" style="grid-template-columns:minmax(90px,1fr) 2fr auto">${x.sectors.map((s) => `<span>${esc(s.sector)}</span>${ui.bar(s.pct / L.max_sector_exposure, s.pct > L.max_sector_exposure ? "down" : "")}<span class="val">${SM.pct(s.pct, 1)}</span>`).join("")}</div>` : ui.empty("No exposure") })}
          ${ui.card({ title: "Symbol concentration", body: x.symbols.length ? `<div class="brk" style="grid-template-columns:minmax(90px,1fr) 2fr auto">${x.symbols.map((s) => `<span>${esc(s.symbol)}</span>${ui.bar(s.pct / L.max_position_pct)}<span class="val">${SM.pct(s.pct, 1)}</span>`).join("")}</div>` : ui.empty("No positions") })}
          ${ui.card({ title: "Correlation warnings", body: d.correlation.length ? ui.checklist(d.correlation.map((c) => ({ ok: false, text: c.detail }))) : ui.empty("No correlated pairs above threshold", "", "check") })}
        </div>
        <div class="grid g-2">
          ${ui.card({ title: "Equity & open risk", sub: "paper session", body: '<div id="rk-eq"></div>' })}
          ${ui.card({ title: "Setups vetoed by risk", body: '<div id="rk-rej"></div>', flush: true })}
        </div>`;
      SM.charts.line(el.querySelector("#rk-eq"), { height: 220, xFmt: SM.dateShort, yFmt: (v) => SM.compact(v), label: "Equity",
        series: [{ name: "Equity", color: "var(--accent)", area: true, data: d.equity.map((p) => ({ x: p.t, y: p.equity })) }] });
      ui.table(el.querySelector("#rk-rej"), { compact: true, rows: d.risk_rejections, maxHeight: 300, empty: ui.empty("No risk vetoes in this session", "", "check"), columns: [
        { key: "time", label: "Date", render: (r) => SM.dateShort(r.time) }, { key: "symbol", label: "Symbol", render: (r) => `<span class="sym">${esc(r.symbol)}</span>` },
        { key: "direction", label: "Dir", render: (r) => ui.dirBadge(r.direction) }, { key: "reason", label: "Reason", cls: "wrap", render: (r) => esc(r.reason.replace(/^RISK: /, "")) },
      ] });
    },
  };
})();
