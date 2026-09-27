/* Swing Master -- core: namespace, formatting, icons, API client, state, router. */
(function () {
  "use strict";
  const SM = (window.SM = window.SM || {});

  // ------------------------------------------------------------------ utils
  const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  SM.esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ESC[c]);
  SM.isNum = (x) => typeof x === "number" && isFinite(x);
  const nf = {};
  function numFmt(dp) {
    if (!nf[dp]) nf[dp] = new Intl.NumberFormat("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp });
    return nf[dp];
  }
  SM.fmt = (x, dp = 2) => (SM.isNum(x) ? numFmt(dp).format(x) : "—");
  SM.inr = (x, dp = 0) => (SM.isNum(x) ? (x < 0 ? "−₹" : "₹") + numFmt(dp).format(Math.abs(x)) : "—");
  SM.signed = (x, dp = 2, suffix = "") => (SM.isNum(x) ? (x > 0 ? "+" : x < 0 ? "−" : "") + numFmt(dp).format(Math.abs(x)) + suffix : "—");
  SM.signedInr = (x, dp = 0) => (SM.isNum(x) ? (x > 0 ? "+" : x < 0 ? "−" : "") + "₹" + numFmt(dp).format(Math.abs(x)) : "—");
  SM.pct = (x, dp = 1, fraction = true) => (SM.isNum(x) ? numFmt(dp).format(fraction ? x * 100 : x) + "%" : "—");
  SM.signedPct = (x, dp = 2, fraction = false) => (SM.isNum(x) ? SM.signed(fraction ? x * 100 : x, dp, "%") : "—");
  SM.dir = (x) => (SM.isNum(x) ? (x > 0 ? "up" : x < 0 ? "down" : "") : "");
  SM.compact = (x) => {
    if (!SM.isNum(x)) return "—";
    const a = Math.abs(x);
    if (a >= 1e7) return SM.fmt(x / 1e7, 2) + " Cr";
    if (a >= 1e5) return SM.fmt(x / 1e5, 2) + " L";
    if (a >= 1e3) return SM.fmt(x / 1e3, 1) + "K";
    return SM.fmt(x, 0);
  };
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  SM.parseT = (iso) => (iso ? new Date(iso.length <= 10 ? iso + "T00:00:00" : iso) : null);
  SM.date = (iso) => { const d = SM.parseT(iso); return d ? `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}` : "—"; };
  SM.dateShort = (iso) => { const d = SM.parseT(iso); return d ? `${d.getDate()} ${MONTHS[d.getMonth()]}` : "—"; };
  SM.monthYear = (iso) => { const d = SM.parseT(iso); return d ? `${MONTHS[d.getMonth()]} ${String(d.getFullYear()).slice(2)}` : "—"; };
  SM.time = (iso) => { const d = SM.parseT(iso); return d ? d.toTimeString().slice(0, 5) : "—"; };
  SM.dateTime = (iso) => { const d = SM.parseT(iso); return d ? `${SM.date(iso)} ${SM.time(iso)}` : "—"; };
  SM.months = MONTHS;
  SM.title = (s) => String(s || "").toLowerCase().replace(/(^|[\s_-])(\w)/g, (m, a, b) => a + b.toUpperCase()).replace(/_/g, " ");
  SM.debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

  SM.store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* storage unavailable: preference not kept */ } },
  };

  SM.toast = (msg) => {
    const t = document.createElement("div");
    t.className = "toast";
    t.setAttribute("role", "status");
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 2600);
  };

  // ------------------------------------------------------------------ icons
  const P = {
    grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    trend: '<path d="M3 17l6-6 4 4 8-8"/><path d="M14 7h7v7"/>',
    layers: '<path d="M12 3 2 8l10 5 10-5-10-5z"/><path d="m2 13 10 5 10-5"/>',
    profile: '<path d="M3 5h10M3 10h16M3 15h12M3 20h7"/>',
    users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M18 14a5.5 5.5 0 0 1 3.5 6"/>',
    activity: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    candles: '<path d="M7 3v4M7 17v4M17 5v3M17 16v3"/><rect x="4.5" y="7" width="5" height="10" rx="1"/><rect x="14.5" y="8" width="5" height="8" rx="1"/>',
    setup: '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V3h6v1"/><path d="m9 13 2 2 4-4"/>',
    briefcase: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2M3 13h18"/>',
    shield: '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6l-8-3z"/><path d="m9 12 2 2 4-4"/>',
    flask: '<path d="M9 3h6M10 3v6L4.5 18.5A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.5-2.5L14 9V3"/><path d="M7.5 15h9"/>',
    repeat: '<path d="M17 2l3 3-3 3"/><path d="M4 11V9a4 4 0 0 1 4-4h12"/><path d="M7 22l-3-3 3-3"/><path d="M20 13v2a4 4 0 0 1-4 4H4"/>',
    book: '<path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v17H6.5A2.5 2.5 0 0 0 4 21.5z"/><path d="M4 19.5V4.5M9 7h7"/>',
    xcircle: '<circle cx="12" cy="12" r="9"/><path d="m15 9-6 6M9 9l6 6"/>',
    report: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 17v-3M12 17v-6M16 17v-2"/>',
    heart: '<path d="M20.8 5.6a5 5 0 0 0-7.1 0L12 7.3l-1.7-1.7a5 5 0 1 0-7.1 7.1L12 21.5l8.8-8.8a5 5 0 0 0 0-7.1z"/><path d="M3.5 12h4l1.5-3 3 6 1.5-3h3"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>',
    menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
    check: '<path d="m5 12 5 5L20 7"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    minus: '<path d="M5 12h14"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>',
    alert: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
    palette: '<circle cx="13.5" cy="6.5" r="1.2"/><circle cx="17.5" cy="10.5" r="1.2"/><circle cx="8.5" cy="7.5" r="1.2"/><circle cx="6.5" cy="12.5" r="1.2"/><path d="M12 2a10 10 0 0 0 0 20c.9 0 1.7-.8 1.7-1.7 0-.4-.2-.8-.4-1.1-.3-.3-.4-.7-.4-1.1 0-.9.8-1.7 1.7-1.7h2A5.6 5.6 0 0 0 22 11c0-5-4.5-9-10-9z"/>',
    arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    play: '<path d="m7 4 13 8-13 8z"/>',
    refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4L21 8"/><path d="M21 3v5h-5"/>',
    lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    wallet: '<path d="M3 7a2 2 0 0 1 2-2h13v4"/><path d="M3 7v11a2 2 0 0 0 2 2h15V9H5a2 2 0 0 1-2-2z"/><circle cx="16" cy="14.5" r="1.2"/>',
    target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    link: '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
    download: '<path d="M12 3v12M7 10l5 5 5-5M4 21h16"/>',
    up: '<path d="M12 19V5M5 12l7-7 7 7"/>',
    down: '<path d="M12 5v14M19 12l-7 7-7-7"/>',
    bank: '<path d="M3 10h18L12 4 3 10zM5 10v8M9 10v8M15 10v8M19 10v8M3 21h18"/>',
    bars: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    pie: '<path d="M21 12A9 9 0 1 1 12 3v9z"/><path d="M15 3.5A9 9 0 0 1 20.5 9H15z"/>',
    zap: '<path d="M13 2 3 14h9l-1 8 10-12h-9z"/>',
  };
  SM.icon = (name, cls = "") =>
    `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${P[name] || P.info}</svg>`;

  // ------------------------------------------------------------------ API
  class Unavailable extends Error {}
  SM.Unavailable = Unavailable;
  const cache = new Map();
  SM.api = {
    key(path, params) {
      const qs = Object.keys(params || {}).filter((k) => params[k] !== undefined && params[k] !== null && params[k] !== "")
        .sort().map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(params[k])}`).join("&");
      return qs ? `${path}?${qs}` : path;
    },
    isStatic() { return !!window.__SM_SNAPSHOT__; },
    async get(path, params = {}, opts = {}) {
      const k = this.key(path, params);
      const snap = window.__SM_SNAPSHOT__;
      if (snap) {
        if (Object.prototype.hasOwnProperty.call(snap.data, k)) return snap.data[k];
        throw new Unavailable("This view is not included in the static preview. Run the local server for every symbol and timeframe.");
      }
      if (!opts.fresh && cache.has(k)) return cache.get(k);
      const res = await fetch(k, { headers: { Accept: "application/json" } });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || `${res.status} ${res.statusText}`);
      if (!opts.nocache) cache.set(k, body);
      return body;
    },
    async post(path, body) {
      if (window.__SM_SNAPSHOT__) throw new Unavailable("Static preview is read-only. Start the local server to recompute.");
      const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
      const out = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(out.detail || `${res.status} ${res.statusText}`);
      cache.clear();
      return out;
    },
    clear() { cache.clear(); },
  };

  // ------------------------------------------------------------------ state
  const listeners = [];
  SM.state = {
    symbol: SM.store.get("sm.symbol", "NIFTY"),
    tf: SM.store.get("sm.tf", "1D"),
    skin: SM.store.get("sm.skin", "auto"),
    meta: null,
    overview: null,
  };
  SM.setState = (patch) => {
    const changed = Object.keys(patch).filter((k) => SM.state[k] !== patch[k]);
    Object.assign(SM.state, patch);
    if (patch.symbol) SM.store.set("sm.symbol", patch.symbol);
    if (patch.tf) SM.store.set("sm.tf", patch.tf);
    if (changed.length) listeners.forEach((fn) => fn(changed));
  };
  SM.onState = (fn) => listeners.push(fn);

  // ------------------------------------------------------------------ router
  SM.views = SM.views || {};
  SM.route = () => {
    const h = (location.hash || "").replace(/^#/, "");
    return SM.views[h] ? h : "overview";
  };
  SM.go = (name) => {
    if (location.hash !== "#" + name) location.hash = name;
    else SM.render && SM.render();
  };
  SM.openSymbol = (symbol, view = "setup") => {
    SM.setState({ symbol });
    SM.go(view);
  };
})();
