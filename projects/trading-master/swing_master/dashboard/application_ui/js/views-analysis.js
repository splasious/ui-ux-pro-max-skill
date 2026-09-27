/* Trading Master -- analysis screens: chart & structure, zones, volume profile, positioning, derivatives, candlesticks. */
(function () {
  "use strict";
  const TM = window.TM, ui = TM.ui, esc = TM.esc;
  TM.parts = TM.parts || {};
  const TFS = ["1M", "1W", "1D", "4H", "1H", "15m", "5m"];

  // ------------------------------------------------------------------ shared chart card
  TM.parts.chartCard = function (el, opts = {}) {
    const st = { tf: TM.state.tf, profile: opts.profile || "FIXED", layers: { zones: true, profile: true, zigzag: true, labels: true, events: true, levels: true, volume: true } };
    const sym = () => TM.state.symbol;
    el.innerHTML = ui.card({
      title: `<span id="cc-title">${esc(sym())}</span>`, sub: '<span id="cc-sub"></span>',
      actions: `${ui.seg("tf", TFS, st.tf, true)}
        ${opts.compact ? "" : `<select class="select" id="cc-prof" aria-label="Volume profile window">${["FIXED", "SWING", "STRUCTURAL_LEG", "DAILY", "WEEKLY"].map((p) => `<option value="${p}" ${p === st.profile ? "selected" : ""}>${TM.title(p)} profile</option>`).join("")}</select>`}`,
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
        const d = await TM.api.get("/api/chart", { symbol: sym(), tf: st.tf, profile: st.profile });
        el.querySelector("#cc-title").textContent = `${d.symbol} · ${d.timeframe}`;
        const s = d.summary;
        el.querySelector("#cc-sub").innerHTML = `${esc(d.name)} · <b class="num">${TM.fmt(s.last.c)}</b> <span class="${TM.dir(s.change)}">${TM.signed(s.change)} (${TM.signed(s.change_pct)}%)</span> · ${ui.trendBadge(s.trend)} <span class="muted">HTF ${esc(d.htf)}</span> ${ui.trendBadge(s.htf_trend)}`;
        chart = new TM.charts.CandleChart(chartEl, d, Object.assign({ height: opts.height || 460, visible: opts.visible || 150, onPivot: opts.onPivot }, st.layers));
        if (opts.onData) opts.onData(d);
      } catch (err) { chartEl.innerHTML = ui.error(err); if (opts.onData) opts.onData(null, err); }
    }
    ui.bindSeg(el, "tf", (v) => { st.tf = v; TM.setState({ tf: v }); load(); });
    const prof = el.querySelector("#cc-prof");
    if (prof) prof.addEventListener("change", () => { st.profile = prof.value; load(); });
    el.querySelectorAll("[data-layer]").forEach((c) => c.addEventListener("change", () => { st.layers[c.dataset.layer] = c.checked; if (chart) chart.set({ [c.dataset.layer]: c.checked }); }));
    load();
    return { reload: load };
  };

  function symbolBar(extra = "") {
    return `<div class="toolbar"><div class="ctx-field"><label for="v-sym">Symbol</label>${ui.symbolSelect("v-sym", TM.state.symbol)}</div>${extra}</div>`;
  }
  function bindSymbol(el, fn) {
    const s = el.querySelector("#v-sym");
    if (s) s.addEventListener("change", () => { TM.setState({ symbol: s.value }); fn && fn(); });
  }

  // ------------------------------------------------------------------ Chart & Structure
  TM.views.structure = {
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
          ["Pivot", `${esc(p.label || p.type)} <span class="muted">(${esc(p.type)})</span>`], ["Price", TM.fmt(p.price)],
          ["Pivot time", TM.date(p.time)], ["Confirmation time", TM.date(p.confirmation_time)],
          ["Bars to confirm", String(p.confirmation_bar - p.bar)], ["Previous same-side pivot", TM.fmt(p.previous_price)],
          ["Reversal", `${TM.fmt(p.reversal_pct, 2)}%`], ["Reversal (ATR)", TM.isNum(p.reversal_atr) ? TM.fmt(p.reversal_atr, 2) + " ATR" : "—"],
          ["Status", ui.status(p.status)],
        ]);
      };
      TM.parts.chartCard(el.querySelector("#st-chart"), {
        height: 560, visible: 170, onPivot: inspect,
        onData: (d) => {
          if (!d) { side.innerHTML = ""; return; }
          const s = d.summary;
          side.innerHTML = ui.card({ title: "Structure", body: ui.kv([
            ["Confirmed trend", ui.trendBadge(s.trend)], [`Higher TF (${esc(d.htf)})`, ui.trendBadge(s.htf_trend)],
            ["Last pivot", s.last_pivot ? `${esc(s.last_pivot.label || s.last_pivot.type)} ${TM.fmt(s.last_pivot.price)}` : "—"],
            ["Last event", s.last_event ? `<span class="${s.last_event.direction === "BULLISH" ? "up" : "down"}">${esc(TM.title(s.last_event.direction))} ${s.last_event.type === "CHOCH" ? "CHoCH" : "BOS"}</span> @ ${TM.fmt(s.last_event.level)}` : "—"],
            ["ATR (14)", TM.fmt(s.atr)], ["Price vs value", esc(s.price_location || "—")],
            ["Unconfirmed swing", d.candidate ? `${esc(d.candidate.type)} ${TM.fmt(d.candidate.price)} ${ui.status("UNCONFIRMED")}` : "—"],
          ]) }) + ui.card({ title: "Pivot inspector", sub: "click any pivot label", body: `<div id="st-inspect">${ui.empty("Select a pivot on the chart", "", "target")}</div>` });
          if (d.pivots.length) inspect(d.pivots[d.pivots.length - 1]);
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
      { key: "price", label: "Price", num: true, render: (p) => TM.fmt(p.price) },
      { key: "time", label: "Pivot", render: (p) => TM.date(p.time) },
      { key: "confirmation_time", label: "Confirmed", render: (p) => TM.date(p.confirmation_time) },
      { key: "lag", label: "Lag", num: true, sortValue: (p) => p.confirmation_bar - p.bar, render: (p) => `${p.confirmation_bar - p.bar} bars` },
      { key: "reversal_atr", label: "Reversal", num: true, render: (p) => (TM.isNum(p.reversal_atr) ? TM.fmt(p.reversal_atr, 1) + " ATR" : "—") },
    ] });
  }
  function renderEvents(el, d) {
    const rows = d.events.slice().reverse();
    el.innerHTML = ui.card({ title: "BOS / CHoCH", sub: "CHoCH is an early warning only", body: '<div id="ev-t"></div>', flush: true });
    ui.table(el.querySelector("#ev-t"), { compact: true, rows, maxHeight: 360, empty: ui.empty("No structure events in view"), columns: [
      { key: "time", label: "Time", render: (e) => TM.date(e.time) },
      { key: "type", label: "Event", render: (e) => `<b class="${e.direction === "BULLISH" ? "up" : "down"}">${esc(TM.title(e.direction))} ${e.type === "CHOCH" ? "CHoCH" : "BOS"}</b>` },
      { key: "level", label: "Level", num: true, render: (e) => TM.fmt(e.level) },
      { key: "previous_structure", label: "Before", render: (e) => esc(TM.title(e.previous_structure)) },
      { key: "current_structure", label: "After", render: (e) => esc(TM.title(e.current_structure)) },
    ] });
  }

  // ------------------------------------------------------------------ Demand / Supply
  TM.views.zones = {
    title: "Demand / Supply", icon: "layers", group: "Analysis",
    async render(el) {
      const tf = TM.state.tf === "1D" || TM.state.tf === "1W" ? TM.state.tf : "1D";
      el.innerHTML = `<div class="view-head"><div><h1>Demand & supply zones</h1><p>Created at the close of the leg-out candle, never back-dated. Demand is shown in the green family, supply in red.</p></div>
        <div class="actions">${symbolBar(ui.seg("ztf", ["1W", "1D"], tf, true) + ui.seg("zf", [["ACTIVE", "Active"], ["INVALIDATED", "Invalidated"], ["ALL", "All"]], "ACTIVE", true))}</div></div><div id="z-body"></div>`;
      const st = { tf, filter: "ACTIVE" };
      const body = el.querySelector("#z-body");
      const draw = () => ui.load(body, async () => {
        const d = await TM.api.get("/api/zones", { symbol: TM.state.symbol, tf: st.tf });
        const zs = d.zones.filter((z) => st.filter === "ALL" || (st.filter === "ACTIVE" ? z.status !== "INVALIDATED" : z.status === "INVALIDATED"));
        body.innerHTML = `<p class="muted" style="margin:0 0 10px">${esc(d.symbol)} at ${TM.fmt(d.price)} · ATR ${TM.fmt(d.atr)} · minimum zone score ${d.min_zone_score}. ${esc("Scores exclude components that need a live test (candle, R:R, positioning) until price arrives.")}</p>
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
      <header><b class="${demand ? "up" : "down"}">${esc(TM.title(z.type))}</b>${ui.badge(z.pattern, demand ? "b-up" : "b-down")}${ui.status(z.status)}
        <span style="margin-left:auto">${ui.scoreChip(z.score, TM.state.meta.min_zone)}</span></header>
      <div class="mini-kv">
        <div><span>Proximal</span><b>${TM.fmt(z.proximal)}</b></div><div><span>Distal</span><b>${TM.fmt(z.distal)}</b></div>
        <div><span>Origin</span><b>${TM.date(z.origin_time)}</b></div><div><span>Created</span><b>${TM.date(z.creation_time)}</b></div>
        <div><span>Touches</span><b>${z.touches}</b></div><div><span>Departure</span><b>${TM.fmt(z.departure_atr, 2)} ATR</b></div>
        <div><span>Base quality</span><b>${TM.pct(z.base_quality, 0)}</b></div><div><span>Base candles</span><b>${z.base_bars}</b></div>
        <div><span>Pivot alignment</span><b>${z.pivot_alignment ? "Yes" : "No"}</b></div><div><span>POC alignment</span><b>${esc(z.poc_alignment || "—")}</b></div>
        <div><span>HTF alignment</span><b>${esc(z.htf_alignment || "—")}</b></div><div><span>Distance</span><b>${TM.isNum(z.distance_atr) ? TM.fmt(z.distance_atr, 1) + " ATR" : "—"}</b></div>
      </div>
      <div class="muted" style="font-size:12px">Invalidation: ${esc(z.invalidation_rule)}${z.invalidation_time ? ` · invalidated ${TM.date(z.invalidation_time)}` : ""}</div>
      <details class="more"><summary>Score breakdown (${TM.pct(z.coverage, 0)} of weight available)</summary>
        <div class="brk" style="margin-top:8px">${z.score_rows.map((r) => `<span>${esc(r.name)}</span>${ui.bar(r.fraction, r.fraction == null ? "" : r.fraction >= 0.5 ? "up" : "warn")}<span class="val">${r.points == null ? '<span class="muted">n/a</span>' : TM.fmt(r.points, 1) + "/" + r.weight}</span>`).join("")}</div></details>
    </article>`;
  }

  // ------------------------------------------------------------------ Volume Profile
  TM.views.profile = {
    title: "Volume Profile", icon: "profile", group: "Analysis",
    async render(el) {
      const st = { type: "FIXED" };
      el.innerHTML = `<div class="view-head"><div><h1>Volume profile</h1><p>Where value has been accepted: POC, value area (70%), high- and low-volume nodes, and how they relate to active zones.</p></div>
        <div class="actions">${symbolBar(ui.seg("vpt", [["FIXED", "Fixed"], ["SWING", "Swing"], ["STRUCTURAL_LEG", "Structural leg"], ["DAILY", "Daily"], ["WEEKLY", "Weekly"]], "FIXED", true))}</div></div>
        <div class="grid g-main-l"><div id="vp-side" class="grid"></div><div id="vp-main"></div></div><div id="vp-rel"></div>`;
      const draw = () => ui.load(el.querySelector("#vp-main"), async () => {
        const d = await TM.api.get("/api/volume-profile", { symbol: TM.state.symbol, tf: "1D", type: st.type });
        const vp = d.profile;
        el.querySelector("#vp-main").innerHTML = ui.card({ title: `${esc(d.symbol)} · ${esc(TM.title(d.type))} profile`, sub: vp ? `bars ${vp.start_bar}–${vp.end_bar}` : "", body: '<div id="vp-chart"></div>', note: esc(d.method) });
        TM.charts.profile(el.querySelector("#vp-chart"), vp, { price: d.price, zones: d.relations.map((r) => r.zone), height: 460 });
        el.querySelector("#vp-side").innerHTML = ui.card({ title: "Levels", body: vp ? ui.kv([
          ["Last price", TM.fmt(d.price)], ["Location", esc(d.location || "—")], ["POC", `<span style="color:var(--poc)">${TM.fmt(vp.poc)}</span>`],
          ["VAH", TM.fmt(vp.vah)], ["VAL", TM.fmt(vp.val)], ["HVN", vp.hvn.map((x) => TM.fmt(x, 0)).join(", ") || "—"],
          ["LVN", vp.lvn.map((x) => TM.fmt(x, 0)).join(", ") || "—"], ["Bins", String(vp.volumes.length)], ["Total volume", TM.compact(vp.total_volume)],
        ]) : ui.empty("Profile unavailable for this window") });
        const rel = el.querySelector("#vp-rel");
        rel.innerHTML = ui.card({ title: "Relationship to active zones", sub: `distance normalised by ATR (${TM.fmt(d.atr)})`, body: '<div id="vp-rel-t"></div>', flush: true });
        ui.table(rel.querySelector("#vp-rel-t"), { rows: d.relations, empty: ui.empty("No active zones"), columns: [
          { key: "zone", label: "Zone", render: (r) => `<b class="${r.zone.type === "DEMAND" ? "up" : "down"}">${esc(TM.title(r.zone.type))} ${esc(r.zone.pattern)}</b> ${TM.fmt(r.zone.proximal)}–${TM.fmt(r.zone.distal)}` },
          { key: "poc", label: "POC", render: (r) => relCell(r.confluence.levels.POC) },
          { key: "vah", label: "VAH", render: (r) => relCell(r.confluence.levels.VAH) },
          { key: "val", label: "VAL", render: (r) => relCell(r.confluence.levels.VAL) },
          { key: "hvn", label: "HVN", render: (r) => (r.confluence.levels.HVN || []).map(relCell).join(" ") || "—" },
          { key: "lvn", label: "LVN inside", render: (r) => (r.confluence.lvn_inside ? ui.badge("Yes", "b-warn") : "No") },
          { key: "score", label: "VP score", num: true, sortValue: (r) => r.confluence.score, render: (r) => TM.isNum(r.confluence.score) ? TM.pct(r.confluence.score, 0) : "—" },
        ] });
      });
      ui.bindSeg(el, "vpt", (v) => { st.type = v; draw(); });
      bindSymbol(el, draw);
      draw();
    },
  };
  function relCell(l) {
    if (!l) return "—";
    const k = l.relation === "INSIDE" ? "b-up" : l.relation === "NEAR" ? "b-warn" : "b-muted";
    return `${ui.badge(l.relation, k)} <span class="muted num">${TM.isNum(l.distance_atr) ? TM.fmt(l.distance_atr, 1) + "A" : ""}</span>`;
  }

  // ------------------------------------------------------------------ Positioning
  TM.views.positioning = {
    title: "Positioning", icon: "users", group: "Analysis",
    async render(el) {
      const d = await TM.api.get("/api/positioning");
      const cat = (k) => {
        const c = d.categories[k];
        return ui.card({ title: TM.title(k), actions: ui.status(c.status), body: `<div class="pos-card">
          ${ui.kv([["Net", TM.fmt(c.net, 0)], ["Net %", TM.isNum(c.net_pct) ? TM.pct(c.net_pct, 1) : "—"], ["Percentile", TM.isNum(c.percentile) ? TM.fmt(c.percentile, 0) : "—"],
            ["Z-score", TM.fmt(c.zscore, 2)], ["1P change", TM.isNum(c.change_1) ? TM.signed(c.change_1 * 100, 1, "%") : "—"],
            ["5P change", TM.isNum(c.change_5) ? TM.signed(c.change_5 * 100, 1, "%") : "—"], ["20P change", TM.isNum(c.change_20) ? TM.signed(c.change_20 * 100, 1, "%") : "—"],
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
          ["5-day state", p.state_5d ? esc(p.state_5d.state) : "—"], ["OI", p.state ? TM.compact(p.state.oi) : "—"], ["OI change", p.state ? ui.chg(p.state.oi_change_pct) : "—"]])}
          <div id="pz-${i}" style="margin-top:10px"></div>` })).join("") || ui.empty("No futures OI loaded");
      d.proxies.forEach((p, i) => TM.charts.bars(el.querySelector(`#pz-${i}`), { height: 130, yFmt: (v) => TM.fmt(v, 1) + "%", label: "OI change %",
        items: p.history.map((h) => ({ label: TM.dateShort(h.date), value: h.oi_change_pct })) }));
    },
  };

  // ------------------------------------------------------------------ Derivatives
  TM.views.derivatives = {
    title: "Derivatives", icon: "activity", group: "Analysis",
    async render(el) {
      const st = { days: 30 };
      el.innerHTML = `<div class="view-head"><div><h1>Derivatives context</h1><p>Futures OI build-up states and options put/call ratios. PCR is context only and never a standalone signal.</p></div>
        <div class="actions">${symbolBar(ui.seg("dd", [["20", "20D"], ["30", "30D"], ["60", "60D"]], "30", true))}</div></div><div id="dv"></div>`;
      const body = el.querySelector("#dv");
      const draw = () => ui.load(body, async () => {
        const d = await TM.api.get("/api/derivatives", { symbol: TM.state.symbol, days: st.days });
        const f = d.futures, o = d.options;
        body.innerHTML = `<div class="grid g-2">
          ${ui.card({ title: "Futures OI", actions: ui.status(f ? d.source : "UNAVAILABLE"), body: f ? `<div class="kpi-row" style="margin-bottom:12px">
              ${ui.kpi({ label: "State", value: `<span class="${/LONG BUILD|SHORT COVER/.test(f.state.state) ? "up" : /SHORT BUILD|LONG UNWIND/.test(f.state.state) ? "down" : ""}" style="font-size:16px">${esc(f.state.state)}</span>`, cls: "compact" })}
              ${ui.kpi({ label: "Open interest", value: TM.compact(f.state.oi), sub: `ΔOI ${TM.compact(f.state.oi_change)}`, cls: "compact" })}
              ${ui.kpi({ label: "Price", value: TM.fmt(f.state.price), sub: ui.chg(f.state.price_change_pct), cls: "compact" })}</div>
              <div id="dv-oi"></div>` : ui.empty("No futures OI for this instrument") , note: esc(d.note) })}
          ${ui.card({ title: "Options / PCR", actions: ui.status(o && o.now.available ? d.source : "UNAVAILABLE"), body: o && o.now.available ? `<div class="kpi-row" style="margin-bottom:12px">
              ${ui.kpi({ label: "PCR (OI)", value: TM.fmt(o.now.pcr, 2), sub: `ATM ± ${o.strikes_each_side} strikes`, cls: "compact" })}
              ${ui.kpi({ label: "ΔOI PCR", value: TM.isNum(o.now.change_oi_pcr) ? TM.fmt(o.now.change_oi_pcr, 2) : "—", sub: esc(o.now.change_oi_pcr_reason || "put ΔOI / call ΔOI"), cls: "compact" })}
              ${ui.kpi({ label: "ATM", value: TM.fmt(o.now.atm, 0), sub: `Range ${TM.fmt(o.now.strike_range[0], 0)}–${TM.fmt(o.now.strike_range[1], 0)} · expiry ${TM.dateShort(o.now.expiry)}`, cls: "compact" })}</div>
              <div id="dv-pcr"></div>` : ui.empty("No option chain for this instrument", "The demo simulates option chains for NIFTY, BANKNIFTY and FINNIFTY only.") })}
          </div>
          <div class="grid g-2">${f ? ui.card({ title: "Futures history", body: '<div id="dv-ft"></div>', flush: true }) : ""}
          ${o && o.strikes.length ? ui.card({ title: "Option chain", sub: `${o.now.strikes_used} strikes used · Put OI (left) vs Call OI (right)`, body: '<div id="dv-chain"></div>' }) : ""}</div>`;
        if (f) {
          TM.charts.bars(body.querySelector("#dv-oi"), { height: 170, label: "Open interest", yFmt: (v) => TM.compact(v),
            items: f.history.map((h) => ({ label: TM.dateShort(h.date), value: h.oi, color: h.price_change_pct >= 0 ? "var(--up)" : "var(--down)", opacity: 0.75 })) });
          ui.table(body.querySelector("#dv-ft"), { compact: true, maxHeight: 360, rows: f.history.slice().reverse(), columns: [
            { key: "date", label: "Date", render: (h) => TM.date(h.date) }, { key: "price", label: "Price", num: true, render: (h) => TM.fmt(h.price) },
            { key: "price_change_pct", label: "Price Δ", num: true, render: (h) => ui.chg(h.price_change_pct) },
            { key: "oi", label: "OI", num: true, render: (h) => TM.compact(h.oi) }, { key: "oi_change_pct", label: "ΔOI", num: true, render: (h) => ui.chg(h.oi_change_pct) },
            { key: "state", label: "State", render: (h) => `<span class="${/LONG BUILD|SHORT COVER/.test(h.state) ? "up" : /SHORT BUILD|LONG UNWIND/.test(h.state) ? "down" : "muted"}">${esc(TM.title(h.state))}</span>` },
          ] });
        }
        if (o && o.now.available) {
          TM.charts.line(body.querySelector("#dv-pcr"), { height: 170, label: "PCR history", yFmt: (v) => TM.fmt(v, 2), xFmt: TM.dateShort,
            series: [{ name: "PCR", color: "var(--accent)", data: o.history.map((h) => ({ x: h.date, y: h.pcr })) },
              { name: "ΔOI PCR", color: "var(--warn)", dash: "4 3", data: o.history.map((h) => ({ x: h.date, y: h.change_oi_pcr })) }] });
          TM.charts.chain(body.querySelector("#dv-chain"), o.strikes, { atm: o.now.atm });
        }
      });
      ui.bindSeg(el, "dd", (v) => { st.days = +v; draw(); });
      bindSymbol(el, draw);
      draw();
    },
  };

  // ------------------------------------------------------------------ Candlesticks
  TM.views.candles = {
    title: "Candlesticks", icon: "candles", group: "Analysis",
    async render(el) {
      el.innerHTML = `<div class="view-head"><div><h1>Candlestick reversals</h1><p>Every pattern is a formula on body, range, wicks, close location, the previous candle and ATR. Nothing is judged by eye.</p></div>
        <div class="actions">${symbolBar()}</div></div><div id="cd"></div>`;
      const body = el.querySelector("#cd");
      const draw = () => ui.load(body, async () => {
        const d = await TM.api.get("/api/candles", { symbol: TM.state.symbol, tf: "1D", lookback: 60 });
        body.innerHTML = `<div class="grid g-main">${ui.card({ title: `${esc(d.symbol)} patterns`, sub: `last ${d.lookback} bars`, body: '<div id="cd-t"></div>', flush: true })}
          ${ui.card({ title: "Definitions", body: `<ul class="checklist">${d.definitions.map((x) => `<li class="na"><span class="ic">${TM.icon("candles")}</span><span><b>${esc(x.pattern)}</b><br><span class="muted">${esc(x.rule)}</span></span></li>`).join("")}</ul>` })}</div>`;
        ui.table(body.querySelector("#cd-t"), { rows: d.rows, empty: ui.empty("No reversal patterns in this window"), columns: [
          { key: "time", label: "Date", render: (r) => TM.date(r.time) },
          { key: "pattern", label: "Pattern", render: (r) => `<b class="${r.direction === "BULLISH" ? "up" : "down"}">${esc(TM.title(r.pattern))}</b>` },
          { key: "confidence", label: "Confidence", num: true, render: (r) => `${TM.pct(r.confidence, 0)}` },
          { key: "body_ratio", label: "Body", num: true, render: (r) => TM.pct(r.body_ratio, 0) },
          { key: "upper_wick_ratio", label: "Upper wick", num: true, render: (r) => TM.pct(r.upper_wick_ratio, 0) },
          { key: "lower_wick_ratio", label: "Lower wick", num: true, render: (r) => TM.pct(r.lower_wick_ratio, 0) },
          { key: "atr_range", label: "Range/ATR", num: true, render: (r) => TM.fmt(r.atr_range, 2) },
          { key: "close_location", label: "Close loc.", num: true, render: (r) => TM.pct(r.close_location, 0) },
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
