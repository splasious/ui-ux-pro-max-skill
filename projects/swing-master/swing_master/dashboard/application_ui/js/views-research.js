/* Swing Master -- research screens: backtest lab, walk-forward, journal, rejected signals, reports. */
(function () {
  "use strict";
  const SM = window.SM, ui = SM.ui, esc = SM.esc;
  SM.parts = SM.parts || {};

  const COMP_LABEL = { structure: "Structure", zones: "Zones", volume_profile: "Volume profile", candlestick: "Candlestick", commercial: "Commercial",
    institutional: "Institutional", retail: "Retail", oi: "Futures OI", pcr: "PCR", bos: "BOS / CHoCH" };

  function kpis(m) {
    const k = (label, value, sub = "") => ui.kpi({ label, value, sub, cls: "compact" });
    return `<div class="kpi-row">
      ${k("Net P&L", ui.money(m.net_pnl), SM.signedPct(m.net_pnl_pct, 2, true))}
      ${k("CAGR", `<span class="${SM.dir(m.cagr)}">${SM.isNum(m.cagr) ? SM.signedPct(m.cagr, 2, true) : "—"}</span>`)}
      ${k("Max drawdown", `<span class="down">${SM.pct(m.max_drawdown, 2)}</span>`, SM.inr(m.max_drawdown_amount))}
      ${k("Win rate", SM.pct(m.win_rate, 1), `${m.total_trades} trades`)}
      ${k("Profit factor", SM.fmt(m.profit_factor, 2))}
      ${k("Expectancy", ui.money(m.expectancy), `${SM.signed(m.expectancy_r, 3)}R per trade`)}
      ${k("Average R", `<span class="${SM.dir(m.average_r)}">${SM.signed(m.average_r, 3)}R</span>`, `Median ${SM.signed(m.median_r, 2)}R`)}
      ${k("Avg holding", SM.isNum(m.avg_holding_bars) ? SM.fmt(m.avg_holding_bars, 1) + " bars" : "—")}
      ${k("Sharpe", SM.fmt(m.sharpe, 2), `Sortino ${SM.fmt(m.sortino, 2)}`)}
      ${k("Recovery factor", SM.fmt(m.recovery_factor, 2), `Costs ${SM.inr(m.total_costs)}`)}
    </div>`;
  }
  SM.parts.kpis = kpis;

  // ------------------------------------------------------------------ Backtest
  SM.views.backtest = {
    title: "Backtest", icon: "flask", group: "Research",
    async render(el) {
      const d = await SM.api.get("/api/backtest");
      el.innerHTML = `<div class="view-head"><div><h1>Backtest lab</h1><p>${esc(d.label)} · ${SM.date(d.start)} → ${SM.date(d.end)} · ${d.signals} decisions, ${d.rejected} rejected. Entries fill on the next open; a stop and a target inside the same bar count as the stop.</p></div></div>
        ${d.data_note ? ui.notice(esc(d.data_note)) : ""}
        ${ui.card({ title: "Components", sub: "switch layers off to test whether each one adds value", actions: `<button class="btn btn-primary" id="bt-run" type="button">${SM.icon("play")} Run backtest</button>`,
          body: `<div class="toolbar">${d.components.map((c) => `<label class="switch"><input type="checkbox" data-comp="${c}" ${d.enabled.includes(c) ? "checked" : ""}><span class="track"></span>${COMP_LABEL[c] || c}</label>`).join("")}</div>
            <div id="bt-msg" class="muted" style="font-size:12px;margin-top:8px"></div>` })}
        <div id="bt-results"></div>
        ${ui.card({ title: "Ablation ladder", sub: "does each layer earn its place?", actions: `<button class="btn" id="bt-abl" type="button">${SM.icon("layers")} Compare layers</button>`, body: '<div id="bt-ablation" class="muted">Runs six backtests: Structure only → + Zones → + Volume → + Price action → + Positioning → + Derivatives.</div>' })}`;
      const results = el.querySelector("#bt-results");
      renderResults(results, d);
      el.querySelector("#bt-run").addEventListener("click", async () => {
        const comps = [...el.querySelectorAll("[data-comp]")].filter((c) => c.checked).map((c) => c.dataset.comp);
        const msg = el.querySelector("#bt-msg");
        msg.textContent = "Running…";
        try {
          const r = await SM.api.post("/api/backtest/run", { components: comps });
          renderResults(results, r);
          msg.textContent = `Custom run with ${comps.length} components.`;
        } catch (err) { msg.textContent = err.message; }
      });
      el.querySelector("#bt-abl").addEventListener("click", () => loadAblation(el.querySelector("#bt-ablation")));
      if (SM.api.isStatic()) loadAblation(el.querySelector("#bt-ablation"));
    },
  };

  async function loadAblation(box) {
    await ui.load(box, async () => {
      const d = await SM.api.get("/api/backtest/ablation");
      box.innerHTML = '<div id="ab-chart"></div><div id="ab-t" style="margin-top:8px"></div>';
      SM.charts.bars(box.querySelector("#ab-chart"), { height: 170, yFmt: (v) => SM.fmt(v, 2) + "R", label: "Average R by layer set",
        items: d.rows.map((r) => ({ label: r.label, value: r.metrics.average_r })) });
      ui.table(box.querySelector("#ab-t"), { compact: true, rows: d.rows, rowKey: (r) => r.label, columns: [
        { key: "label", label: "Layers", render: (r) => `<b>${esc(r.label)}</b>` },
        { key: "t", label: "Trades", num: true, sortValue: (r) => r.metrics.total_trades, render: (r) => r.metrics.total_trades },
        { key: "w", label: "Win rate", num: true, sortValue: (r) => r.metrics.win_rate, render: (r) => SM.pct(r.metrics.win_rate, 1) },
        { key: "r", label: "Avg R", num: true, sortValue: (r) => r.metrics.average_r, render: (r) => `<span class="${SM.dir(r.metrics.average_r)}">${SM.signed(r.metrics.average_r, 3)}</span>` },
        { key: "pf", label: "Profit factor", num: true, sortValue: (r) => r.metrics.profit_factor, render: (r) => SM.fmt(r.metrics.profit_factor, 2) },
        { key: "dd", label: "Max DD", num: true, sortValue: (r) => r.metrics.max_drawdown, render: (r) => `<span class="down">${SM.pct(r.metrics.max_drawdown, 1)}</span>` },
        { key: "n", label: "Net P&L", num: true, sortValue: (r) => r.metrics.net_pnl, render: (r) => ui.money(r.metrics.net_pnl) },
      ] });
    });
  }

  function renderResults(el, d) {
    const c = d.charts;
    el.innerHTML = `${kpis(d.metrics)}
      <div class="grid g-2">
        ${ui.card({ title: "Equity curve", body: '<div id="bt-eq"></div>' })}
        ${ui.card({ title: "Drawdown", body: '<div id="bt-dd"></div>' })}
      </div>
      ${ui.card({ title: "Monthly returns", body: '<div id="bt-heat"></div>' })}
      <div class="grid g-3">
        ${ui.card({ title: "R distribution", body: '<div id="bt-r"></div>' })}
        ${ui.card({ title: "Holding period", sub: "bars", body: '<div id="bt-h"></div>' })}
        ${ui.card({ title: "Rolling performance", sub: `${c.rolling_window}-trade window`, body: '<div id="bt-roll"></div>' })}
      </div>
      <div class="grid g-2">
        ${ui.card({ title: "Exit reasons", body: `<div class="brk" style="grid-template-columns:minmax(120px,1fr) 2fr auto">${Object.entries(d.metrics.exit_reasons || {}).map(([k, v]) => `<span>${esc(SM.title(k))}</span>${ui.bar(v / Math.max(1, d.metrics.total_trades))}<span class="val">${v}</span>`).join("")}</div>` })}
        ${ui.card({ title: "Factor attribution", actions: `<select class="select" id="bt-dim" aria-label="Attribution dimension">${(d.attribution || []).map((a, i) => `<option value="${i}">${esc(a.dimension)}</option>`).join("")}</select>`, body: '<div id="bt-attr"></div>', flush: true })}
      </div>
      ${ui.card({ title: "Trades", sub: "click for the full journal entry", body: '<div id="bt-trades"></div>', flush: true })}`;
    SM.charts.line(el.querySelector("#bt-eq"), { height: 230, xFmt: SM.monthYear, tipX: SM.date, yFmt: (v) => SM.compact(v), label: "Equity curve",
      series: [{ name: "Equity", color: "var(--accent)", area: true, data: c.equity.map((p) => ({ x: p.t, y: p.equity })) }] });
    SM.charts.line(el.querySelector("#bt-dd"), { height: 230, xFmt: SM.monthYear, tipX: SM.date, yFmt: (v) => SM.fmt(v * 100, 1) + "%", zero: true, yMax: 0, label: "Drawdown",
      series: [{ name: "Drawdown", color: "var(--down)", area: true, areaOpacity: 0.25, data: c.equity.map((p) => ({ x: p.t, y: p.dd })) }] });
    SM.charts.heatmap(el.querySelector("#bt-heat"), c.monthly);
    SM.charts.bars(el.querySelector("#bt-r"), { height: 190, rotate: true, label: "R distribution", items: c.r_distribution.map((b) => ({ label: b.bucket, value: b.count,
      color: b.bucket.startsWith("<") || b.bucket.startsWith("-") ? "var(--down)" : "var(--up)" })) });
    SM.charts.bars(el.querySelector("#bt-h"), { height: 190, label: "Holding period", items: c.holding.map((b) => ({ label: b.bucket, value: b.count, color: "var(--accent)" })) });
    SM.charts.line(el.querySelector("#bt-roll"), { height: 190, xFmt: SM.monthYear, yFmt: (v) => SM.fmt(v, 2), zero: true, label: "Rolling expectancy",
      series: [{ name: "Expectancy (R)", color: "var(--accent)", data: c.rolling.map((p) => ({ x: p.t, y: p.expectancy_r })) },
        { name: "Win rate", color: "var(--warn)", dash: "4 3", data: c.rolling.map((p) => ({ x: p.t, y: p.win_rate })) }] });
    const attr = el.querySelector("#bt-attr"), dim = el.querySelector("#bt-dim");
    const drawAttr = () => {
      const a = (d.attribution || [])[+dim.value];
      if (!a) { attr.innerHTML = ui.empty("No attribution"); return; }
      ui.table(attr, { compact: true, rows: a.rows, rowKey: (r) => r.bucket, columns: [
        { key: "bucket", label: a.dimension, render: (r) => `<b>${esc(r.bucket)}</b>` }, { key: "trades", label: "Trades", num: true },
        { key: "win_rate", label: "Win rate", num: true, render: (r) => SM.pct(r.win_rate, 1) },
        { key: "avg_r", label: "Avg R", num: true, render: (r) => `<span class="${SM.dir(r.avg_r)}">${SM.signed(r.avg_r, 3)}</span>` },
        { key: "profit_factor", label: "PF", num: true, render: (r) => SM.fmt(r.profit_factor, 2) },
        { key: "net_pnl", label: "Net P&L", num: true, render: (r) => ui.money(r.net_pnl) },
      ] });
    };
    if (dim) { dim.addEventListener("change", drawAttr); drawAttr(); }
    SM.parts.journalTable(el.querySelector("#bt-trades"), d.trades.map(tradeToEntry));
  }

  function tradeToEntry(t) {
    const s = t.snapshot || {};
    return { trade_id: t.trade_id, symbol: t.symbol, direction: t.direction, entry_time: t.entry_time, exit_time: t.exit_time,
      structure: s.structure, zone_pattern: s.zone_pattern, zone_score: s.zone_score, confluence: s.confluence, candlestick: s.candlestick,
      entry: t.entry, stop: t.initial_stop, net_pnl: t.net_pnl, r_multiple: t.r_multiple, holding_bars: t.holding_bars, exit_reason: t.exit_reason,
      oi_state: s.oi_state, status: t.status };
  }

  // ------------------------------------------------------------------ Journal
  SM.parts.journalTable = function (el, entries) {
    ui.table(el, { rows: entries, rowKey: (e) => e.trade_id, maxHeight: 520, onRow: (e) => openJournal(e.trade_id), empty: ui.empty("No trades"), columns: [
      { key: "trade_id", label: "Trade" }, { key: "symbol", label: "Symbol", render: (e) => `<span class="sym">${esc(e.symbol)}</span>` },
      { key: "direction", label: "Dir", render: (e) => ui.dirBadge(e.direction) },
      { key: "entry_time", label: "Entry", render: (e) => SM.date(e.entry_time) }, { key: "exit_time", label: "Exit", render: (e) => (e.exit_time ? SM.date(e.exit_time) : ui.status("OPEN")) },
      { key: "structure", label: "Structure", render: (e) => ui.trendBadge(e.structure) },
      { key: "zone_pattern", label: "Zone" }, { key: "zone_score", label: "Zone sc.", num: true, render: (e) => SM.fmt(e.zone_score, 0) },
      { key: "confluence", label: "Confl.", num: true, render: (e) => SM.fmt(e.confluence, 0) },
      { key: "candlestick", label: "Pattern", render: (e) => esc(SM.title(e.candlestick || "—")) },
      { key: "oi_state", label: "OI", render: (e) => esc(SM.title(e.oi_state || "—")) },
      { key: "entry", label: "Entry px", num: true, render: (e) => SM.fmt(e.entry) }, { key: "stop", label: "SL", num: true, render: (e) => SM.fmt(e.stop) },
      { key: "holding_bars", label: "Hold", num: true }, { key: "exit_reason", label: "Exit reason", render: (e) => esc(SM.title(e.exit_reason || "—")) },
      { key: "r_multiple", label: "R", num: true, render: (e) => `<b class="${SM.dir(e.r_multiple)}">${SM.signed(e.r_multiple, 2)}</b>` },
      { key: "net_pnl", label: "Net P&L", num: true, render: (e) => ui.money(e.net_pnl) },
    ] });
  };

  async function openJournal(id) {
    ui.drawer(`Trade ${esc(id)}`, ui.loading(), async (body) => {
      try {
        const d = await SM.api.get(`/api/journal/${encodeURIComponent(id)}`);
        const e = d.entry;
        body.innerHTML = `
          <div class="toolbar">${ui.dirBadge(e.direction)} <b style="font-size:16px">${esc(e.symbol)}</b> ${ui.status(e.status)} <span class="${SM.dir(e.r_multiple)}" style="font-weight:700">${SM.signed(e.r_multiple, 2)}R · ${SM.signedInr(e.net_pnl)}</span></div>
          <div id="jd-chart"></div>
          <div class="grid g-2">
            <div>${ui.kv([["Signal", SM.date(e.signal_time)], ["Entry", `${SM.date(e.entry_time)} @ ${SM.fmt(e.entry)}`], ["Exit", e.exit_time ? `${SM.date(e.exit_time)} · ${esc(SM.title(e.exit_reason))}` : "open"],
              ["Pivot / confirmed", `${SM.date(e.pivot_time)} / ${SM.date(e.pivot_confirmation_time)}`], ["Structure", `${esc(e.structure || "—")} · ${esc(e.structure_event || "")}`],
              ["Zone", `${esc(e.zone_type || "")} ${esc(e.zone_pattern || "")} · score ${SM.fmt(e.zone_score, 0)}`], ["POC / VAH / VAL", `${SM.fmt(e.poc, 0)} / ${SM.fmt(e.vah, 0)} / ${SM.fmt(e.val, 0)}`],
              ["Commercial / Inst. / Retail", `${esc(e.commercial)} / ${esc(e.institutional)} / ${esc(e.retail)}`], ["OI / PCR / ΔOI PCR", `${esc(e.oi_state)} / ${SM.fmt(e.pcr, 2)} / ${SM.fmt(e.change_oi_pcr, 2)}`],
              ["Candlestick", esc(SM.title(e.candlestick || "—"))], ["Confluence", SM.fmt(e.confluence, 1)]])}</div>
            <div>${ui.kv([["Entry / SL", `${SM.fmt(e.entry)} / ${SM.fmt(e.stop)}`], ["T1 / T2 / T3", `${SM.fmt(e.t1)} / ${SM.fmt(e.t2)} / ${SM.fmt(e.t3)}`], ["Quantity", SM.fmt(e.quantity, 0)],
              ["Gross P&L", ui.money(e.gross_pnl)], ["Costs", SM.inr(e.costs)], ["Net P&L", ui.money(e.net_pnl)], ["R multiple", SM.signed(e.r_multiple, 2)],
              ["Holding", `${e.holding_bars} bars`], ["MFE / MAE", `${SM.signed(e.mfe_r, 2)}R / ${SM.signed(e.mae_r, 2)}R`], ["Trail changes", String(e.trail_changes)]])}</div>
          </div>
          <div><h3 class="section-title">Partial exits</h3>${e.partial_exits.length ? e.partial_exits.map((f) => `<div class="muted">${SM.date(f.time)} · ${esc(f.reason)} · ${f.qty} @ ${SM.fmt(f.price)}</div>`).join("") : '<span class="muted">none</span>'}</div>
          <div><h3 class="section-title">Trailing-stop history</h3>${e.trail_history.map((h) => `<div class="muted">${SM.date(h.time)} · ${h.old == null ? "" : SM.fmt(h.old) + " → "}${SM.fmt(h.new)} · ${esc(h.reason)}</div>`).join("")}</div>`;
        const c = d.chart;
        const tr = { entry: c.levels.entry, current_stop: c.levels.stop, initial_stop: c.levels.stop, targets: [c.levels.t1, c.levels.t2, c.levels.t3],
          targets_hit: [false, false, false], trail_history: c.trail };
        const markers = [{ bar: c.entry_bar, kind: "entry", direction: e.direction, price: e.entry, trade_id: id }];
        if (c.exit_bar != null) markers.push({ bar: c.exit_bar, kind: "exit", direction: e.direction, price: e.exit_price || e.entry, reason: e.exit_reason, trade_id: id });
        new SM.charts.CandleChart(body.querySelector("#jd-chart"), { symbol: e.symbol, timeframe: "1D", bars: c.bars, offset: c.offset, pivots: [], zones: [], events: [], profile: null, trade: tr, markers },
          { height: 300, visible: c.bars.length, volume: false });
      } catch (err) { body.innerHTML = ui.error(err); }
    });
  }
  SM.parts.openJournal = openJournal;

  SM.views.journal = {
    title: "Journal", icon: "book", group: "Research",
    async render(el) {
      const st = { source: "backtest" };
      el.innerHTML = `<div class="view-head"><div><h1>Trade journal</h1><p>Every trade stores its full decision context, partial exits and trail history. Click a trade for its entry/exit chart snapshot.</p></div>
        <div class="actions">${ui.seg("js", [["backtest", "Backtest"], ["paper", "Paper"]], "backtest", true)}
        ${SM.api.isStatic() ? "" : `<a class="btn" href="/api/journal.csv">${SM.icon("download")} Export CSV</a>`}</div></div><div id="jr"></div>`;
      const body = el.querySelector("#jr");
      const draw = () => ui.load(body, async () => {
        const d = await SM.api.get("/api/journal", { source: st.source });
        body.innerHTML = ui.card({ title: `${d.entries.length} trades`, body: '<div id="jr-t"></div>', flush: true });
        SM.parts.journalTable(body.querySelector("#jr-t"), d.entries);
      });
      ui.bindSeg(el, "js", (v) => { st.source = v; draw(); });
      draw();
    },
  };

  // ------------------------------------------------------------------ Walk-forward
  SM.views.walkforward = {
    title: "Walk-Forward", icon: "repeat", group: "Research",
    async render(el) {
      el.innerHTML = `<div class="view-head"><div><h1>Walk-forward lab</h1><p>Parameters are chosen on the train and validate windows only. The test window is touched once, after selection.</p></div></div>
        <div class="protocol"><span>TRAIN 18M</span><span class="arrow">→</span><span>VALIDATE 6M</span><span class="arrow">→</span><span>OUT-OF-SAMPLE TEST 6M</span><span class="arrow">→</span><span>ROLL FORWARD 6M</span></div>
        <div id="wf"></div>`;
      const box = el.querySelector("#wf");
      const poll = async () => {
        let d;
        try { d = await SM.api.get("/api/walkforward", {}, { fresh: true, nocache: true }); } catch (err) { box.innerHTML = ui.error(err); return; }
        if (d.state !== "done") {
          box.innerHTML = ui.card({ title: "Running walk-forward", body: `<div class="loading" role="status">Optimising each fold (${esc(d.state)})…</div>` });
          if (SM.route() === "walkforward" && String(d.state).startsWith("running")) setTimeout(poll, 2500);
          return;
        }
        renderWF(box, d);
      };
      poll();
    },
  };

  function renderWF(box, d) {
    const s = d.summary;
    const first = SM.parseT(d.folds[0].train.start), last = SM.parseT(d.folds[d.folds.length - 1].test.end);
    const span = last - first;
    const pos = (iso) => ((SM.parseT(iso) - first) / span) * 100;
    box.innerHTML = `
      <div class="grid g-4">
        ${ui.kpi({ label: "In-sample avg R", value: `<span class="${SM.dir(s.in_sample_avg_r)}">${SM.signed(s.in_sample_avg_r, 3)}</span>`, sub: "train windows (optimised)" })}
        ${ui.kpi({ label: "Out-of-sample avg R", value: `<span class="${SM.dir(s.out_of_sample_avg_r)}">${SM.signed(s.out_of_sample_avg_r, 3)}</span>`, sub: `degradation ${SM.signed(s.degradation, 3)}R` })}
        ${ui.kpi({ label: "OOS return", value: `<span class="${SM.dir(s.oos_return)}">${SM.signedPct(s.oos_return, 2, true)}</span>`, sub: `max DD ${SM.pct(s.oos_max_drawdown, 1)}` })}
        ${ui.kpi({ label: "OOS trades", value: String(s.oos_trades), sub: `win rate ${SM.pct(s.oos_win_rate, 1)} · ${SM.signed(s.oos_trade_avg_r, 3)}R/trade` })}
      </div>
      ${ui.card({ title: "Fold timeline", body: `<div style="display:grid;gap:6px">${d.folds.map((f) => `<div class="fold-row"><span class="muted">Fold ${f.fold}</span><div class="fold-track">
          <i class="tr" style="left:${pos(f.train.start)}%;width:${pos(f.train.end) - pos(f.train.start)}%" title="Train ${f.train.start} → ${f.train.end}"></i>
          <i class="va" style="left:${pos(f.validate.start)}%;width:${pos(f.validate.end) - pos(f.validate.start)}%" title="Validate ${f.validate.start} → ${f.validate.end}"></i>
          <i class="te" style="left:${pos(f.test.start)}%;width:${pos(f.test.end) - pos(f.test.start)}%" title="Test ${f.test.start} → ${f.test.end}"></i></div></div>`).join("")}</div>`,
        note: '<span class="chart-legend" style="padding:0"><span><i style="background:var(--profile-va)"></i>Train</span><span><i style="background:var(--warn)"></i>Validate</span><span><i style="background:var(--up)"></i>Out-of-sample test</span></span>' })}
      <div class="grid g-main">
        ${ui.card({ title: "In-sample vs out-of-sample by fold", body: '<div id="wf-t"></div>', flush: true, note: esc(d.protocol) })}
        ${ui.card({ title: "Chained OOS equity", body: '<div id="wf-eq"></div>' })}
      </div>`;
    ui.table(box.querySelector("#wf-t"), { rows: d.folds, rowKey: (f) => f.fold, expand: (f) => `<div class="muted" style="margin-bottom:6px">Grid on train (${f.grid.length} combinations):</div>
        <div class="table-wrap"><table class="table compact"><thead><tr>${d.grid_keys.map((k) => `<th>${esc(k)}</th>`).join("")}<th class="num">Objective</th><th class="num">Trades</th><th class="num">Avg R</th></tr></thead>
        <tbody>${f.grid.map((g) => `<tr>${d.grid_keys.map((k) => `<td>${g.params[k]}</td>`).join("")}<td class="num">${SM.fmt(g.objective, 3)}</td><td class="num">${g.trades}</td><td class="num">${SM.signed(g.avg_r, 3)}</td></tr>`).join("")}</tbody></table></div>`,
      columns: [
        { key: "fold", label: "Fold", num: true }, { key: "test", label: "Test window", render: (f) => `${SM.monthYear(f.test.start)} → ${SM.monthYear(f.test.end)}` },
        { key: "params", label: "Chosen parameters", sort: false, render: (f) => Object.entries(f.params).map(([k, v]) => `${esc(k.replace("MIN_", "").replace("_SCORE", "").toLowerCase())} ${v}`).join(" · ") },
        { key: "is", label: "IS avg R", num: true, sortValue: (f) => f.train_metrics.average_r, render: (f) => SM.signed(f.train_metrics.average_r, 3) },
        { key: "va", label: "Val avg R", num: true, sortValue: (f) => f.validate_metrics.average_r, render: (f) => SM.signed(f.validate_metrics.average_r, 3) },
        { key: "oos", label: "OOS avg R", num: true, sortValue: (f) => f.test_metrics.average_r, render: (f) => `<b class="${SM.dir(f.test_metrics.average_r)}">${SM.signed(f.test_metrics.average_r, 3)}</b>` },
        { key: "n", label: "OOS trades", num: true, sortValue: (f) => f.test_metrics.total_trades, render: (f) => f.test_metrics.total_trades },
        { key: "pnl", label: "OOS P&L", num: true, sortValue: (f) => f.test_metrics.net_pnl, render: (f) => ui.money(f.test_metrics.net_pnl) },
      ] });
    SM.charts.line(box.querySelector("#wf-eq"), { height: 260, xFmt: SM.monthYear, tipX: SM.date, yFmt: (v) => SM.compact(v), label: "Chained out-of-sample equity",
      series: [{ name: "OOS equity", color: "var(--up)", area: true, data: d.oos_equity.map((p) => ({ x: p.time.slice(0, 10), y: p.equity })) }] });
  }

  // ------------------------------------------------------------------ Rejected signals
  SM.views.rejected = {
    title: "Rejected Signals", icon: "xcircle", group: "Research",
    async render(el) {
      const d = await SM.api.get("/api/rejected", { limit: 300 });
      const reasons = Object.keys(d.counts);
      el.innerHTML = `<div class="view-head"><div><h1>Rejected signal log</h1><p>${SM.fmt(d.total, 0)} setup moments were rejected over the backtest. Each one keeps its full pass/fail path, score and minimum. Rejections are research data.</p></div></div>
        ${ui.card({ title: "Why setups are rejected", body: '<div id="rj-chart"></div>' })}
        ${ui.card({ title: "Latest rejections", sub: "expand a row for the rule-by-rule path", actions: `<select class="select" id="rj-r" aria-label="Filter by reason"><option value="">All reasons</option>${reasons.map((r) => `<option>${esc(r)}</option>`).join("")}</select>
          <input class="input" id="rj-q" type="search" placeholder="Symbol" aria-label="Filter by symbol">`, body: '<div id="rj-t"></div>', flush: true })}`;
      SM.charts.bars(el.querySelector("#rj-chart"), { height: 200, rotate: true, padL: 50, label: "Rejections by first failing rule",
        items: reasons.map((r) => ({ label: r.length > 22 ? r.slice(0, 21) + "…" : r, value: d.counts[r], color: r.startsWith("RISK") ? "var(--warn)" : "var(--down)" })) });
      const t = ui.table(el.querySelector("#rj-t"), { rows: d.rows, rowKey: (r) => r.eval_id + r.decided_at, maxHeight: 620, expand: rejectDetail, columns: [
        { key: "time", label: "Date", render: (r) => SM.date(r.time) }, { key: "symbol", label: "Symbol", render: (r) => `<span class="sym">${esc(r.symbol)}</span>` },
        { key: "direction", label: "Dir", render: (r) => ui.dirBadge(r.direction) }, { key: "trigger", label: "Trigger" },
        { key: "score", label: "Score", num: true, render: (r) => `${ui.scoreChip(r.score, r.min_score)} <span class="muted">/ ${r.min_score}</span>` },
        { key: "zone_score", label: "Zone", num: true, render: (r) => `${ui.scoreChip(r.zone_score, r.min_zone_score)} <span class="muted">/ ${r.min_zone_score}</span>` },
        { key: "coverage", label: "Data", num: true, render: (r) => SM.pct(r.coverage, 0) },
        { key: "reason", label: "Rejection reason", cls: "wrap", render: (r) => esc(r.reason) },
      ] });
      const apply = () => {
        const q = el.querySelector("#rj-q").value.trim().toUpperCase(), rr = el.querySelector("#rj-r").value;
        t.setRows(d.rows.filter((r) => (!q || r.symbol.includes(q)) && (!rr || (r.reason || "").startsWith(rr))));
      };
      el.querySelector("#rj-q").addEventListener("input", SM.debounce(apply, 150));
      el.querySelector("#rj-r").addEventListener("change", apply);
    },
  };
  function rejectDetail(r) {
    return `<div class="grid g-2"><div><h3 class="section-title">Rules</h3>${ui.checklist(r.rules.map((x) => ({ ok: x.passed, text: `${x.rule}: ${x.detail}` })).concat(
      (r.risk_checks || []).map((c) => ({ ok: c.passed, text: `Risk · ${c.rule}: ${c.detail}` }))))}</div>
      <div><h3 class="section-title">Factors</h3><div class="brk">${r.factors.map((f) => `<span>${esc(f.name)}</span>${ui.bar(f.fraction, f.fraction == null ? "" : f.fraction >= 0.5 ? "up" : "warn")}<span class="val">${f.points == null ? '<span class="muted">n/a</span>' : SM.fmt(f.points, 1) + "/" + f.weight}</span>`).join("")}</div>
      <div class="muted" style="margin-top:8px;font-size:12px">${esc(r.zone.type || "")} ${esc(r.zone.pattern || "")} ${SM.fmt(r.zone.proximal)}–${SM.fmt(r.zone.distal)} · ${esc(r.zone.status || "")} · trend ${esc(r.trend)} / HTF ${esc(r.htf_trend)} · pattern ${esc(r.pattern || "none")} · R:R ${SM.fmt(r.rr, 2)}</div></div></div>`;
  }

  // ------------------------------------------------------------------ Reports
  SM.views.reports = {
    title: "Reports", icon: "report", group: "Research",
    async render(el) {
      const d = await SM.api.get("/api/reports");
      const grp = (title, rows) => ui.card({ title, body: `<div id="rp-${title.replace(/\W/g, "")}"></div>`, flush: true });
      el.innerHTML = `<div class="view-head"><div><h1>Reports</h1><p>Backtest performance broken down every way the journal allows, next to the paper session.</p></div></div>
        ${kpis(d.metrics)}
        ${ui.card({ title: "Monthly returns", body: '<div id="rp-heat"></div>' })}
        <div class="grid g-3">${grp("By year")}${grp("By direction")}${grp("By exit reason")}</div>
        <div class="grid g-2">${grp("By sector")}${grp("By symbol")}</div>
        <div class="grid g-2">
          ${ui.card({ title: "Paper session vs backtest", body: ui.kv([["Paper trades", String(d.paper.total_trades)], ["Paper avg R", SM.signed(d.paper.average_r, 3)], ["Paper net P&L", ui.money(d.paper.net_pnl)],
            ["Backtest avg R", SM.signed(d.metrics.average_r, 3)], ["Backtest win rate", SM.pct(d.metrics.win_rate, 1)]]) })}
          ${ui.card({ title: "Walk-forward", body: d.walk_forward ? ui.kv([["Folds", String(d.walk_forward.folds)], ["IS avg R", SM.signed(d.walk_forward.in_sample_avg_r, 3)],
            ["OOS avg R", SM.signed(d.walk_forward.out_of_sample_avg_r, 3)], ["OOS return", SM.signedPct(d.walk_forward.oos_return, 2, true)]]) : ui.empty("Not run yet", "Open the Walk-Forward screen to compute it.") })}
        </div>`;
      SM.charts.heatmap(el.querySelector("#rp-heat"), d.monthly);
      const cols = (label) => [{ key: "key", label, render: (r) => `<b>${esc(SM.title(r.key))}</b>` }, { key: "trades", label: "Trades", num: true },
        { key: "win_rate", label: "Win", num: true, render: (r) => SM.pct(r.win_rate, 0) },
        { key: "avg_r", label: "Avg R", num: true, render: (r) => `<span class="${SM.dir(r.avg_r)}">${SM.signed(r.avg_r, 2)}</span>` },
        { key: "net_pnl", label: "Net P&L", num: true, render: (r) => ui.money(r.net_pnl) }];
      [["Byyear", d.by_year, "Year"], ["Bydirection", d.by_direction, "Direction"], ["Byexitreason", d.by_exit, "Exit"], ["Bysector", d.by_sector, "Sector"], ["Bysymbol", d.by_symbol, "Symbol"]]
        .forEach(([id, rows, label]) => ui.table(el.querySelector(`#rp-${id}`), { compact: true, rows, rowKey: (r) => r.key, maxHeight: 340, columns: cols(label) }));
    },
  };
})();
