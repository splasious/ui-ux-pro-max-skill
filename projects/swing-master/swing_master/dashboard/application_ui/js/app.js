/* Swing Master -- application shell: skins, top bar, sidebar, KPI ribbon, routing and boot. */
(function () {
  "use strict";
  const SM = window.SM, ui = SM.ui, esc = SM.esc;

  // ------------------------------------------------------------------ skins
  SM.skins = [
    { id: "midnight", name: "Midnight Teal", desc: "Deep navy, teal mark, blue controls", tagline: "Plan · Analyse · Execute · Improve",
      swatch: ["#071526", "#0b1e33", "#1f7df2", "#19c9a3", "#2ccf97", "#ff6275"] },
    { id: "imperial", name: "Imperial Gold", desc: "Black lacquer with brushed gold", tagline: "Discipline · Structure · Consistency",
      swatch: ["#0a0b0d", "#131417", "#d8aa52", "#ecc97b", "#3ec783", "#ef5a5f"] },
    { id: "ultraviolet", name: "Ultraviolet", desc: "Indigo night, violet and cyan", tagline: "From structure to a clear decision.",
      swatch: ["#0a0918", "#11102a", "#7a5cff", "#3ee6f0", "#2edca3", "#ff5b79"] },
    { id: "daylight", name: "Daylight", desc: "Bright workspace, cobalt accents", tagline: "Structured charts. Disciplined execution.",
      swatch: ["#f3f6fb", "#ffffff", "#1766f0", "#ef8a00", "#0c8f5a", "#d3343f"] },
    { id: "terminal", name: "Cyan Terminal", desc: "Instrument-panel cyan on deep sea", tagline: "Plan · Analyze · Execute · Improve",
      swatch: ["#06101b", "#0a1928", "#17d0ef", "#f5b83d", "#25d796", "#ff5a69"] },
  ];
  const mql = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  SM.resolvedSkin = () => {
    if (SM.state.skin !== "auto") return SM.state.skin;
    const host = document.documentElement.getAttribute("data-theme");
    if (host === "dark") return "midnight";
    if (host === "light") return "daylight";
    return mql && mql.matches ? "midnight" : "daylight";
  };
  SM.applySkin = (id) => {
    SM.state.skin = id;
    SM.store.set("sm.skin", id);
    const root = document.documentElement;
    if (id === "auto") root.removeAttribute("data-skin"); else root.setAttribute("data-skin", id);
    const s = SM.skins.find((x) => x.id === SM.resolvedSkin()) || SM.skins[0];
    const tag = document.getElementById("brand-tag");
    if (tag) tag.textContent = s.tagline;
    document.querySelectorAll("[data-skin-pick]").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.skinPick === id)));
  };
  if (mql && mql.addEventListener) mql.addEventListener("change", () => SM.state.skin === "auto" && SM.applySkin("auto"));

  // ------------------------------------------------------------------ nav
  const NAV = [
    ["Market", ["overview", "scanner"]],
    ["Analysis", ["structure", "zones", "profile", "positioning", "derivatives", "candles"]],
    ["Execution", ["setup", "trades", "risk"]],
    ["Research", ["backtest", "walkforward", "journal", "rejected", "reports"]],
    ["System", ["health", "settings"]],
  ];

  const MARK = `<svg class="brand-mark" viewBox="0 0 40 34" aria-hidden="true">
    <g class="m-mountain"><path d="M2 32 15 8l7 12 4-6 12 18z" fill="currentColor" opacity="0.95"/><path d="M15 8l5 9-5 15H2z" fill="var(--accent)" opacity="0.85"/></g>
    <g class="m-crown" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linejoin="round"><path d="M5 27 3 10l9 7 8-12 8 12 9-7-2 17z"/><path d="M6 31h28"/></g>
    <g class="m-bars" fill="currentColor"><rect x="4" y="20" width="6" height="12" rx="1"/><rect x="13" y="13" width="6" height="19" rx="1"/><rect x="22" y="7" width="6" height="25" rx="1"/><rect x="31" y="2" width="6" height="30" rx="1"/></g></svg>`;

  function shell() {
    const m = SM.state.meta;
    const stat = SM.api.isStatic();
    const sidebar = NAV.map(([g, items]) => `<nav class="nav-group" aria-label="${g}"><div class="nav-label">${g}</div>${items.map((id) => {
      const v = SM.views[id];
      return `<a class="nav-item" href="#${id}" data-nav="${id}" title="${esc(v.title)}">${SM.icon(v.icon)}<span>${esc(v.title)}</span>${id === "trades" ? '<span class="count" id="nav-trades" hidden></span>' : ""}</a>`;
    }).join("")}</nav>`).join("");
    document.getElementById("app").innerHTML = `
      <div class="shell" id="shell">
        <header class="topbar" id="topbar">
          <button class="iconbtn menu-btn" type="button" id="menu-btn" aria-label="Open navigation" aria-expanded="false">${SM.icon("menu")}</button>
          <a class="brand" href="#overview" aria-label="Swing Master home">${MARK}<span class="brand-text"><span class="brand-name">Swing Master</span><span class="brand-tag" id="brand-tag"></span></span></a>
          ${m.demo ? '<span class="badge b-warn brand-demo" title="Fictional demo data">Demo</span>' : ""}
          <div class="demo-plate" role="note">${m.demo ? `<b>Demo · Illustrative data</b><small>${stat ? "Static preview · fictional data · no guaranteed returns" : "Fictional data for education and demonstration · no guaranteed returns"}</small>` : `<b>${esc(m.source)}</b><small>As of ${SM.dateTime(m.as_of)}</small>`}</div>
          <div class="top-ctx">
            <div class="ctx-field"><label for="ctx-market">Market</label><select class="select" id="ctx-market"><option>NSE</option></select></div>
            <div class="ctx-field ctx-uni"><label for="ctx-uni">Universe</label><select class="select" id="ctx-uni" title="${esc(m.universe_name)}"><option>${m.universe_info && m.universe_info.mode === "ALL" ? "All" : "F&amp;O"} (${m.universe.length})</option></select></div>
            <div class="ctx-field search"><label for="ctx-search">Symbol</label>${SM.icon("search")}<input class="input" id="ctx-search" type="search" autocomplete="off" placeholder="Search symbol (/)" aria-autocomplete="list" aria-controls="ctx-results" value="${esc(SM.state.symbol)}"><div class="search-results" id="ctx-results" role="listbox" hidden></div></div>
            <div class="ctx-field ctx-tf"><label for="ctx-tf">Timeframe</label><select class="select" id="ctx-tf">${m.timeframes.map((t) => `<option ${t === SM.state.tf ? "selected" : ""}>${t}</option>`).join("")}</select></div>
          </div>
          <div class="top-actions">
            <span class="acct-seg" title="Execution mode: ${esc(SM.title(m.execution_mode))}. Change it in Settings.">${ui.seg("acct", [["paper", "Paper"], ["live", "Live"]], "paper", true)}</span>
            <span class="status-pill hide-sm hide-md" title="Market data feed"><span class="status-dot ${m.demo ? "warn" : ""}"></span>${m.demo ? "Demo feed" : "Data OK"}</span>
            <span class="status-pill hide-sm hide-md" title="Broker connection"><span class="status-dot off"></span>Broker: paper</span>
            <div style="position:relative"><button class="iconbtn" type="button" id="skin-btn" aria-haspopup="true" aria-expanded="false" aria-label="Choose theme">${SM.icon("palette")}</button>
              <div class="skin-pop" id="skin-pop" role="radiogroup" aria-label="Theme" hidden><h4>Theme</h4>
                <button type="button" class="skin-opt" role="radio" data-skin-pick="auto" aria-checked="false"><span class="swatch"><i style="background:#f3f6fb"></i><i style="background:#071526"></i></span><span><b>Auto</b><small>Follow light / dark setting</small></span></button>
                ${SM.skins.map((s) => `<button type="button" class="skin-opt" role="radio" data-skin-pick="${s.id}" aria-checked="false"><span class="swatch">${s.swatch.slice(0, 4).map((c) => `<i style="background:${c}"></i>`).join("")}</span><span><b>${esc(s.name)}</b><small>${esc(s.desc)}</small></span></button>`).join("")}</div></div>
            <div style="position:relative"><button class="iconbtn" type="button" id="bell-btn" aria-haspopup="true" aria-expanded="false" aria-label="Notifications">${SM.icon("bell")}<span class="dot" id="bell-dot" hidden></span></button>
              <div class="skin-pop" id="bell-pop" hidden style="width:340px;max-height:420px;overflow-y:auto"></div></div>
            <span class="avatar" aria-hidden="true">SM</span>
          </div>
        </header>
        <aside class="sidebar" id="sidebar">${sidebar}
          <div class="side-foot">
            <div class="side-card"><div class="row"><span class="muted">Market</span><b>NSE</b></div><div class="row" title="${esc(m.universe_name)}"><span class="muted">Universe</span><b>${m.universe_info && m.universe_info.mode === "ALL" ? "All" : "F&amp;O"} · ${esc(String(m.universe.length))}</b></div>
              <div class="row"><span class="muted">Mode</span><b>${esc(SM.title(m.execution_mode))}</b></div></div>
            <a class="side-card side-theme" href="#settings" style="display:none;align-items:center;gap:8px">${SM.icon("palette")}<b>Theme</b><span class="muted" style="margin-left:auto">${esc((SM.skins.find((s) => s.id === SM.resolvedSkin()) || {}).name || "")}</span></a>
            <div class="side-card"><h4><span class="status-dot"></span>Paper trading <span class="badge b-up" style="margin-left:auto">On</span></h4><span class="muted">Replay of recent sessions through the live decision engine.</span></div>
            <div class="side-card" id="side-risk"></div>
          </div></aside>
        <div class="nav-scrim" id="nav-scrim"></div>
        <main class="main" id="main"><section class="ribbon" id="ribbon" aria-label="Market summary"></section><div id="view" class="grid"></div></main>
      </div>`;
    wireShell();
    SM.applySkin(SM.state.skin);
  }

  function wireShell() {
    const $ = (id) => document.getElementById(id);
    const shellEl = $("shell");
    $("menu-btn").addEventListener("click", () => {
      const open = !shellEl.classList.contains("nav-open");
      shellEl.classList.toggle("nav-open", open);
      $("menu-btn").setAttribute("aria-expanded", String(open));
    });
    const closeNav = () => { shellEl.classList.remove("nav-open"); $("menu-btn").setAttribute("aria-expanded", "false"); };
    $("sidebar").addEventListener("click", (e) => { if (e.target.closest("a")) closeNav(); });
    $("nav-scrim").addEventListener("click", closeNav);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && shellEl.classList.contains("nav-open")) closeNav(); });
    // popovers
    const pop = (btn, box, onOpen) => {
      $(btn).addEventListener("click", (e) => {
        e.stopPropagation();
        const open = $(box).hidden;
        document.querySelectorAll(".skin-pop").forEach((p) => { p.hidden = true; });
        $(box).hidden = !open;
        $(btn).setAttribute("aria-expanded", String(open));
        if (open && onOpen) onOpen();
      });
    };
    pop("skin-btn", "skin-pop");
    pop("bell-btn", "bell-pop", renderBell);
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".skin-pop")) document.querySelectorAll(".skin-pop").forEach((p) => { p.hidden = true; });
      if (!e.target.closest(".search")) $("ctx-results").hidden = true;
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") document.querySelectorAll(".skin-pop").forEach((p) => { p.hidden = true; });
      if ((e.key === "/" || (e.key === "k" && (e.ctrlKey || e.metaKey))) && !/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) {
        e.preventDefault(); $("ctx-search").focus(); $("ctx-search").select();
      }
    });
    document.querySelectorAll("[data-skin-pick]").forEach((b) => b.addEventListener("click", () => {
      SM.applySkin(b.dataset.skinPick);
      if (SM.route() === "settings" || SM.route() === "overview") SM.render(); else redrawCharts();
    }));
    // search
    const input = $("ctx-search"), res = $("ctx-results");
    let sel = 0, matches = [];
    const show = () => {
      const q = input.value.trim().toUpperCase();
      matches = SM.state.meta.universe.filter((u) => !q || u.symbol.includes(q) || u.name.toUpperCase().includes(q)).slice(0, 10);
      sel = 0;
      res.innerHTML = matches.map((u, i) => `<button type="button" role="option" aria-selected="${i === 0}" data-sym="${esc(u.symbol)}"><b>${esc(u.symbol)}</b><span class="muted">${esc(u.name)}</span></button>`).join("") || '<div class="empty">No match</div>';
      res.hidden = false;
    };
    const choose = (sym) => { res.hidden = true; input.value = sym; SM.setState({ symbol: sym }); };
    input.addEventListener("focus", show);
    input.addEventListener("input", show);
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        sel = Math.max(0, Math.min(matches.length - 1, sel + (e.key === "ArrowDown" ? 1 : -1)));
        res.querySelectorAll("button").forEach((b, i) => b.setAttribute("aria-selected", String(i === sel)));
      } else if (e.key === "Enter" && matches[sel]) { e.preventDefault(); choose(matches[sel].symbol); input.blur(); }
      else if (e.key === "Escape") { res.hidden = true; }
    });
    res.addEventListener("click", (e) => { const b = e.target.closest("[data-sym]"); if (b) choose(b.dataset.sym); });
    $("ctx-tf").addEventListener("change", (e) => SM.setState({ tf: e.target.value }));
    ui.bindSeg(document.getElementById("topbar"), "acct", (v) => {
      if (v === "live") {
        SM.toast("Live execution is locked until research is validated and a broker is configured");
        document.querySelectorAll('[data-seg="acct"]').forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.value === "paper")));
      }
    });
    const setH = () => document.documentElement.style.setProperty("--topbar-h", $("topbar").offsetHeight + "px");
    setH();
    window.addEventListener("resize", SM.debounce(setH, 100));
  }

  function renderBell() {
    const items = (SM.state.overview && SM.state.overview.notifications) || [];
    document.getElementById("bell-pop").innerHTML = `<h4>Notifications</h4>${items.length ? items.map((n) => `<div style="padding:8px 4px;border-bottom:1px solid var(--border);font-size:12.5px">
      <b>${esc(n.title)}</b> <span class="muted">${esc(n.symbol || "")}</span><div class="muted">${esc(n.time ? SM.date(n.time) : "")} ${n.reason ? "· " + esc(n.reason) : ""} ${SM.isNum(n.price) ? "· " + SM.fmt(n.price) : ""}</div></div>`).join("")
      : ui.empty("No notifications")}<div class="muted" style="font-size:11.5px;padding-top:8px">Telegram delivery switches on when TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set.</div>`;
  }

  // ------------------------------------------------------------------ ribbon
  function ribbon(ov) {
    const mk = ov.market, ix = mk.index, rg = mk.regime, br = mk.breadth, vx = mk.vix, h = mk.health;
    document.getElementById("ribbon").innerHTML = `
      ${ui.kpi({ label: esc(ix.name), value: SM.fmt(ix.price), sub: `<span class="${SM.dir(ix.change)}">${SM.signed(ix.change)}</span><span class="${SM.dir(ix.change)}">${SM.signed(ix.change_pct)}%</span>`,
        spark: SM.charts.spark(ix.series, { color: ix.change >= 0 ? "var(--up)" : "var(--down)" }) })}
      ${ui.kpi({ label: "Market regime", value: `<span class="${rg.label === "UPTREND" ? "up" : rg.label === "DOWNTREND" ? "down" : "warn"}">${esc(rg.label)}</span>`, valueCls: "word", sub: esc(rg.detail) })}
      ${ui.kpi({ label: `Breadth <span class="muted" style="font-weight:500">(${br.universe})</span>`, value: `<span class="up">${br.advances}</span> <span class="muted">/</span> <span class="down">${br.declines}</span>`,
        sub: `<div style="width:100%"><div class="split" role="img" aria-label="${SM.pct(br.adv_pct, 0)} advancing"><span class="a" style="width:${br.adv_pct * 100}%"></span><span class="d" style="width:${(br.declines / Math.max(1, br.universe)) * 100}%"></span></div>
          <div style="display:flex;justify-content:space-between;margin-top:3px"><span class="up">${SM.pct(br.adv_pct, 0)} adv</span><span>${br.above_50dma} above 50-DMA</span></div></div>` })}
      ${vx ? ui.kpi({ label: esc(vx.label), value: SM.fmt(vx.value), sub: `<span class="${SM.dir(-vx.change)}">${SM.signed(vx.change)}</span><span class="${SM.dir(-vx.change)}">${SM.signed(vx.change_pct)}%</span>`,
        spark: SM.charts.spark(vx.series, { color: "var(--down)", area: false }) }) : ui.kpi({ label: "Volatility index", value: "—", sub: ui.status("UNAVAILABLE") })}
      ${ui.kpi({ label: "Data health", value: `<span class="${h.ok ? "up" : "down"}" style="font-size:14px;display:inline-flex;align-items:center;gap:8px"><span class="status-dot ${h.ok ? "" : "warn"}"></span>${esc(h.label)}</span>`,
        sub: Object.entries(h.feeds).map(([k, v]) => `<span title="${esc(k)}">${esc(SM.title(k.replace("_feed", "")))} ${v === "UNAVAILABLE" ? '<span class="muted">✕</span>' : '<span class="up">✓</span>'}</span>`).join("") })}`;
    const acc = ov.account;
    const side = document.getElementById("side-risk");
    side.innerHTML = `<h4>${SM.icon("shield")} Risk limits (session)</h4>
      <div class="row"><span class="muted">Open risk</span><b class="num">${SM.inr(acc.open_risk)}</b></div>
      <div class="row"><span class="muted">Max open risk</span><b class="num">${SM.fmt(acc.max_risk_pct, 1)}%</b></div>
      <div class="row"><span class="muted">Risk / trade</span><b class="num">${SM.fmt(acc.risk_per_trade_pct, 1)}%</b></div>
      <div class="row"><span class="muted">Open positions</span><b class="num">${acc.open_positions}</b></div>`;
    const cnt = document.getElementById("nav-trades");
    if (acc.open_positions) { cnt.hidden = false; cnt.textContent = acc.open_positions; }
    document.getElementById("bell-dot").hidden = !(ov.notifications && ov.notifications.length);
  }

  // ------------------------------------------------------------------ render
  let token = 0;
  SM.render = async () => {
    const name = SM.route();
    const view = SM.views[name];
    document.body.setAttribute("data-route", name);
    document.querySelectorAll("[data-nav]").forEach((a) => {
      if (a.dataset.nav === name) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    const el = document.getElementById("view");
    const my = ++token;
    try {
      const tmp = document.createElement("div");
      tmp.className = "grid";
      tmp.innerHTML = ui.loading();
      el.replaceWith(tmp);
      tmp.id = "view";
      await view.render(tmp);
      if (my !== token) return;
    } catch (err) {
      console.error(err);
      document.getElementById("view").innerHTML = ui.error(err);
    }
    const s = document.getElementById("ctx-search");
    if (s && document.activeElement !== s) s.value = SM.state.symbol;
  };
  function redrawCharts() { window.dispatchEvent(new Event("resize")); SM.render(); }

  SM.refreshShell = async () => {
    SM.api.clear();
    const meta = await SM.api.get("/api/meta");
    SM.state.meta = meta;
    const ov = await SM.api.get("/api/overview");
    SM.state.overview = ov;
    ribbon(ov);
  };

  SM.onState((changed) => {
    if (changed.includes("tf")) { const s = document.getElementById("ctx-tf"); if (s) s.value = SM.state.tf; }
    if (changed.includes("symbol") || changed.includes("tf")) SM.render();
  });

  async function boot() {
    const root = document.getElementById("app");
    SM.applySkin(SM.state.skin);
    try {
      const meta = await SM.api.get("/api/meta");
      SM.state.meta = meta;
      if (!meta.universe.some((u) => u.symbol === SM.state.symbol)) SM.state.symbol = meta.universe[0].symbol;
      if (!meta.timeframes.includes(SM.state.tf)) SM.state.tf = "1D";
      shell();
      const ov = await SM.api.get("/api/overview");
      SM.state.overview = ov;
      if (SM.store.get("sm.symbol", null) == null && ov.focus_symbol) SM.state.symbol = ov.focus_symbol;
      ribbon(ov);
      window.addEventListener("hashchange", SM.render);
      await SM.render();
    } catch (err) {
      console.error(err);
      root.innerHTML = `<div style="padding:40px">${ui.error(err)}</div>`;
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
