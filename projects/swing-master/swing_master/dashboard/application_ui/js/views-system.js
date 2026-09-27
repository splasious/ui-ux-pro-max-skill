/* Swing Master -- system screens: data health and settings (incl. the theme gallery). */
(function () {
  "use strict";
  const SM = window.SM, ui = SM.ui, esc = SM.esc;

  SM.views.health = {
    title: "Data Health", icon: "heart", group: "System",
    async render(el) {
      const d = await SM.api.get("/api/health");
      el.innerHTML = `<div class="view-head"><div><h1>System & data health</h1><p>Missing feeds are shown as missing. Nothing is silently substituted.</p></div></div>
        <div class="grid g-4">${d.feeds.map((f) => `<div class="kpi compact"><div class="label"><span>${esc(f.name)}</span>${ui.status(f.status)}</div><div class="sub" style="margin-top:4px">${esc(f.detail)}</div></div>`).join("")}</div>
        <div class="grid g-2">
          ${ui.card({ title: "Engine", body: ui.kv([["Status", ui.status(d.status === "ready" ? "OK" : "PENDING")], ["Symbols analysed", String(d.stats.symbols)], ["Bars processed", SM.fmt(d.stats.bars, 0)],
            ["Confirmed pivots", SM.fmt(d.stats.pivots, 0)], ["Zones created", SM.fmt(d.stats.zones, 0)], ["Setup evaluations", SM.fmt(d.stats.evaluations, 0)],
            ...Object.entries(d.timings).map(([k, v]) => [esc(k.replace(/_s$/, "").replace(/_/g, " ")), `${SM.fmt(v, 2)} s`])]) })}
          ${ui.card({ title: "Notification channel errors", body: d.notification_errors.length ? ui.checklist(d.notification_errors.map((e) => ({ ok: false, text: e }))) : ui.empty("No channel errors", "", "check") })}
        </div>
        ${ui.card({ title: "Audit log" + ui.tip("Structured events for the paper-session window: pivot confirmations, structure changes, zone lifecycle, signals, orders, stops, targets and risk events."),
          sub: "latest first", actions: `<div class="toolbar">${["all", ...Object.keys(d.log_counts || {})].map((c) => `<button type="button" class="chip" data-lc="${esc(c)}" aria-pressed="${c === "all"}">${esc(SM.title(c))} <span class="n">${c === "all" ? d.logs.length : d.log_counts[c]}</span></button>`).join("")}</div>`,
          body: '<div id="hl-log"></div>', flush: true })}`;
      const logT = ui.table(el.querySelector("#hl-log"), { compact: true, rows: d.logs, maxHeight: 460, empty: ui.empty("No log lines yet"), columns: [
        { key: "ts", label: "Time", render: (l) => `<span class="log-line">${esc(l.ts)}</span>` }, { key: "level", label: "Level", render: (l) => ui.status(l.level === "INFO" ? "OK" : l.level) },
        { key: "category", label: "Category" }, { key: "message", label: "Message", cls: "wrap", render: (l) => `<span class="log-line">${esc(l.message)}${l.data ? " " + esc(JSON.stringify(l.data)) : ""}</span>` },
      ] });
      el.querySelectorAll("[data-lc]").forEach((b) => b.addEventListener("click", () => {
        el.querySelectorAll("[data-lc]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
        logT.setRows(b.dataset.lc === "all" ? d.logs : d.logs.filter((l) => l.category === b.dataset.lc));
      }));
    },
  };

  SM.views.settings = {
    title: "Settings", icon: "gear", group: "System",
    async render(el) {
      const d = await SM.api.get("/api/settings");
      const readOnly = SM.api.isStatic();
      el.innerHTML = `<div class="view-head"><div><h1>Settings</h1><p>One configuration object drives backtest, scanner and paper execution alike.</p></div></div>
        ${ui.card({ title: "Theme", sub: "five interchangeable skins", body: `<div class="zone-grid" id="st-skins">${SM.skins.map(skinCard).join("")}</div>
          <div class="toolbar" style="margin-top:12px"><label class="switch"><input type="checkbox" id="st-hollow" ${SM.store.get("sm.hollow", true) ? "checked" : ""}><span class="track"></span>Hollow up-candles (direction readable without colour)</label>
          <label class="switch"><input type="checkbox" id="st-auto" ${SM.state.skin === "auto" ? "checked" : ""}><span class="track"></span>Follow system light / dark (Daylight / Midnight)</label></div>` })}
        <div class="grid g-2">
          ${ui.card({ title: "Strategy parameters", sub: readOnly ? "read-only in the static preview" : "applying re-runs the full analysis", body: `<form id="st-form" class="kv left" style="grid-template-columns:minmax(160px,1fr) minmax(0,1fr)">
              ${d.editable.map((p) => `<dt><label for="p-${p.key}">${esc(p.key)}</label><div class="muted" style="font-size:11.5px">${esc(p.help)}</div></dt><dd>${field(p, d.choices, readOnly)}</dd>`).join("")}
            </form>
            ${readOnly ? "" : `<div class="toolbar" style="margin-top:12px"><button class="btn btn-primary" type="button" id="st-apply">${SM.icon("refresh")} Apply & rebuild</button><span class="muted" id="st-msg"></span></div>`}` })}
          <div class="grid">
            ${ui.card({ title: "Confluence weights", body: weights(d.weights.confluence) })}
            ${ui.card({ title: "Zone-score weights", body: weights(d.weights.zone) })}
            ${ui.card({ title: "Execution & secrets", body: ui.kv([["Data source", esc(d.app.data_source)],
              ["Execution mode", `<select class="select" id="st-mode" aria-label="Execution mode" ${readOnly ? "disabled" : ""}>${SM.state.meta.modes.map((x) => `<option value="${x}" ${x === d.app.execution_mode ? "selected" : ""} ${x === "AUTO" && !d.app.live_trading_enabled ? "disabled" : ""}>${SM.title(x)}${x === "AUTO" && !d.app.live_trading_enabled ? " (locked)" : ""}</option>`).join("")}</select>`],
              ["Live trading", d.app.live_trading_enabled ? ui.status("ON") : `${ui.status("OFF")} <span class="muted">set SM_LIVE_TRADING_ENABLED=1</span>`],
              ...Object.entries(d.app.secrets).map(([k, v]) => [esc(k), `<code>${esc(v)}</code> <span class="muted">env var</span>`])]),
              note: "Secrets are read from environment variables only and are never stored in files or shown here." })}
          </div>
        </div>
        <div class="grid g-2">
          ${ui.card({ title: "Notifications", sub: esc(d.notify ? d.notify.channel.detail : ""), body: '<div id="st-notify"></div>',
            note: "Events are published by the engine and delivered by channels; a failing channel never affects trading." })}
          ${ui.card({ title: "Rule definitions", sub: "centralised in config/", body: `
            <h3 class="section-title">Candlestick thresholds</h3>${ui.kv(Object.entries(d.rules.candlestick).map(([k, v]) => [esc(k.replace(/_/g, " ")), SM.fmt(v, 2)]))}
            <h3 class="section-title" style="margin-top:12px">PCR bands (long bias)</h3>${ui.kv(d.rules.pcr_bands_long.map(([b, f, l]) => [b == null ? "above" : "&lt; " + SM.fmt(b, 1), `${SM.fmt(f, 2)} <span class="muted">${esc(l)}</span>`]))}
            <h3 class="section-title" style="margin-top:12px">Timeframe hierarchy</h3>${ui.kv(Object.entries(d.rules.mtf_hierarchy).map(([k, v]) => [esc(k), `HTF ${esc(v)}`]))}
            <h3 class="section-title" style="margin-top:12px">Positioning percentile bands</h3><div class="muted">${d.rules.positioning_bands.join(" / ")}</div>` })}
        </div>
        ${ui.card({ title: "Full configuration", body: `<details class="more"><summary>Show all ${Object.keys(d.config).length} parameters</summary><div class="table-wrap" style="margin-top:8px"><table class="table compact"><tbody>
          ${Object.entries(d.config).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="num">${esc(typeof v === "object" ? JSON.stringify(v) : String(v))}</td></tr>`).join("")}</tbody></table></div></details>` })}`;
      el.querySelectorAll("[data-skin-opt]").forEach((b) => b.addEventListener("click", () => { SM.applySkin(b.dataset.skinOpt); SM.render(); }));
      el.querySelector("#st-auto").addEventListener("change", (e) => { SM.applySkin(e.target.checked ? "auto" : "midnight"); SM.render(); });
      el.querySelector("#st-hollow").addEventListener("change", (e) => { SM.store.set("sm.hollow", e.target.checked); SM.toast(e.target.checked ? "Up candles drawn hollow" : "Up candles drawn filled"); });
      renderNotify(el.querySelector("#st-notify"), readOnly);
      const mode = el.querySelector("#st-mode");
      mode.addEventListener("change", async () => {
        try { await SM.api.post("/api/mode", { mode: mode.value }); SM.state.meta.execution_mode = mode.value; SM.toast(`Execution mode: ${SM.title(mode.value)}`); }
        catch (err) { SM.toast(err.message); mode.value = d.app.execution_mode; }
      });
      const apply = el.querySelector("#st-apply");
      if (apply) apply.addEventListener("click", async () => {
        const overrides = {};
        d.editable.forEach((p) => {
          const inp = el.querySelector(`#p-${p.key}`);
          const v = p.type === "bool" ? inp.checked : inp.value;
          if (String(v) !== String(p.value)) overrides[p.key] = v;
        });
        const msg = el.querySelector("#st-msg");
        if (!Object.keys(overrides).length) { msg.textContent = "Nothing changed."; return; }
        apply.disabled = true; msg.textContent = "Rebuilding analysis…";
        try { await SM.api.post("/api/settings", { overrides }); SM.toast("Settings applied"); await SM.refreshShell(); SM.render(); }
        catch (err) { msg.textContent = err.message; apply.disabled = false; }
      });
    },
  };

  async function renderNotify(box, ro) {
    try {
      const n = await SM.api.get("/api/notifications", {}, { fresh: true });
      box.innerHTML = `<div class="toolbar" style="margin-bottom:8px">${ui.status(n.channel.enabled ? "ON" : "OFF")} <span class="muted">Telegram</span></div>
        <div style="display:grid;gap:8px">${n.events.map((e) => `<label class="switch"><input type="checkbox" data-ev="${esc(e.type)}" ${e.enabled ? "checked" : ""} ${ro ? "disabled" : ""}><span class="track"></span>${esc(e.title)}</label>`).join("")}</div>`;
      box.querySelectorAll("[data-ev]").forEach((c) => c.addEventListener("change", async () => {
        const events = [...box.querySelectorAll("[data-ev]")].filter((x) => x.checked).map((x) => x.dataset.ev);
        try { await SM.api.post("/api/notifications/config", { events }); SM.toast("Notification events saved"); } catch (err) { SM.toast(err.message); }
      }));
    } catch (err) { box.innerHTML = ui.error(err); }
  }

  function field(p, choices, ro) {
    const dis = ro ? "disabled" : "";
    if (choices[p.key]) return `<select class="select" id="p-${p.key}" ${dis}>${choices[p.key].map((c) => `<option ${c === p.value ? "selected" : ""}>${c}</option>`).join("")}</select>`;
    if (p.type === "bool") return `<label class="switch"><input type="checkbox" id="p-${p.key}" ${p.value ? "checked" : ""} ${dis}><span class="track"></span></label>`;
    return `<input class="input" id="p-${p.key}" value="${esc(p.value)}" inputmode="decimal" style="width:120px" ${dis}>`;
  }
  function weights(w) {
    const total = Object.values(w).reduce((a, b) => a + b.weight, 0);
    return `<div class="brk" style="grid-template-columns:minmax(150px,1.3fr) 2fr auto">${Object.values(w).map((x) => `<span>${esc(x.name)}</span>${ui.bar(x.weight / 15)}<span class="val">${x.weight}</span>`).join("")}
      <span><b>Total</b></span><span></span><span class="val">${total}</span></div>`;
  }
  function skinCard(s) {
    const active = (SM.state.skin === "auto" ? SM.resolvedSkin() : SM.state.skin) === s.id;
    return `<button type="button" class="skin-opt" data-skin-opt="${s.id}" aria-checked="${active}" role="radio" style="border:1px solid var(--border);padding:12px;display:grid;gap:8px;text-align:left">
      <span class="swatch" style="width:100%;height:42px">${s.swatch.map((c) => `<i style="background:${c}"></i>`).join("")}</span>
      <span><b>${esc(s.name)}</b><small>${esc(s.desc)}</small></span></button>`;
  }
})();
