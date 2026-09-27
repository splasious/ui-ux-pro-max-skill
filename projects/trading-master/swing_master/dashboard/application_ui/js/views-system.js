/* Trading Master -- system screens: data health and settings (incl. the theme gallery). */
(function () {
  "use strict";
  const TM = window.TM, ui = TM.ui, esc = TM.esc;

  TM.views.health = {
    title: "Data Health", icon: "heart", group: "System",
    async render(el) {
      const d = await TM.api.get("/api/health");
      el.innerHTML = `<div class="view-head"><div><h1>System & data health</h1><p>Missing feeds are shown as missing. Nothing is silently substituted.</p></div></div>
        <div class="grid g-4">${d.feeds.map((f) => `<div class="kpi compact"><div class="label"><span>${esc(f.name)}</span>${ui.status(f.status)}</div><div class="sub" style="margin-top:4px">${esc(f.detail)}</div></div>`).join("")}</div>
        <div class="grid g-2">
          ${ui.card({ title: "Engine", body: ui.kv([["Status", ui.status(d.status === "ready" ? "OK" : "PENDING")], ["Symbols analysed", String(d.stats.symbols)], ["Bars processed", TM.fmt(d.stats.bars, 0)],
            ["Confirmed pivots", TM.fmt(d.stats.pivots, 0)], ["Zones created", TM.fmt(d.stats.zones, 0)], ["Setup evaluations", TM.fmt(d.stats.evaluations, 0)],
            ...Object.entries(d.timings).map(([k, v]) => [esc(k.replace(/_s$/, "").replace(/_/g, " ")), `${TM.fmt(v, 2)} s`])]) })}
          ${ui.card({ title: "Notification channel errors", body: d.notification_errors.length ? ui.checklist(d.notification_errors.map((e) => ({ ok: false, text: e }))) : ui.empty("No channel errors", "", "check") })}
        </div>
        ${ui.card({ title: "Structured log", sub: "latest first", body: '<div id="hl-log"></div>', flush: true })}`;
      ui.table(el.querySelector("#hl-log"), { compact: true, rows: d.logs, maxHeight: 420, empty: ui.empty("No log lines yet"), columns: [
        { key: "ts", label: "Time", render: (l) => `<span class="log-line">${esc(l.ts)}</span>` }, { key: "level", label: "Level", render: (l) => ui.status(l.level === "INFO" ? "OK" : l.level) },
        { key: "category", label: "Category" }, { key: "message", label: "Message", cls: "wrap", render: (l) => `<span class="log-line">${esc(l.message)}${l.data ? " " + esc(JSON.stringify(l.data)) : ""}</span>` },
      ] });
    },
  };

  TM.views.settings = {
    title: "Settings", icon: "gear", group: "System",
    async render(el) {
      const d = await TM.api.get("/api/settings");
      const readOnly = TM.api.isStatic();
      el.innerHTML = `<div class="view-head"><div><h1>Settings</h1><p>One configuration object drives backtest, scanner and paper execution alike.</p></div></div>
        ${ui.card({ title: "Theme", sub: "five interchangeable skins", body: `<div class="zone-grid" id="st-skins">${TM.skins.map(skinCard).join("")}</div>
          <div class="toolbar" style="margin-top:12px"><label class="switch"><input type="checkbox" id="st-hollow" ${TM.store.get("tm.hollow", true) ? "checked" : ""}><span class="track"></span>Hollow up-candles (direction readable without colour)</label>
          <label class="switch"><input type="checkbox" id="st-auto" ${TM.state.skin === "auto" ? "checked" : ""}><span class="track"></span>Follow system light / dark (Daylight / Midnight)</label></div>` })}
        <div class="grid g-2">
          ${ui.card({ title: "Strategy parameters", sub: readOnly ? "read-only in the static preview" : "applying re-runs the full analysis", body: `<form id="st-form" class="kv left" style="grid-template-columns:minmax(160px,1fr) minmax(0,1fr)">
              ${d.editable.map((p) => `<dt><label for="p-${p.key}">${esc(p.key)}</label><div class="muted" style="font-size:11.5px">${esc(p.help)}</div></dt><dd>${field(p, d.choices, readOnly)}</dd>`).join("")}
            </form>
            ${readOnly ? "" : `<div class="toolbar" style="margin-top:12px"><button class="btn btn-primary" type="button" id="st-apply">${TM.icon("refresh")} Apply & rebuild</button><span class="muted" id="st-msg"></span></div>`}` })}
          <div class="grid">
            ${ui.card({ title: "Confluence weights", body: weights(d.weights.confluence) })}
            ${ui.card({ title: "Zone-score weights", body: weights(d.weights.zone) })}
            ${ui.card({ title: "Execution & secrets", body: ui.kv([["Data source", esc(d.app.data_source)],
              ["Execution mode", `<select class="select" id="st-mode" aria-label="Execution mode" ${readOnly ? "disabled" : ""}>${TM.state.meta.modes.map((x) => `<option value="${x}" ${x === d.app.execution_mode ? "selected" : ""} ${x === "AUTO" && !d.app.live_trading_enabled ? "disabled" : ""}>${TM.title(x)}${x === "AUTO" && !d.app.live_trading_enabled ? " (locked)" : ""}</option>`).join("")}</select>`],
              ["Live trading", d.app.live_trading_enabled ? ui.status("ON") : `${ui.status("OFF")} <span class="muted">set TM_LIVE_TRADING_ENABLED=1</span>`],
              ...Object.entries(d.app.secrets).map(([k, v]) => [esc(k), `<code>${esc(v)}</code> <span class="muted">env var</span>`])]),
              note: "Secrets are read from environment variables only and are never stored in files or shown here." })}
          </div>
        </div>
        ${ui.card({ title: "Full configuration", body: `<details class="more"><summary>Show all ${Object.keys(d.config).length} parameters</summary><div class="table-wrap" style="margin-top:8px"><table class="table compact"><tbody>
          ${Object.entries(d.config).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="num">${esc(typeof v === "object" ? JSON.stringify(v) : String(v))}</td></tr>`).join("")}</tbody></table></div></details>` })}`;
      el.querySelectorAll("[data-skin-opt]").forEach((b) => b.addEventListener("click", () => { TM.applySkin(b.dataset.skinOpt); TM.render(); }));
      el.querySelector("#st-auto").addEventListener("change", (e) => { TM.applySkin(e.target.checked ? "auto" : "midnight"); TM.render(); });
      el.querySelector("#st-hollow").addEventListener("change", (e) => { TM.store.set("tm.hollow", e.target.checked); TM.toast(e.target.checked ? "Up candles drawn hollow" : "Up candles drawn filled"); });
      const mode = el.querySelector("#st-mode");
      mode.addEventListener("change", async () => {
        try { await TM.api.post("/api/mode", { mode: mode.value }); TM.state.meta.execution_mode = mode.value; TM.toast(`Execution mode: ${TM.title(mode.value)}`); }
        catch (err) { TM.toast(err.message); mode.value = d.app.execution_mode; }
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
        try { await TM.api.post("/api/settings", { overrides }); TM.toast("Settings applied"); await TM.refreshShell(); TM.render(); }
        catch (err) { msg.textContent = err.message; apply.disabled = false; }
      });
    },
  };

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
    const active = (TM.state.skin === "auto" ? TM.resolvedSkin() : TM.state.skin) === s.id;
    return `<button type="button" class="skin-opt" data-skin-opt="${s.id}" aria-checked="${active}" role="radio" style="border:1px solid var(--border);padding:12px;display:grid;gap:8px;text-align:left">
      <span class="swatch" style="width:100%;height:42px">${s.swatch.map((c) => `<i style="background:${c}"></i>`).join("")}</span>
      <span><b>${esc(s.name)}</b><small>${esc(s.desc)}</small></span></button>`;
  }
})();
