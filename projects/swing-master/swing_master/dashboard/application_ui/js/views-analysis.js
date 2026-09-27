/* Swing Master -- analysis screens: chart & structure, zones, volume profile, positioning, derivatives, candlesticks. */
(function () {
  "use strict";
  const SM = window.SM, ui = SM.ui, esc = SM.esc;
  SM.parts = SM.parts || {};
  const TFS = ["1M", "1W", "1D", "4H", "1H", "15m", "5m"];

  // ------------------------------------------------------------------ shared chart card
  SM.parts.chartCard = function (el, opts = {}) {
    const st = { tf: SM.state.tf, profile: opts.profile || "FIXED", layers: { zones: true, profile: true, zigzag: true, labels: true, events: true, levels: true, volume: true } };
    const sym = () => SM.state.symbol;
    el.innerHTML = ui.card({
      title: `<span id="cc-title">${esc(sym())}</span>`, sub: '<span id="cc-sub"></span>',
      actions: `${ui.seg("tf", TFS, st.tf, true)}
        ${opts.compact ? "" : `<select class="select" id="cc-prof" aria-label="Volume profile window">${["FIXED", "SWING", "STRUCTURAL_LEG", "DAILY", "WEEKLY"].map((p) => `<option value="${p}" ${p === st.profile ? "selected" : ""}>${SM.title(p)} profile</option>`).join("")}</select>`}`,
      body: `${opts.compact ? "" : `<div class="toolbar" style="margin-bottom:8px">${Object.keys(st.layers).map((k) => `<label class="switch"><input type="checkbox" data-layer="${k}" checked><span class="track"></span>${{ zones: "Demand / Supply", profile: "Volume profile", zigzag: "ZigZag (confirmed)", labels: "HH / HL / LH / LL", events: "BOS / CHoCH", levels: "Trade levels", volume: "Volume" }[k]}</label>`).join("")}</div>`}
        <div id="cc-chart" style="min-height:${opts.height || 460}px"></div>`,
      note: `<span class="chart-legend" style="padding:0">
        <span><i style="background:var(--demand-fill);border:1px solid var(--demand)"></i>Demand</span>
        <span><i style="background:var(--supply-fill);border:1px solid var(--supply)"></i>Supply</span>
        <span><i style="background:var(--poc)"></i>POC</span><span><i style="background:var(--profile-va)"></i>Value area</span>
        <span><i style="background:var(--accent-2)"></i>Confirmed ZigZag · ◇ confirmation bar · ○ unconfirmed (display only)</span>
        <span>Hollow candle = up close</span></span>`,
    });
    let chart = null;
    const chartEl = el.querySelector("#cc-chart");
    async function load() {
      chartEl.innerHTML = ui.loading();
      try {
        const d = await SM.api.get("/api/chart", { symbol: sym(), tf: st.tf, profile: st.profile });
        el.querySelector("#cc-title").textContent = `${d.symbol} · ${d.timeframe}`;
        const s = d.summary;
        el.querySelector("#cc-sub").innerHTML = `${esc(d.name)} · <b class="num">${SM.fmt(s.last.c)}</b> <span class="${SM.dir(s.change)}">${SM.signed(s.change)} (${SM.signed(s.change_pct)}%)</span> · ${ui.trendBadge(s.trend)} <span class="muted">HTF ${esc(d.htf)}</span> ${ui.trendBadge(s.htf_trend)}`;
        chart = new SM.charts.CandleChart(chartEl, d, Object.assign({ height: opts.height || 460, visible: opts.visible || 150, onPivot: opts.onPivot }, st.layers));
        if (opts.onData) opts.onData(d);
      } catch (err) { chartEl.innerHTML = ui.error(err); if (opts.onData) opts.onData(null, err); }
    }
    ui.bindSeg(el, "tf", (v) => { st.tf = v; SM.setState({ tf: v }); load(); });
    const prof = el.querySelector("#cc-prof");
    if (prof) prof.addEventListener("change", () => { st.profile = prof.value; load(); });
    el.querySelectorAll("[data-layer]").forEach((c) => c.addEventListener("change", () => { st.layers[c.dataset.layer] = c.checked; if (chart) chart.set({ [c.dataset.layer]: c.checked }); }));
    load();
    return { reload: load };
  };

  // Section 4 hierarchy: Weekly macro -> Daily structure -> 4H setup -> 1H entry refinement
  SM.parts.mtfCard = async function (el, symbol) {
    el.innerHTML = ui.card({ title: "Timeframe alignment", body: ui.loading() });
    try {
      const d = await SM.api.get("/api/mtf", { symbol });
      const v = d.verdict;
      el.innerHTML = ui.card({ title: "Timeframe alignment" + ui.tip("Weekly gives macro context, Daily the main swing structure, 4H the setup and 1H the entry refinement. Each row uses only completed bars of its own timeframe."),
        actions: ui.badge(v, /BULLISH/.test(v) ? "b-up" : /BEARISH/.test(v) ? "b-down" : "b-warn"),
        body: `<div class="table-wrap"><table class="table compact responsive"><thead><tr><th>TF</th><th>Role</th><th>Trend</th><th>Last pivot</th><th>Last event</th><th class="num">Volatility</th></tr></thead><tbody>
          ${d.rows.map((r) => r.available ? `<tr><td data-label="TF"><b>${esc(r.timeframe)}</b></td><td data-label="Role" class="muted">${esc(r.role)}</td><td data-label="Trend">${ui.trendBadge(r.trend)}</td>
            <td data-label="Last pivot">${r.last_pivot ? `${esc(r.last_pivot.label)} ${SM.fmt(r.last_pivot.price)}` : "—"}</td><td data-label="Last event">${esc(r.last_event || "—")}</td>
            <td data-label="Volatility" class="num">${r.volatility && r.volatility.regime !== "UNAVAILABLE" ? `${SM.fmt(r.volatility.atr_pct, 2)}% <span class="muted">${esc(r.volatility.regime.toLowerCase())}</span>` : "—"}</td></tr>`
            : `<tr><td data-label="TF"><b>${esc(r.timeframe)}</b></td><td data-label="Role" class="muted">${esc(r.role)}</td><td data-label="Trend" colspan="4">${ui.status("UNAVAILABLE")}</td></tr>`).join("")}
          </tbody></table></div>`,
        note: `${d.bullish} of ${d.count} trading timeframes bullish, ${d.bearish} bearish.` });
    } catch (err) { el.innerHTML = ui.card({ title: "Timeframe alignment", body: ui.error(err) }); }
  };

  function volatilityRows(v) {
    if (!v || v.regime === "UNAVAILABLE") return [["Volatility", "—"]];
    return [["ATR % of price", `${SM.fmt(v.atr_pct, 2)}%`],
      ["ATR percentile" + ui.tip(`Where today's ATR sits among the last ${v.lookback} readings. Uses past data only.`), `${SM.fmt(v.percentile, 0)} <span class="muted">(${esc(v.regime.toLowerCase())}, ${esc(v.trend.toLowerCase())})</span>`]];
  }

  function symbolBar(extra = "") {
    return `<div class="toolbar"><div class="ctx-field"><label for="v-sym">Symbol</label>${ui.symbolSelect("v-sym", SM.state.symbol)}</div>${extra}</div>`;
  }
  function bindSymbol(el, fn) {
    const s = el.querySelector("#v-sym");
    if (s) s.addEventListener("change", () => { SM.setState({ symbol: s.value }); fn && fn(); });
  }

  // ------------------------------------------------------------------ Chart & Structure
  SM.views.structure = {
    title: "Chart & Structure", icon: "trend", group: "Analysis",
    async render(el) {
      el.innerHTML = `<div class="view-head"><div><h1>Market structure</h1>
        <p>Pivots are drawn where the swing printed, and a ◇ marks the bar on which the reversal confirmed them. The engine can only use a pivot from its confirmation bar onward.</p></div></div>
        <div class="grid g-main"><div id="st-chart"></div><div class="grid" id="st-side"></div></div>
        <div class="grid g-2"><div id="st-pivots"></div><div id="st-events"></div></div>`;
      const side = el.querySelector("#st-side");
      const inspect = (p) => {
        const box = side.querySelector("#st-inspect");
        if (!box || !p) return;
        box.innerHTML = ui.kv([
          ["Pivot", `${esc(p.label || p.type)} <span class="muted">(${esc(p.type)})</span>`], ["Price", SM.fmt(p.price)],
          ["Pivot time", SM.date(p.time)], ["Confirmation time", SM.date(p.confirmation_time)],
          ["Bars to confirm", String(p.confirmation_bar - p.bar)], ["Previous same-side pivot", SM.fmt(p.previous_price)],
          ["Reversal", `${SM.fmt(p.reversal_pct, 2)}%`], ["Reversal (ATR)", SM.isNum(p.reversal_atr) ? SM.fmt(p.reversal_atr, 2) + " ATR" : "—"],
          ["Status", ui.status(p.status)],
        ]);
      };
      SM.parts.chartCard(el.querySelector("#st-chart"), {
        height: 560, visible: 170, onPivot: inspect,
        onData: (d) => {
          if (!d) { side.innerHTML = ""; return; }
          const s = d.summary;
          side.innerHTML = ui.card({ title: "Structure", body: ui.kv([
            ["Confirmed trend", ui.trendBadge(s.trend)], [`Higher TF (${esc(d.htf)})`, ui.trendBadge(s.htf_trend)],
            ["Last pivot", s.last_pivot ? `${esc(s.last_pivot.label || s.last_pivot.type)} ${SM.fmt(s.last_pivot.price)}` : "—"],
            ["Last event", s.last_event ? `<span class="${s.last_event.direction === "BULLISH" ? "up" : "down"}">${esc(SM.title(s.last_event.direction))} ${s.last_event.type === "CHOCH" ? "CHoCH" : "BOS"}</span> @ ${SM.fmt(s.last_event.level)}` : "—"],
            ["ATR (14)", SM.fmt(s.atr)], ...volatilityRows(s.volatility), ["Price vs value", esc(s.price_location || "—")],
            ["Unconfirmed swing", d.candidate ? `${esc(d.candidate.type)} ${SM.fmt(d.candidate.price)} ${ui.status("UNCONFIRMED")}` : "—"],
          ]) }) + ui.card({ title: "Pivot inspector", sub: "click any pivot label", body: `<div id="st-inspect">${ui.empty("Select a pivot on the chart", "", "target")}</div>` })
            + '<div id="st-mtf"></div>';
          if (d.pivots.length) inspect(d.pivots[d.pivots.length - 1]);
          SM.parts.mtfCard(side.querySelector("#st-mtf"), d.symbol);
          renderPivots(el.querySelector("#st-pivots"), d);
          renderEvents(el.querySelector("#st-events"), d);
        },
      });
    },
  };

  function renderPivots(el, d) {
    const rows = d.pivots.slice().reverse().slice(0, 40);
    el.innerHTML = ui.card({ title: "Confirmed pivots", sub: `${d.pivots.length} in view`, body: '<div id="pv-t"></div>', flush: true });
    ui.table(el.querySelector("#pv-t"), { compact: true, rows, maxHeight: 360, columns: [
      { key: "label", label: "Label", render: (p) => `<b class="${["HH", "HL"].includes(p.label) ? "up" : ["LH", "LL"].includes(p.label) ? "down" : ""}">${esc(p.label || p.type)}</b>` },
      { key: "price", label: "Price", num: true, render: (p) => SM.fmt(p.price) },
      { key: "time", label: "Pivot", render: (p) => SM.date(p.time) },
      { key: "confirmation_time", label: "Confirmed", render: (p) => SM.date(p.confirmation_time) },
      { key: "lag", label: "Lag", num: true, sortValue: (p) => p.confirmation_bar - p.bar, render: (p) => `${p.confirmation_bar - p.bar} bars` },
      { key: "reversal_atr", label: "Reversal", num: true, render: (p) => (SM.isNum(p.reversal_atr) ? SM.fmt(p.reversal_atr, 1) + " ATR" : "—") },
    ] });
  }
  function renderEvents(el, d) {
    const rows = d.events.slice().reverse();
    el.innerHTML = ui.card({ title: "BOS / CHoCH", sub: "CHoCH is an early warning only", body: '<div id="ev-t"></div>', flush: true });
    ui.table(el.querySelector("#ev-t"), { compact: true, rows, maxHeight: 360, empty: ui.empty("No structure events in view"), columns: [
      { key: "time", label: "Time", render: (e) => SM.date(e.time) },
      { key: "type", label: "Event", render: (e) => `<b class="${e.direction === "BULLISH" ? "up" : "down"}">${esc(SM.title(e.direction))} ${e.type === "CHOCH" ? "CHoCH" : "BOS"}</b>` },
      { key: "level", label: "Level", num: true, render: (e) => SM.fmt(e.level) },
      { key: "previous_structure", label: "Before", render: (e) => esc(SM.title(e.previous_structure)) },
      { key: "current_structure", label: "After", render: (e) => esc(SM.title(e.current_structure)) },
    ] });
  }

  // ------------------------------------------------------------------ Demand / Supply
  SM.views.zones = {
    title: "Demand / Supply", icon: "layers", group: "Analysis",
    async render(el) {
      const tf = SM.state.tf === "1D" || SM.state.tf === "1W" ? SM.state.tf : "1D";
      el.innerHTML = `<div class="view-head"><div><h1>Demand & supply zones</h1><p>Created at the close of the leg-out candle, never back-dated. Demand is shown in the green family, supply in red.</p></div>
        <div class="actions">${symbolBar(ui.seg("ztf", ["1W", "1D"], tf, true) + ui.seg("zf", [["ACTIVE", "Active"], ["INVALIDATED", "Invalidated"], ["ALL", "All"]], "ACTIVE", true))}</div></div><div id="z-body"></div>`;
      const st = { tf, filter: "ACTIVE" };
      const body = el.querySelector("#z-body");
      const draw = () => ui.load(body, async () => {
        const d = await SM.api.get("/api/zones", { symbol: SM.state.symbol, tf: st.tf });
        const zs = d.zones.filter((z) => st.filter === "ALL" || (st.filter === "ACTIVE" ? z.status !== "INVALIDATED" : z.status === "INVALIDATED"));
        body.innerHTML = `<p class="muted" style="margin:0 0 10px">${esc(d.symbol)} at ${SM.fmt(d.price)} · ATR ${SM.fmt(d.atr)} · minimum zone score ${d.min_zone_score}. ${esc("Scores exclude components that need a live test (candle, R:R, positioning) until price arrives.")}</p>
          ${zs.length ? `<div class="zone-grid">${zs.map(zoneCard).join("")}</div>` : ui.empty("No zones match this filter")}`;
      });
      ui.bindSeg(el, "ztf", (v) => { st.tf = v; draw(); });
      ui.bindSeg(el, "zf", (v) => { st.filter = v; draw(); });
      bindSymbol(el, draw);
      draw();
    },
  };

  function zoneCard(z) {
    const demand = z.type === "DEMAND";
    return `<article class="zone-card ${demand ? "" : "supply"} ${z.status === "INVALIDATED" ? "invalid" : ""}">
      <header><b class="${demand ? "up" : "down"}">${esc(SM.title(z.type))}</b>${ui.badge(z.pattern, demand ? "b-up" : "b-down")}${ui.status(z.status)}
        <span style="margin-left:auto">${ui.scoreChip(z.score, SM.state.meta.min_zone)}</span></header>
      <div class="mini-kv">
        <div><span>Proximal</span><b>${SM.fmt(z.proximal)}</b></div><div><span>Distal</span><b>${SM.fmt(z.distal)}</b></div>
        <div><span>Origin</span><b>${SM.date(z.origin_time)}</b></div><div><span>Created</span><b>${SM.date(z.creation_time)}</b></div>
        <div><span>Touches</span><b>${z.touches}</b></div><div><span>Departure</span><b>${SM.fmt(z.departure_atr, 2)} ATR</b></div>
        <div><span>Base quality</span><b>${SM.pct(z.base_quality, 0)}</b></div><div><span>Base candles</span><b>${z.base_bars}</b></div>
        <div><span>Pivot alignment</span><b>${z.pivot_alignment ? "Yes" : "No"}</b></div><div><span>POC alignment</span><b>${esc(z.poc_alignment || "—")}</b></div>
        <div><span>HTF alignment</span><b>${esc(z.htf_alignment || "—")}</b></div><div><span>Structure</span><b>${esc((z.structure_alignment || "—").split(" / ")[1] || "—")}</b></div><div><span>Distance</span><b>${SM.isNum(z.distance_atr) ? SM.fmt(z.distance_atr, 1) + " ATR" : "—"}</b></div>
      </div>
      <div class="muted" style="font-size:12px">Structure alignment: ${esc(z.structure_alignment || "—")}</div>
      <div class="muted" style="font-size:12px">Invalidation: ${esc(z.invalidation_rule)}${z.invalidation_time ? ` · invalidated ${SM.date(z.invalidation_time)}` : ""}</div>
      <details class="more"><summary>Score breakdown (${SM.pct(z.coverage, 0)} of weight available)</summary>
        <div class="brk" style="margin-top:8px">${z.score_rows.map((r) => `<span>${esc(r.name)}</span>${ui.bar(r.fraction, r.fraction == null ? "" : r.fraction >= 0.5 ? "up" : "warn")}<span class="val">${r.points == null ? '<span class="muted">n/a</span>' : SM.fmt(r.points, 1) + "/" + r.weight}</span>`).join("")}</div></details>
    </article>`;
  }

  // ------------------------------------------------------------------ Volume Profile
  SM.views.profile = {
    title: "Volume Profile", icon: "profile", group: "Analysis",
    async render(el) {
      const st = { type: "FIXED", lookback: 120 };
      el.innerHTML = `<div class="view-head"><div><h1>Volume profile</h1><p>Where value has been accepted: POC, value area (70%), high- and low-volume nodes, and how they relate to active zones.</p></div>
        <div class="actions">${symbolBar(ui.seg("vpt", [["FIXED", "Fixed range"], ["SWING", "Swing"], ["STRUCTURAL_LEG", "Structural leg"], ["DAILY", "Daily"], ["WEEKLY", "Weekly"], ["HIGHER_TF", "Higher TF"]], "FIXED", true)
          + `<span id="vp-lb">${ui.seg("vplb", [["60", "60 bars"], ["120", "120 bars"], ["250", "250 bars"]], "120", true)}</span>`)}</div></div>
        <div class="grid g-main-l"><div id="vp-side" class="grid"></div><div id="vp-main"></div></div><div id="vp-rel"></div>`;
      const draw = () => ui.load(el.querySelector("#vp-main"), async () => {
        el.querySelector("#vp-lb").hidden = st.type !== "FIXED";
        const params = { symbol: SM.state.symbol, tf: "1D", type: st.type };
        if (st.type === "FIXED" && st.lookback !== 120) params.lookback = st.lookback;
        const d = await SM.api.get("/api/volume-profile", params);
        const vp = d.profile;
        el.querySelector("#vp-main").innerHTML = ui.card({ title: `${esc(d.symbol)} · ${esc(SM.title(d.type))} profile`, sub: vp ? `bars ${vp.start_bar}–${vp.end_bar}` : "", body: '<div id="vp-chart"></div>', note: esc(d.method) });
        SM.charts.profile(el.querySelector("#vp-chart"), vp, { price: d.price, zones: d.relations.map((r) => r.zone), height: 460 });
        el.querySelector("#vp-side").innerHTML = ui.card({ title: "Levels", body: vp ? ui.kv([
          ["Last price", SM.fmt(d.price)], ["Location", esc(d.location || "—")], ["POC", `<span style="color:var(--poc)">${SM.fmt(vp.poc)}</span>`],
          ["VAH", SM.fmt(vp.vah)], ["VAL", SM.fmt(vp.val)], ["HVN", vp.hvn.map((x) => SM.fmt(x, 0)).join(", ") || "—"],
          ["LVN", vp.lvn.map((x) => SM.fmt(x, 0)).join(", ") || "—"], ["Bins", String(vp.volumes.length)], ["Total volume", SM.compact(vp.total_volume)],
        ]) : ui.empty("Profile unavailable for this window") });
        const rel = el.querySelector("#vp-rel");
        rel.innerHTML = ui.card({ title: "Relationship to active zones", sub: `distance normalised by ATR (${SM.fmt(d.atr)})`, body: '<div id="vp-rel-t"></div>', flush: true });
        ui.table(rel.querySelector("#vp-rel-t"), { rows: d.relations, empty: ui.empty("No active zones"), columns: [
          { key: "zone", label: "Zone", render: (r) => `<b class="${r.zone.type === "DEMAND" ? "up" : "down"}">${esc(SM.title(r.zone.type))} ${esc(r.zone.pattern)}</b> ${SM.fmt(r.zone.proximal)}–${SM.fmt(r.zone.distal)}` },
          { key: "poc", label: "POC", render: (r) => relCell(r.confluence.levels.POC) },
          { key: "vah", label: "VAH", render: (r) => relCell(r.confluence.levels.VAH) },
          { key: "val", label: "VAL", render: (r) => relCell(r.confluence.levels.VAL) },
          { key: "hvn", label: "HVN", render: (r) => (r.confluence.levels.HVN || []).map(relCell).join(" ") || "—" },
          { key: "lvn", label: "LVN inside", render: (r) => (r.confluence.lvn_inside ? ui.badge("Yes", "b-warn") : "No") },
          { key: "score", label: "VP score", num: true, sortValue: (r) => r.confluence.score, render: (r) => SM.isNum(r.confluence.score) ? SM.pct(r.confluence.score, 0) : "—" },
        ] });
      });
      ui.bindSeg(el, "vpt", (v) => { st.type = v; draw(); });
      ui.bindSeg(el, "vplb", (v) => { st.lookback = +v; draw(); });
      bindSymbol(el, draw);
      draw();
    },
  };
  function relCell(l) {
    if (!l) return "—";
    const k = l.relation === "INSIDE" ? "b-up" : l.relation === "NEAR" ? "b-warn" : "b-muted";
    return `${ui.badge(l.relation, k)} <span class="muted num">${SM.isNum(l.distance_atr) ? SM.fmt(l.distance_atr, 1) + "A" : ""}</span>`;
  }

  // ------------------------------------------------------------------ Positioning
  SM.views.positioning = {
    title: "Positioning", icon: "users", group: "Analysis",
    async render(el) {
      const d = await SM.api.get("/api/positioning");
      const cat = (k) => {
        const c = d.categories[k];
        return ui.card({ title: SM.title(k), actions: ui.status(c.status), body: `<div class="pos-card">
          ${ui.kv([["Net", SM.fmt(c.net, 0)], ["Net %", SM.isNum(c.net_pct) ? SM.pct(c.net_pct, 1) : "—"], ["Percentile", SM.isNum(c.percentile) ? SM.fmt(c.percentile, 0) : "—"],
            ["Z-score", SM.fmt(c.zscore, 2)], ["1P change", SM.isNum(c.change_1) ? SM.signed(c.change_1 * 100, 1, "%") : "—"],
            ["5P change", SM.isNum(c.change_5) ? SM.signed(c.change_5 * 100, 1, "%") : "—"], ["20P change", SM.isNum(c.change_20) ? SM.signed(c.change_20 * 100, 1, "%") : "—"],
            ["Classification", c.classification ? `<b>${esc(c.classification)}</b>` : "—"], ["Observations", String(c.observations)]])}
          ${c.note ? `<div class="muted" style="font-size:12px">${esc(c.note)}</div>` : ""}</div>` });
      };
      const dv = d.divergence;
      el.innerHTML = `<div class="view-head"><div><h1>Participant positioning</h1><p>Commercial, institutional and retail engines run separately. Each value is tagged DIRECT, PROXY or UNAVAILABLE, and is only used after its publication time.</p></div></div>
        ${ui.card({ title: "Positioning divergence", actions: ui.status(dv.status), body: `<div class="grid g-2" style="align-items:center">
            <div><div class="status-big ${dv.signal && dv.signal.startsWith("BULL") ? "up" : dv.signal && dv.signal.startsWith("BEAR") ? "down" : "muted"}">${esc(dv.signal || "CANNOT EVALUATE")}</div>
            <p class="muted" style="margin:6px 0 0">${esc(dv.detail)}</p></div>
            <div>${ui.notice(esc(d.source_help), "info")}</div></div>` })}
        <div class="grid g-3">${cat("COMMERCIAL")}${cat("INSTITUTIONAL")}${cat("RETAIL")}</div>
        <h2 class="section-title">Futures OI (positioning proxy)</h2>
        <div class="grid g-3" id="pz"></div>`;
      const pz = el.querySelector("#pz");
      pz.innerHTML = d.proxies.map((p, i) => ui.card({ title: esc(p.symbol), actions: ui.status("PROXY"),
        body: `${ui.kv([["1-day state", p.state ? `<b class="${/LONG BUILD|SHORT COVER/.test(p.state.state) ? "up" : /SHORT BUILD|LONG UNWIND/.test(p.state.state) ? "down" : ""}">${esc(p.state.state)}</b>` : "—"],
          ["5-day state", p.state_5d ? esc(p.state_5d.state) : "—"], ["OI", p.state ? SM.compact(p.state.oi) : "—"], ["OI change", p.state ? ui.chg(p.state.oi_change_pct) : "—"]])}
          <div id="pz-${i}" style="margin-top:10px"></div>` })).join("") || ui.empty("No futures OI loaded");
      d.proxies.forEach((p, i) => SM.charts.bars(el.querySelector(`#pz-${i}`), { height: 130, yFmt: (v) => SM.fmt(v, 1) + "%", label: "OI change %",
        items: p.history.map((h) => ({ label: SM.dateShort(h.date), value: h.oi_change_pct })) }));
    },
  };

  // ------------------------------------------------------------------ Derivatives
  SM.views.derivatives = {
    title: "Derivatives", icon: "activity", group: "Analysis",
    async render(el) {
      const st = { days: 30, strikes: 10, chainView: "chart" };
      el.innerHTML = `<div class="view-head"><div><h1>Derivatives context</h1><p>Futures OI build-up states and options put/call ratios. PCR is context only and never a standalone signal.</p></div>
        <div class="actions">${symbolBar(ui.seg("dd", [["20", "20D"], ["30", "30D"], ["60", "60D"], ["90", "90D"]], "30", true)
          + ui.seg("dk", [["5", "ATM ±5"], ["10", "ATM ±10"], ["15", "ATM ±15"]], "10", true))}</div></div><div id="dv"></div>`;
      const body = el.querySelector("#dv");
      const draw = () => ui.load(body, async () => {
        const params = { symbol: SM.state.symbol, days: st.days };
        if (st.strikes !== 10) params.strikes = st.strikes;
        const d = await SM.api.get("/api/derivatives", params);
        const f = d.futures, o = d.options;
        body.innerHTML = `<div class="grid g-2">
          ${ui.card({ title: "Futures OI", actions: ui.status(f ? d.source : "UNAVAILABLE"), body: f ? `<div class="kpi-row" style="margin-bottom:12px">
              ${ui.kpi({ label: "State", value: `<span class="${/LONG BUILD|SHORT COVER/.test(f.state.state) ? "up" : /SHORT BUILD|LONG UNWIND/.test(f.state.state) ? "down" : ""}" style="font-size:16px">${esc(f.state.state)}</span>`, cls: "compact" })}
              ${ui.kpi({ label: "Open interest", value: SM.compact(f.state.oi), sub: `ΔOI ${SM.compact(f.state.oi_change)}`, cls: "compact" })}
              ${ui.kpi({ label: "Price", value: SM.fmt(f.state.price), sub: ui.chg(f.state.price_change_pct), cls: "compact" })}</div>
              <div id="dv-oi"></div>` : ui.empty("No futures OI for this instrument") , note: esc(d.note) })}
          ${ui.card({ title: "Options / PCR", actions: ui.status(o && o.now.available ? d.source : "UNAVAILABLE"), body: o && o.now.available ? `<div class="kpi-row" style="margin-bottom:12px">
              ${ui.kpi({ label: "PCR (OI)", value: SM.fmt(o.now.pcr, 2), sub: `ATM ± ${o.strikes_each_side} strikes`, cls: "compact" })}
              ${ui.kpi({ label: "ΔOI PCR", value: SM.isNum(o.now.change_oi_pcr) ? SM.fmt(o.now.change_oi_pcr, 2) : "—", sub: esc(o.now.change_oi_pcr_reason || "put ΔOI / call ΔOI"), cls: "compact" })}
              ${ui.kpi({ label: "ATM", value: SM.fmt(o.now.atm, 0), sub: `Range ${SM.fmt(o.now.strike_range[0], 0)}–${SM.fmt(o.now.strike_range[1], 0)} · expiry ${SM.dateShort(o.now.expiry)}`, cls: "compact" })}</div>
              <div id="dv-pcr"></div>` : ui.empty("No option chain for this instrument", "The demo simulates option chains for NIFTY, BANKNIFTY and FINNIFTY only.") })}
          </div>
          <div class="grid g-2">${f ? ui.card({ title: "Futures history", body: '<div id="dv-ft"></div>', flush: true }) : ""}
          ${o && o.strikes.length ? ui.card({ title: "Option chain", sub: `${o.now.strikes_used} strikes in ATM ±${o.strikes_each_side}`,
            actions: ui.seg("cv", [["chart", "OI chart"], ["table", "OI & ΔOI table"]], st.chainView, true), body: '<div id="dv-chain"></div>',
            note: o.now.skipped_illiquid.length ? `Illiquid strikes skipped: ${o.now.skipped_illiquid.join(", ")}` : "Faded rows are outside the selected strike range." }) : ""}</div>`;
        if (f) {
          SM.charts.bars(body.querySelector("#dv-oi"), { height: 170, label: "Open interest", yFmt: (v) => SM.compact(v),
            items: f.history.map((h) => ({ label: SM.dateShort(h.date), value: h.oi, color: h.price_change_pct >= 0 ? "var(--up)" : "var(--down)", opacity: 0.75 })) });
          ui.table(body.querySelector("#dv-ft"), { compact: true, maxHeight: 360, rows: f.history.slice().reverse(), columns: [
            { key: "date", label: "Date", render: (h) => SM.date(h.date) }, { key: "price", label: "Price", num: true, render: (h) => SM.fmt(h.price) },
            { key: "price_change_pct", label: "Price Δ", num: true, render: (h) => ui.chg(h.price_change_pct) },
            { key: "oi", label: "OI", num: true, render: (h) => SM.compact(h.oi) }, { key: "oi_change_pct", label: "ΔOI", num: true, render: (h) => ui.chg(h.oi_change_pct) },
            { key: "state", label: "State", render: (h) => `<span class="${/LONG BUILD|SHORT COVER/.test(h.state) ? "up" : /SHORT BUILD|LONG UNWIND/.test(h.state) ? "down" : "muted"}">${esc(SM.title(h.state))}</span>` },
          ] });
        }
        if (o && o.now.available) {
          SM.charts.line(body.querySelector("#dv-pcr"), { height: 170, label: "PCR history", yFmt: (v) => SM.fmt(v, 2), xFmt: SM.dateShort,
            series: [{ name: "PCR", color: "var(--accent)", data: o.history.map((h) => ({ x: h.date, y: h.pcr })) },
              { name: "ΔOI PCR", color: "var(--warn)", dash: "4 3", data: o.history.map((h) => ({ x: h.date, y: h.change_oi_pcr })) }] });
          const drawChain = () => {
            const box = body.querySelector("#dv-chain");
            if (st.chainView === "chart") { SM.charts.chain(box, o.strikes, { atm: o.now.atm }); return; }
            ui.table(box, { compact: true, rows: o.strikes.filter((x) => x.selected), maxHeight: 460, rowKey: (x) => x.strike, columns: [
              { key: "call_change_oi", label: "Call ΔOI", num: true, render: (x) => `<span class="${SM.dir(x.call_change_oi)}">${SM.compact(x.call_change_oi)}</span>` },
              { key: "call_oi", label: "Call OI", num: true, render: (x) => SM.compact(x.call_oi) },
              { key: "strike", label: "Strike", num: true, render: (x) => `<b class="${x.strike === o.now.atm ? "accent" : ""}">${SM.fmt(x.strike, 0)}${x.strike === o.now.atm ? " ATM" : ""}</b>` },
              { key: "put_oi", label: "Put OI", num: true, render: (x) => SM.compact(x.put_oi) },
              { key: "put_change_oi", label: "Put ΔOI", num: true, render: (x) => `<span class="${SM.dir(x.put_change_oi)}">${SM.compact(x.put_change_oi)}</span>` },
            ] });
          };
          drawChain();
          ui.bindSeg(body, "cv", (v) => { st.chainView = v; drawChain(); });
        }
      });
      ui.bindSeg(el, "dd", (v) => { st.days = +v; draw(); });
      ui.bindSeg(el, "dk", (v) => { st.strikes = +v; draw(); });
      bindSymbol(el, draw);
      draw();
    },
  };

  // ------------------------------------------------------------------ Candlesticks
  SM.views.candles = {
    title: "Candlesticks", icon: "candles", group: "Analysis",
    async render(el) {
      el.innerHTML = `<div class="view-head"><div><h1>Candlestick reversals</h1><p>Every pattern is a formula on body, range, wicks, close location, the previous candle and ATR. Nothing is judged by eye.</p></div>
        <div class="actions">${symbolBar()}</div></div><div id="cd"></div>`;
      const body = el.querySelector("#cd");
      const draw = () => ui.load(body, async () => {
        const d = await SM.api.get("/api/candles", { symbol: SM.state.symbol, tf: "1D", lookback: 60 });
        body.innerHTML = `<div class="grid g-main">${ui.card({ title: `${esc(d.symbol)} patterns`, sub: `last ${d.lookback} bars`, body: '<div id="cd-t"></div>', flush: true })}
          ${ui.card({ title: "Definitions", body: `<ul class="checklist">${d.definitions.map((x) => `<li class="na"><span class="ic">${SM.icon("candles")}</span><span><b>${esc(x.pattern)}</b><br><span class="muted">${esc(x.rule)}</span></span></li>`).join("")}</ul>` })}</div>`;
        ui.table(body.querySelector("#cd-t"), { rows: d.rows, empty: ui.empty("No reversal patterns in this window"), columns: [
          { key: "time", label: "Date", render: (r) => SM.date(r.time) },
          { key: "pattern", label: "Pattern", render: (r) => `<b class="${r.direction === "BULLISH" ? "up" : "down"}">${esc(SM.title(r.pattern))}</b>` },
          { key: "confidence", label: "Confidence", num: true, render: (r) => `${SM.pct(r.confidence, 0)}` },
          { key: "body_ratio", label: "Body", num: true, render: (r) => SM.pct(r.body_ratio, 0) },
          { key: "upper_wick_ratio", label: "Upper wick", num: true, render: (r) => SM.pct(r.upper_wick_ratio, 0) },
          { key: "lower_wick_ratio", label: "Lower wick", num: true, render: (r) => SM.pct(r.lower_wick_ratio, 0) },
          { key: "atr_range", label: "Range/ATR", num: true, render: (r) => SM.fmt(r.atr_range, 2) },
          { key: "close_location", label: "Close loc.", num: true, render: (r) => SM.pct(r.close_location, 0) },
          { key: "previous_relationship", label: "Previous candle", cls: "wrap" },
          { key: "zone_relationship", label: "Zone", render: (r) => relBadge(r.zone_relationship) },
          { key: "poc_relationship", label: "POC", render: (r) => relBadge(r.poc_relationship) },
        ] });
      });
      bindSymbol(el, draw);
      draw();
    },
  };
  function relBadge(r) {
    if (!r || r === "NONE") return '<span class="muted">—</span>';
    return ui.badge(r, r === "INSIDE" ? "b-up" : r === "NEAR" ? "b-warn" : "b-muted");
  }
})();
