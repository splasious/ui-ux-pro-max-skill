/* Swing Master -- reusable UI pieces (cards, badges, sortable tables, drawer, checklists). */
(function () {
  "use strict";
  const SM = window.SM;
  const esc = SM.esc;
  const ui = (SM.ui = {});

  const STATUS = {
    READY: ["b-up", "check"], ACCEPTED: ["b-up", "check"], CANDIDATE: ["b-up", "check"], PASS: ["b-up", "check"],
    OK: ["b-up", "check"], DIRECT: ["b-up", "check"], ON: ["b-up", "check"], CONFIRMED: ["b-up", "check"],
    WATCH: ["b-info", "eye"], PROXY: ["b-warn", "link"], DEMO: ["b-info", "info"], PAPER: ["b-info", "briefcase"],
    WAIT: ["b-warn", "clock"], WEAK: ["b-warn", "minus"], WARN: ["b-warn", "alert"], PENDING: ["b-warn", "clock"],
    REJECTED: ["b-down", "x"], FAIL: ["b-down", "x"], DOWN: ["b-down", "x"], ERROR: ["b-down", "x"], INVALIDATED: ["b-down", "x"],
    ACTIVE: ["b-solid-accent", "play"], OPEN: ["b-solid-accent", "play"],
    UNAVAILABLE: ["b-muted", "minus"], SKIPPED: ["b-muted", "minus"], "N/A": ["b-muted", "minus"], OFF: ["b-muted", "minus"],
    "NOT CONFIGURED": ["b-muted", "minus"], NOT_APPLICABLE: ["b-muted", "minus"], CLOSED: ["b-muted", "check"],
    FRESH: ["b-up", "check"], "TESTED ONCE": ["b-warn", "clock"], "TESTED MULTIPLE TIMES": ["b-down", "alert"],
    UNCONFIRMED: ["b-warn", "clock"], COMPUTED: ["b-accent", "check"],
  };
  ui.badge = (text, kind = "b-muted", icon = null) =>
    `<span class="badge ${kind}">${icon ? SM.icon(icon) : ""}${esc(text)}</span>`;
  ui.status = (s) => {
    if (s == null || s === "") return '<span class="muted">—</span>';
    const [k, ic] = STATUS[String(s).toUpperCase()] || ["b-muted", null];
    return ui.badge(s, k, ic);
  };
  ui.dirBadge = (d) => d === "LONG" ? ui.badge("Long", "b-up", "up") : d === "SHORT" ? ui.badge("Short", "b-down", "down") : "";
  ui.trendBadge = (t) => {
    const m = { BULLISH: ["b-up", "up"], BEARISH: ["b-down", "down"], TRANSITION: ["b-warn", "activity"],
      CONSOLIDATION: ["b-warn", "minus"], UNDEFINED: ["b-muted", "minus"] };
    const [k, ic] = m[t] || ["b-muted", "minus"];
    return ui.badge(SM.title(t || "—"), k, ic);
  };
  ui.scoreChip = (v, min) => {
    if (!SM.isNum(v)) return '<span class="muted">—</span>';
    const k = min != null ? (v >= min ? "b-up" : v >= min - 10 ? "b-warn" : "b-down") : "b-accent";
    return `<span class="score-chip ${k}">${SM.fmt(v, 0)}</span>`;
  };
  ui.chg = (x, dp = 2, suffix = "%") => `<span class="${SM.dir(x)} num">${SM.signed(x, dp, suffix)}</span>`;
  ui.money = (x) => `<span class="${SM.dir(x)} num">${SM.signedInr(x)}</span>`;

  ui.card = ({ title = "", sub = "", actions = "", body = "", cls = "", note = "", id = "", flush = false }) => `
    <section class="card ${cls}" ${id ? `id="${id}"` : ""}>
      ${title || actions ? `<div class="card-head"><h2 class="card-title">${title}${sub ? ` <small>${sub}</small>` : ""}</h2>
        ${actions ? `<div class="actions">${actions}</div>` : ""}</div>` : ""}
      <div class="card-body ${flush ? "flush" : ""}">${body}</div>
      ${note ? `<div class="card-note">${note}</div>` : ""}
    </section>`;

  ui.kpi = ({ label, value, sub = "", cls = "", spark = "", icon = "", valueCls = "" }) => `
    <div class="kpi ${cls} ${spark ? "has-spark" : ""}">
      ${icon ? SM.icon(icon, "icon") : ""}
      <div class="label"><span>${label}</span></div>
      <div class="value ${valueCls}">${value}</div>
      ${sub ? `<div class="sub">${sub}</div>` : ""}
      ${spark ? `<div class="spark">${spark}</div>` : ""}
    </div>`;

  ui.tip = (text) => `<span class="tip" tabindex="0" role="note" aria-label="${esc(text)}" data-tip="${esc(text)}">?</span>`;
  // one floating tooltip, clamped to the viewport (hover, keyboard focus and tap)
  (function tooltips() {
    let box = null;
    const show = (t) => {
      if (!box) { box = document.createElement("div"); box.className = "floating-tip"; box.setAttribute("role", "tooltip"); document.body.appendChild(box); }
      box.textContent = t.dataset.tip;
      box.hidden = false;
      const r = t.getBoundingClientRect(), bw = box.offsetWidth, bh = box.offsetHeight;
      const left = Math.max(8, Math.min(window.innerWidth - bw - 8, r.left + r.width / 2 - bw / 2));
      const top = r.top - bh - 8 >= 8 ? r.top - bh - 8 : r.bottom + 8;
      box.style.left = left + "px";
      box.style.top = top + "px";
    };
    const hide = () => { if (box) box.hidden = true; };
    document.addEventListener("mouseover", (e) => { const t = e.target.closest && e.target.closest(".tip"); if (t) show(t); });
    document.addEventListener("mouseout", (e) => { if (e.target.closest && e.target.closest(".tip")) hide(); });
    document.addEventListener("focusin", (e) => { if (e.target.classList && e.target.classList.contains("tip")) show(e.target); });
    document.addEventListener("focusout", hide);
    document.addEventListener("click", (e) => { const t = e.target.closest && e.target.closest(".tip"); if (t) { e.stopPropagation(); show(t); } else hide(); }, true);
    window.addEventListener("scroll", hide, { passive: true });
  })();

  ui.kv = (pairs, cls = "") =>
    `<dl class="kv ${cls}">${pairs.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>`;

  ui.bar = (frac, cls = "") =>
    `<div class="bar ${cls}" role="img" aria-label="${SM.isNum(frac) ? Math.round(frac * 100) + "%" : "n/a"}"><span style="width:${SM.isNum(frac) ? Math.max(0, Math.min(1, frac)) * 100 : 0}%"></span></div>`;

  ui.checklist = (items) => `<ul class="checklist">${items.map((it) => {
    const st = it.ok === true ? "ok" : it.ok === false ? "no" : "na";
    const ic = it.ok === true ? "check" : it.ok === false ? "x" : "minus";
    const label = it.ok === true ? "Pass" : it.ok === false ? "Fail" : "Not evaluated";
    return `<li class="${st}"><span class="ic" title="${label}">${SM.icon(ic)}<span class="sr-only">${label}: </span></span><span>${esc(it.text)}</span></li>`;
  }).join("")}</ul>`;

  ui.empty = (title, text = "", icon = "info") =>
    `<div class="empty">${SM.icon(icon)}<b>${esc(title)}</b>${text ? `<span>${esc(text)}</span>` : ""}</div>`;
  ui.notice = (html, kind = "") => `<div class="notice ${kind}">${SM.icon(kind === "info" ? "info" : "alert")}<div>${html}</div></div>`;
  ui.loading = () => `<div class="loading" role="status">Loading…</div>`;
  ui.error = (err) => err instanceof SM.Unavailable
    ? ui.empty("Not in the static preview", err.message, "lock")
    : ui.empty("Could not load this data", err && err.message ? err.message : String(err), "alert");

  ui.seg = (name, options, value, sm = false) =>
    `<div class="seg ${sm ? "sm" : ""}" role="group" aria-label="${esc(name)}">${options.map((o) => {
      const [v, label, disabled] = Array.isArray(o) ? o : [o, o, false];
      return `<button type="button" data-seg="${esc(name)}" data-value="${esc(v)}" aria-pressed="${String(v) === String(value)}" ${disabled ? "disabled" : ""}>${esc(label)}</button>`;
    }).join("")}</div>`;
  ui.bindSeg = (root, name, fn) => {
    root.querySelectorAll(`[data-seg="${CSS.escape(name)}"]`).forEach((b) =>
      b.addEventListener("click", () => {
        root.querySelectorAll(`[data-seg="${CSS.escape(name)}"]`).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
        fn(b.dataset.value);
      }));
  };

  ui.symbolSelect = (id, value, filter) => {
    const uni = (SM.state.meta && SM.state.meta.universe) || [];
    const list = filter ? uni.filter(filter) : uni;
    return `<select class="select" id="${id}" aria-label="Symbol">${list.map((u) =>
      `<option value="${esc(u.symbol)}" ${u.symbol === value ? "selected" : ""}>${esc(u.symbol)}</option>`).join("")}</select>`;
  };

  // ------------------------------------------------------------------ sortable table
  ui.table = (el, cfg) => {
    const state = { key: cfg.sortKey || null, dir: cfg.sortDir || "desc", open: new Set() };
    function val(row, col) { return col.sortValue ? col.sortValue(row) : row[col.key]; }
    function draw() {
      let rows = cfg.rows.slice();
      if (state.key) {
        const col = cfg.columns.find((c) => c.key === state.key);
        rows.sort((a, b) => {
          const x = val(a, col), y = val(b, col);
          if (x == null && y == null) return 0;
          if (x == null) return 1;
          if (y == null) return -1;
          const r = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
          return state.dir === "asc" ? r : -r;
        });
      }
      if (!rows.length) { el.innerHTML = cfg.empty || ui.empty("Nothing to show"); return; }
      const head = cfg.columns.map((c) => {
        const sort = state.key === c.key ? (state.dir === "asc" ? "ascending" : "descending") : "none";
        const inner = c.sort === false ? esc(c.label) : `<button type="button" data-sort="${esc(c.key)}">${esc(c.label)}</button>`;
        return `<th scope="col" class="${c.num ? "num" : ""}" aria-sort="${sort}" ${c.title ? `title="${esc(c.title)}"` : ""}>${inner}</th>`;
      }).join("");
      const body = rows.map((r, i) => {
        const key = cfg.rowKey ? cfg.rowKey(r) : i;
        const cells = cfg.columns.map((c) => `<td data-label="${esc(c.label)}" class="${c.num ? "num" : ""} ${c.cls || ""} ${c.sm === false ? "sm-hide" : ""}">${c.render ? c.render(r) : esc(r[c.key] == null ? "—" : r[c.key])}</td>`).join("");
        const click = cfg.onRow || cfg.expand;
        let html = `<tr class="${click ? "clickable" : ""}" data-key="${esc(key)}" ${click ? 'tabindex="0"' : ""}>${cells}</tr>`;
        if (cfg.expand && state.open.has(String(key))) html += `<tr class="expand"><td colspan="${cfg.columns.length}">${cfg.expand(r)}</td></tr>`;
        return html;
      }).join("");
      el.innerHTML = `<div class="table-wrap" style="${cfg.maxHeight ? `max-height:${cfg.maxHeight}px;overflow-y:auto` : ""}"><table class="table ${cfg.compact ? "compact" : ""} ${cfg.cards === false ? "" : "responsive"}">
        ${cfg.caption ? `<caption class="sr-only">${esc(cfg.caption)}</caption>` : ""}<thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
      el.querySelectorAll("th button[data-sort]").forEach((b) => b.addEventListener("click", () => {
        const k = b.dataset.sort;
        state.dir = state.key === k && state.dir === "desc" ? "asc" : "desc";
        state.key = k;
        draw();
      }));
      el.querySelectorAll("tbody tr[data-key]").forEach((tr) => {
        const act = () => {
          const key = tr.dataset.key;
          const row = rows.find((r, i) => String(cfg.rowKey ? cfg.rowKey(r) : i) === key);
          if (cfg.expand) { state.open.has(key) ? state.open.delete(key) : state.open.add(key); draw(); }
          if (cfg.onRow) cfg.onRow(row);
        };
        if (cfg.onRow || cfg.expand) {
          tr.addEventListener("click", (e) => { if (!e.target.closest("a,button,select,input")) act(); });
          tr.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); act(); } });
        }
      });
    }
    draw();
    return { redraw: draw, setRows(rows) { cfg.rows = rows; draw(); } };
  };

  // ------------------------------------------------------------------ drawer
  ui.drawer = (title, html, onOpen) => {
    ui.closeDrawer();
    const back = document.createElement("div");
    back.className = "backdrop";
    back.id = "tm-backdrop";
    const d = document.createElement("aside");
    d.className = "drawer";
    d.id = "tm-drawer";
    d.setAttribute("role", "dialog");
    d.setAttribute("aria-modal", "true");
    d.setAttribute("aria-label", title.replace(/<[^>]+>/g, ""));
    d.innerHTML = `<div class="drawer-head"><h2 class="card-title">${title}</h2><button class="iconbtn" style="margin-left:auto" type="button" data-close aria-label="Close">${SM.icon("x")}</button></div><div class="drawer-body">${html}</div>`;
    const prev = document.activeElement;
    document.body.append(back, d);
    const close = () => { ui.closeDrawer(); if (prev && prev.focus) prev.focus(); };
    back.addEventListener("click", close);
    d.querySelector("[data-close]").addEventListener("click", close);
    d.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
    d.querySelector("[data-close]").focus();
    if (onOpen) onOpen(d.querySelector(".drawer-body"));
    return d;
  };
  ui.closeDrawer = () => {
    const a = document.getElementById("tm-drawer");
    const b = document.getElementById("tm-backdrop");
    if (a) a.remove();
    if (b) b.remove();
  };

  // ------------------------------------------------------------------ async section helper
  ui.load = async (el, fn) => {
    el.innerHTML = ui.loading();
    try { await fn(); } catch (err) { console.error(err); el.innerHTML = ui.error(err); }
  };
})();
