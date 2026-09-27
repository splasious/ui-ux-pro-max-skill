/* Swing Master -- dependency-free SVG charts, coloured only through theme tokens.
 * CandleChart: candles (hollow = up, filled = down, so direction never relies on colour),
 * confirmed ZigZag, HH/HL/LH/LL labels with confirmation markers, BOS/CHoCH, demand/supply,
 * volume profile (POC/VAH/VAL), trade levels, trail, markers.  Keyboard: arrows, + / -, 0.
 */
(function () {
  "use strict";
  const SM = window.SM;
  const esc = SM.esc;
  const charts = (SM.charts = {});

  function niceStep(range, n) {
    const raw = range / Math.max(1, n);
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const f = raw / mag;
    return (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * mag;
  }
  function ticks(lo, hi, n = 5) {
    if (!(hi > lo)) return [lo];
    const s = niceStep(hi - lo, n);
    const out = [];
    for (let v = Math.ceil(lo / s) * s; v <= hi + 1e-9; v += s) out.push(+v.toFixed(10));
    return out;
  }
  charts.ticks = ticks;
  const pfmt = (p, big) => SM.fmt(p, big ? 0 : 2);

  // ------------------------------------------------------------------ sparkline
  charts.spark = (values, o = {}) => {
    const w = o.w || 140, h = o.h || 40;
    const vals = (values || []).filter(SM.isNum);
    if (vals.length < 2) return "";
    const lo = Math.min(...vals), hi = Math.max(...vals);
    const span = hi - lo || 1;
    const pts = vals.map((v, i) => [(i / (vals.length - 1)) * (w - 4) + 2, h - 3 - ((v - lo) / span) * (h - 6)]);
    const color = o.color || "var(--accent)";
    const line = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join("");
    const area = `${line}L${pts[pts.length - 1][0].toFixed(1)} ${h}L${pts[0][0].toFixed(1)} ${h}Z`;
    const last = pts[pts.length - 1];
    return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" style="width:100%;height:100%" aria-hidden="true">
      ${o.area === false ? "" : `<path d="${area}" fill="${color}" fill-opacity="0.14"/>`}
      <path d="${line}" fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>
      <circle cx="${last[0]}" cy="${last[1]}" r="2.4" fill="${color}"/></svg>`;
  };

  // ------------------------------------------------------------------ ring
  charts.ring = (value, max = 100, o = {}) => {
    const size = o.size || 120, sw = o.stroke || 10, r = (size - sw) / 2, c = 2 * Math.PI * r;
    const frac = SM.isNum(value) ? Math.max(0, Math.min(1, value / max)) : 0;
    const color = o.color || "var(--accent)";
    return `<svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" role="img" aria-label="${SM.fmt(value, 0)} of ${max}">
      <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="var(--panel-2)" stroke-width="${sw}"/>
      <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="${color}" stroke-width="${sw}" stroke-linecap="round"
        stroke-dasharray="${(frac * c).toFixed(1)} ${c.toFixed(1)}" transform="rotate(-90 ${size / 2} ${size / 2})"/>
      <text x="50%" y="${o.label ? "47%" : "52%"}" text-anchor="middle" dominant-baseline="middle" fill="var(--text)" font-size="${size * 0.26}" font-weight="700">${SM.isNum(value) ? Math.round(value) : "—"}</text>
      ${o.label ? `<text x="50%" y="68%" text-anchor="middle" fill="var(--muted)" font-size="${size * 0.1}">${esc(o.label)}</text>` : ""}</svg>`;
  };

  // ------------------------------------------------------------------ generic line chart
  charts.line = (el, o) => {
    const series = o.series.filter((s) => s.data && s.data.length);
    if (!series.length) { el.innerHTML = SM.ui.empty("No data"); return; }
    const H = o.height || 220, padL = o.padL || 56, padR = 12, padT = 12, padB = 26;
    function draw() {
      const W = el.clientWidth || 600;
      const n = Math.max(...series.map((s) => s.data.length));
      const ys = series.flatMap((s) => s.data.map((d) => d.y)).filter(SM.isNum);
      let lo = o.yMin != null ? o.yMin : Math.min(...ys), hi = o.yMax != null ? o.yMax : Math.max(...ys);
      if (o.zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
      if (hi === lo) { hi += 1; lo -= 1; }
      const pad = (hi - lo) * 0.06; lo -= o.yMin != null ? 0 : pad; hi += o.yMax != null ? 0 : pad;
      const x = (i) => padL + (i / Math.max(1, n - 1)) * (W - padL - padR);
      const y = (v) => padT + ((hi - v) / (hi - lo)) * (H - padT - padB);
      const yf = o.yFmt || ((v) => SM.fmt(v, 0));
      let g = ticks(lo, hi, 4).map((t) => `<line x1="${padL}" x2="${W - padR}" y1="${y(t)}" y2="${y(t)}" stroke="var(--grid)"/>
        <text x="${padL - 6}" y="${y(t)}" text-anchor="end" dominant-baseline="middle" fill="var(--axis)" font-size="10.5">${esc(yf(t))}</text>`).join("");
      if (o.zero && lo < 0 && hi > 0) g += `<line x1="${padL}" x2="${W - padR}" y1="${y(0)}" y2="${y(0)}" stroke="var(--border-strong)"/>`;
      const ref = series[0].data;
      const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor((W - padL) / 90))));
      for (let i = 0; i < ref.length; i += every) {
        g += `<text x="${x(i)}" y="${H - 8}" text-anchor="middle" fill="var(--axis)" font-size="10.5">${esc((o.xFmt || ((v) => v))(ref[i].x))}</text>`;
      }
      for (const s of series) {
        const pts = s.data.map((d, i) => (SM.isNum(d.y) ? [x(i), y(d.y)] : null)).filter(Boolean);
        if (!pts.length) continue;
        const path = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join("");
        if (s.area) {
          const base = y(o.zero ? 0 : lo);
          g += `<path d="${path}L${pts[pts.length - 1][0]} ${base}L${pts[0][0]} ${base}Z" fill="${s.color}" fill-opacity="${s.areaOpacity || 0.14}"/>`;
        }
        g += `<path d="${path}" fill="none" stroke="${s.color}" stroke-width="${s.width || 1.8}" ${s.dash ? `stroke-dasharray="${s.dash}"` : ""} stroke-linejoin="round"/>`;
        const lp = pts[pts.length - 1];
        g += `<circle cx="${lp[0]}" cy="${lp[1]}" r="3" fill="${s.color}"/>`;
      }
      el.innerHTML = `<div class="chart-box" style="height:${H}px"><svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="${esc(o.label || "Line chart")}">${g}
        <g class="hover"></g></svg></div>
        ${series.length > 1 || o.legend ? `<div class="chart-legend">${series.map((s) => `<span><i style="background:${s.color}"></i>${esc(s.name)}</span>`).join("")}</div>` : ""}`;
      const svg = el.querySelector("svg"), hov = el.querySelector(".hover"), box = el.querySelector(".chart-box");
      svg.addEventListener("mousemove", (e) => {
        const r = svg.getBoundingClientRect();
        const mx = ((e.clientX - r.left) / r.width) * W;
        const i = Math.max(0, Math.min(n - 1, Math.round(((mx - padL) / (W - padL - padR)) * (n - 1))));
        hov.innerHTML = `<line x1="${x(i)}" x2="${x(i)}" y1="${padT}" y2="${H - padB}" stroke="var(--border-strong)" stroke-dasharray="3 3"/>` +
          series.map((s) => (s.data[i] && SM.isNum(s.data[i].y) ? `<circle cx="${x(i)}" cy="${y(s.data[i].y)}" r="3.5" fill="${s.color}" stroke="var(--panel)"/>` : "")).join("");
        let tip = box.querySelector(".chart-tip");
        if (!tip) { tip = document.createElement("div"); tip.className = "chart-tip"; box.appendChild(tip); }
        tip.innerHTML = `<b>${esc((o.tipX || o.xFmt || ((v) => v))(ref[i] ? ref[i].x : ""))}</b><br>` +
          series.map((s) => (s.data[i] ? `${esc(s.name)}: <b>${esc(yf(s.data[i].y))}</b>` : "")).filter(Boolean).join("<br>");
        const left = (x(i) / W) * r.width;
        tip.style.left = Math.min(r.width - 160, left + 12) + "px";
        tip.style.top = "8px";
      });
      svg.addEventListener("mouseleave", () => { hov.innerHTML = ""; const t = box.querySelector(".chart-tip"); if (t) t.remove(); });
    }
    draw();
    observe(el, draw);
  };

  // ------------------------------------------------------------------ bar chart (supports negatives)
  charts.bars = (el, o) => {
    const items = o.items || [];
    if (!items.length) { el.innerHTML = SM.ui.empty("No data"); return; }
    const H = o.height || 200, padL = o.padL || 44, padR = 8, padT = 10, padB = o.rotate ? 44 : 26;
    function draw() {
      const W = el.clientWidth || 500;
      const vals = items.map((d) => d.value).filter(SM.isNum);
      let lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
      if (hi === lo) hi = lo + 1;
      const y = (v) => padT + ((hi - v) / (hi - lo)) * (H - padT - padB);
      const bw = (W - padL - padR) / items.length;
      const yf = o.yFmt || ((v) => SM.fmt(v, 0));
      let g = ticks(lo, hi, 4).map((t) => `<line x1="${padL}" x2="${W - padR}" y1="${y(t)}" y2="${y(t)}" stroke="var(--grid)"/>
        <text x="${padL - 6}" y="${y(t)}" text-anchor="end" dominant-baseline="middle" fill="var(--axis)" font-size="10.5">${esc(yf(t))}</text>`).join("");
      g += `<line x1="${padL}" x2="${W - padR}" y1="${y(0)}" y2="${y(0)}" stroke="var(--border-strong)"/>`;
      const every = Math.max(1, Math.ceil(items.length / Math.max(2, Math.floor((W - padL) / (o.rotate ? 26 : 60)))));
      items.forEach((d, i) => {
        if (!SM.isNum(d.value)) return;
        const x0 = padL + i * bw + bw * 0.15, w = Math.max(1, bw * 0.7);
        const color = d.color || (o.colorFn ? o.colorFn(d) : d.value >= 0 ? "var(--up)" : "var(--down)");
        const top = Math.min(y(d.value), y(0)), h = Math.max(1, Math.abs(y(d.value) - y(0)));
        g += `<rect x="${x0}" y="${top}" width="${w}" height="${h}" rx="${Math.min(3, w / 3)}" fill="${color}" fill-opacity="${d.opacity || 0.9}"><title>${esc(d.label)}: ${esc(yf(d.value))}</title></rect>`;
        if (i % every === 0) {
          const lx = x0 + w / 2;
          g += o.rotate
            ? `<text transform="translate(${lx},${H - padB + 10}) rotate(-45)" text-anchor="end" fill="var(--axis)" font-size="10">${esc(d.label)}</text>`
            : `<text x="${lx}" y="${H - 8}" text-anchor="middle" fill="var(--axis)" font-size="10.5">${esc(d.label)}</text>`;
        }
      });
      el.innerHTML = `<div class="chart-box"><svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="${esc(o.label || "Bar chart")}">${g}</svg></div>`;
    }
    draw();
    observe(el, draw);
  };

  // ------------------------------------------------------------------ monthly heatmap (HTML)
  charts.heatmap = (el, monthly) => {
    const years = {};
    monthly.forEach((m) => { const [y, mo] = m.month.split("-"); (years[y] = years[y] || {})[+mo] = m.return; });
    const maxAbs = Math.max(0.01, ...monthly.map((m) => Math.abs(m.return)));
    let html = `<div class="table-wrap"><div class="heat" style="grid-template-columns: 48px repeat(12, minmax(34px, 1fr)) 58px; min-width: 560px">`;
    html += `<div class="hdr"></div>${SM.months.map((m) => `<div class="hdr">${m}</div>`).join("")}<div class="hdr">Year</div>`;
    Object.keys(years).sort().forEach((y) => {
      html += `<div class="hdr" style="text-align:left">${y}</div>`;
      let tot = 1;
      for (let mo = 1; mo <= 12; mo++) {
        const v = years[y][mo];
        if (v == null) { html += `<div class="cell" style="background:var(--panel-2)"></div>`; continue; }
        tot *= 1 + v;
        const pct = Math.round((Math.min(1, Math.abs(v) / maxAbs) * 55) + 8);
        const col = v >= 0 ? "var(--up)" : "var(--down)";
        html += `<div class="cell" style="background:color-mix(in srgb, ${col} ${pct}%, var(--panel))" title="${y}-${String(mo).padStart(2, "0")}: ${SM.signedPct(v, 2, true)}">${SM.signed(v * 100, 1)}</div>`;
      }
      const t = tot - 1;
      html += `<div class="cell ${SM.dir(t)}" style="font-weight:700">${SM.signed(t * 100, 1)}%</div>`;
    });
    el.innerHTML = html + "</div></div>";
  };

  // ------------------------------------------------------------------ option-chain butterfly
  charts.chain = (el, strikes, o = {}) => {
    if (!strikes.length) { el.innerHTML = SM.ui.empty("No option chain"); return; }
    const max = Math.max(...strikes.map((s) => Math.max(s.call_oi, s.put_oi)));
    const rows = strikes.map((s) => {
      const atm = s.strike === o.atm;
      return `<div class="chain-row" style="display:grid;grid-template-columns:1fr 78px 1fr;gap:6px;align-items:center;font-size:11.5px;${s.selected ? "" : "opacity:.45"}">
        <div style="display:flex;justify-content:flex-end;align-items:center;gap:6px"><span class="num muted">${SM.compact(s.put_oi)}</span>
          <span style="height:10px;border-radius:3px;background:var(--up);width:${(s.put_oi / max) * 100}%;min-width:1px" title="Put OI ${SM.fmt(s.put_oi, 0)}"></span></div>
        <div class="num" style="text-align:center;font-weight:${atm ? 800 : 500};${atm ? "color:var(--accent)" : ""}">${SM.fmt(s.strike, 0)}${atm ? " ATM" : ""}</div>
        <div style="display:flex;align-items:center;gap:6px"><span style="height:10px;border-radius:3px;background:var(--down);width:${(s.call_oi / max) * 100}%;min-width:1px" title="Call OI ${SM.fmt(s.call_oi, 0)}"></span>
          <span class="num muted">${SM.compact(s.call_oi)}</span></div></div>`;
    }).join("");
    el.innerHTML = `<div style="display:grid;grid-template-columns:1fr 78px 1fr;gap:6px;font-size:11px;color:var(--muted);margin-bottom:6px">
      <span style="text-align:right">Put OI</span><span style="text-align:center">Strike</span><span>Call OI</span></div><div style="display:grid;gap:3px">${rows}</div>`;
  };

  // ------------------------------------------------------------------ volume profile (standalone)
  charts.profile = (el, vp, o = {}) => {
    if (!vp) { el.innerHTML = SM.ui.empty("Profile unavailable"); return; }
    const padL = 70, padR = 16, padT = 10, padB = 10;
    function draw() {
      const W = el.clientWidth || 500;
      const H = W < 600 ? Math.round(Math.min(o.height || 420, Math.max(300, W * 1.05))) : (o.height || 420);
      const n = vp.volumes.length, lo = vp.price_low, hi = lo + vp.bin_size * n;
      const y = (p) => padT + ((hi - p) / (hi - lo)) * (H - padT - padB);
      const max = Math.max(...vp.volumes);
      const bh = (H - padT - padB) / n;
      let g = "";
      (o.zones || []).forEach((z) => {
        const top = Math.max(z.proximal, z.distal), bot = Math.min(z.proximal, z.distal);
        if (bot > hi || top < lo) return;
        g += `<rect x="${padL}" width="${W - padL - padR}" y="${y(Math.min(top, hi))}" height="${Math.max(2, y(Math.max(bot, lo)) - y(Math.min(top, hi)))}"
          fill="var(--${z.type === "DEMAND" ? "demand" : "supply"}-fill)" stroke="var(--${z.type === "DEMAND" ? "demand" : "supply"})" stroke-dasharray="4 3"><title>${esc(z.type)} ${SM.fmt(z.proximal)}–${SM.fmt(z.distal)}</title></rect>`;
      });
      vp.volumes.forEach((v, k) => {
        const p0 = lo + k * vp.bin_size, mid = p0 + vp.bin_size / 2;
        const inVA = mid >= vp.val && mid <= vp.vah;
        const w = (v / max) * (W - padL - padR);
        g += `<rect x="${padL}" y="${y(p0 + vp.bin_size) + 0.5}" width="${w}" height="${Math.max(1, bh - 1)}" fill="${inVA ? "var(--profile-va)" : "var(--profile)"}" fill-opacity="${inVA ? 0.85 : 0.6}"><title>${SM.fmt(p0)}–${SM.fmt(p0 + vp.bin_size)}: ${SM.compact(v)}</title></rect>`;
      });
      const line = (p, label, color, dash) => `<line x1="${padL}" x2="${W - padR}" y1="${y(p)}" y2="${y(p)}" stroke="${color}" stroke-width="1.4" ${dash ? `stroke-dasharray="${dash}"` : ""}/>
        <text x="${padL - 6}" y="${y(p)}" text-anchor="end" dominant-baseline="middle" font-size="10.5" fill="${color}" font-weight="700">${label}</text>`;
      g += line(vp.vah, "VAH " + SM.fmt(vp.vah, 0), "var(--profile-va)", "4 3") + line(vp.val, "VAL " + SM.fmt(vp.val, 0), "var(--profile-va)", "4 3");
      g += line(vp.poc, "POC " + SM.fmt(vp.poc, 0), "var(--poc)", "");
      (vp.hvn || []).forEach((h) => { g += `<circle cx="${W - padR - 6}" cy="${y(h)}" r="3.5" fill="var(--accent)"><title>HVN ${SM.fmt(h)}</title></circle>`; });
      (vp.lvn || []).forEach((h) => { g += `<rect x="${W - padR - 9}" y="${y(h) - 3}" width="6" height="6" fill="none" stroke="var(--muted)"><title>LVN ${SM.fmt(h)}</title></rect>`; });
      if (SM.isNum(o.price) && o.price >= lo && o.price <= hi) g += line(o.price, "LTP", "var(--text)", "2 3");
      el.innerHTML = `<div class="chart-box"><svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="Volume profile, POC ${SM.fmt(vp.poc)}">${g}</svg></div>`;
    }
    draw();
    observe(el, draw);
  };

  // ------------------------------------------------------------------ visual trade plan ladder
  charts.ladder = (el, plan) => {
    if (!plan || !plan.valid) { el.innerHTML = SM.ui.empty("No valid plan"); return; }
    const long = plan.direction === "LONG";
    const levels = [
      ["T3", plan.t3, "var(--up)"], ["T2", plan.t2, "var(--up)"], ["T1", plan.t1, "var(--up)"],
      ["Entry", plan.entry, "var(--accent)"], ["SL", plan.stop, "var(--down)"],
    ].filter((l) => SM.isNum(l[1]));
    const H = 300, padT = 16, padB = 16;
    function draw() {
      const W = el.clientWidth || 360;
      const ps = levels.map((l) => l[1]);
      if (plan.zone) ps.push(plan.zone.proximal, plan.zone.distal);
      let lo = Math.min(...ps), hi = Math.max(...ps);
      const pad = (hi - lo) * 0.06; lo -= pad; hi += pad;
      const y = (p) => padT + ((hi - p) / (hi - lo)) * (H - padT - padB);
      const x0 = 64, x1 = W - 130;
      let g = "";
      const best = long ? Math.max(...levels.slice(0, 3).map((l) => l[1])) : Math.min(...levels.slice(0, 3).map((l) => l[1]));
      g += `<rect x="${x0}" width="${x1 - x0}" y="${Math.min(y(best), y(plan.entry))}" height="${Math.abs(y(best) - y(plan.entry))}" fill="var(--up-soft)"/>`;
      g += `<rect x="${x0}" width="${x1 - x0}" y="${Math.min(y(plan.stop), y(plan.entry))}" height="${Math.abs(y(plan.stop) - y(plan.entry))}" fill="var(--down-soft)"/>`;
      if (plan.zone) {
        const zt = Math.max(plan.zone.proximal, plan.zone.distal), zb = Math.min(plan.zone.proximal, plan.zone.distal);
        const k = plan.zone.type === "SUPPLY" ? "supply" : "demand";
        g += `<rect x="${x0}" width="${x1 - x0}" y="${y(zt)}" height="${Math.max(3, y(zb) - y(zt))}" fill="var(--${k}-fill)" stroke="var(--${k})" stroke-dasharray="4 3"/>
          <text x="${x0 + 8}" y="${y(zb) - 5}" font-size="10.5" fill="var(--${k})" font-weight="700">${esc(SM.title(plan.zone.type))} zone</text>`;
      }
      levels.forEach(([name, p, color], idx) => {
        const r = name === "Entry" ? "" : name === "SL" ? "−1.0R" : plan.rr && plan.rr[2 - idx] != null ? `+${SM.fmt(plan.rr[2 - idx], 1)}R` : "";
        g += `<line x1="${x0}" x2="${x1}" y1="${y(p)}" y2="${y(p)}" stroke="${color}" stroke-width="${name === "Entry" ? 2 : 1.5}" ${name.startsWith("T") ? 'stroke-dasharray="5 4"' : ""}/>
          <text x="${x0 - 8}" y="${y(p)}" text-anchor="end" dominant-baseline="middle" font-size="12" font-weight="700" fill="${color}">${name}</text>
          <text x="${x1 + 8}" y="${y(p)}" dominant-baseline="middle" font-size="12" fill="var(--text)" font-weight="600">${SM.fmt(p, 2)}</text>
          <text x="${W - 8}" y="${y(p)}" text-anchor="end" dominant-baseline="middle" font-size="11" fill="var(--muted)">${r}</text>`;
      });
      el.innerHTML = `<div class="chart-box"><svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="Trade plan: entry ${SM.fmt(plan.entry)}, stop ${SM.fmt(plan.stop)}">${g}</svg></div>`;
    }
    draw();
    observe(el, draw);
  };

  // ------------------------------------------------------------------ candle chart
  class CandleChart {
    constructor(el, data, opts = {}) {
      this.el = el;
      this.data = data;
      this.o = Object.assign({ height: 460, visible: 160, volume: true, profile: true, zones: true, zigzag: true,
        labels: true, events: true, levels: true, markers: true, hollow: SM.store.get("sm.hollow", true), onPivot: null }, opts);
      const n = data.bars.length;
      this.end = n - 1;
      this.start = Math.max(0, n - this.fitVisible());
      this.cursor = null;
      this.userZoomed = false;
      el.innerHTML = `<div class="chart-box" tabindex="0" role="img" aria-roledescription="interactive chart"
        aria-label="${esc(data.symbol)} ${esc(data.timeframe)} candlestick chart. Arrow keys move the cursor, plus and minus zoom, 0 resets.">
        <div class="chart-readout"></div><svg></svg>
        <div class="zoom-ctl"><button type="button" data-z="in" aria-label="Zoom in">+</button><button type="button" data-z="out" aria-label="Zoom out">−</button><button type="button" data-z="reset" aria-label="Reset zoom">⟲</button></div></div>`;
      this.box = el.querySelector(".chart-box");
      this.svg = el.querySelector("svg");
      this.readout = el.querySelector(".chart-readout");
      this.bind();
      this.render();
      observe(el, () => this.resize());
    }
    set(opts) { Object.assign(this.o, opts); this.render(); }
    fitVisible() {
      // fewer, wider candles on narrow screens so bodies stay readable (about 6 px per candle minimum)
      const w = this.el.clientWidth || 800;
      return Math.max(30, Math.min(this.o.visible, Math.floor(w / 6)));
    }
    fitHeight(W) {
      return W < 700 ? Math.round(Math.min(this.o.height, Math.max(260, W * 0.8))) : this.o.height;
    }
    resize() {
      if (!this.userZoomed) {
        const n = this.data.bars.length;
        this.end = n - 1;
        this.start = Math.max(0, n - this.fitVisible());
      }
      this.render();
    }
    zoom(f, anchor) {
      const n = this.data.bars.length;
      const span = this.end - this.start + 1;
      const ns = Math.max(20, Math.min(n, Math.round(span * f)));
      const a = anchor != null ? anchor : this.end;
      const rel = (a - this.start) / span;
      let s = Math.round(a - rel * ns);
      s = Math.max(0, Math.min(n - ns, s));
      this.start = s; this.end = s + ns - 1;
      this.userZoomed = true;
      this.render();
    }
    pan(bars) {
      const n = this.data.bars.length, span = this.end - this.start;
      let s = Math.max(0, Math.min(n - 1 - span, this.start + bars));
      this.start = s; this.end = s + span;
      this.render();
    }
    bind() {
      this.box.querySelectorAll("[data-z]").forEach((b) => b.addEventListener("click", () => {
        const z = b.dataset.z;
        if (z === "in") this.zoom(0.75); else if (z === "out") this.zoom(1.35);
        else { this.userZoomed = false; this.resize(); }
      }));
      this.svg.addEventListener("wheel", (e) => {
        // zoom only when the chart has focus (clicked) or on pinch / ctrl+wheel, so page scrolling is never trapped
        if (!(e.ctrlKey || e.metaKey || document.activeElement === this.box)) return;
        e.preventDefault();
        this.zoom(e.deltaY > 0 ? 1.15 : 0.87, this.barAt(e));
      }, { passive: false });
      let drag = null;
      this.svg.addEventListener("pointerdown", (e) => {
        this.box.focus({ preventScroll: true });
        if (e.target.closest(".pivot-hit")) return;
        drag = { x: e.clientX, start: this.start };
        this.svg.setPointerCapture(e.pointerId);
      });
      this.svg.addEventListener("pointermove", (e) => {
        if (drag && this.L) {
          const r = this.svg.getBoundingClientRect();
          const dx = ((e.clientX - drag.x) / r.width) * this.L.W;
          const bars = Math.round(-dx / this.L.step);
          const span = this.end - this.start;
          const n = this.data.bars.length;
          const s = Math.max(0, Math.min(n - 1 - span, drag.start + bars));
          if (s !== this.start) { this.start = s; this.end = s + span; this.render(); }
          return;
        }
        const k = this.barAt(e);
        if (k != null) { this.cursor = k; this.drawCursor(e); }
      });
      this.svg.addEventListener("pointerup", () => { drag = null; });
      this.svg.addEventListener("pointerleave", () => { drag = null; this.cursor = null; this.drawCursor(); });
      this.svg.addEventListener("click", (e) => {
        const hit = e.target.closest(".pivot-hit");
        if (hit && this.o.onPivot) this.o.onPivot(this.data.pivots[+hit.dataset.p]);
      });
      this.box.addEventListener("keydown", (e) => {
        const n = this.data.bars.length;
        if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
          e.preventDefault();
          const c = this.cursor == null ? this.end : this.cursor + (e.key === "ArrowLeft" ? -1 : 1);
          this.cursor = Math.max(0, Math.min(n - 1, c));
          if (this.cursor < this.start) this.pan(this.cursor - this.start);
          if (this.cursor > this.end) this.pan(this.cursor - this.end);
          this.drawCursor();
        } else if (e.key === "+" || e.key === "=") { this.zoom(0.75, this.cursor); }
        else if (e.key === "-" || e.key === "_") { this.zoom(1.35, this.cursor); }
        else if (e.key === "0") { this.userZoomed = false; this.resize(); }
      });
    }
    barAt(e) {
      if (!this.L) return null;
      const r = this.svg.getBoundingClientRect();
      const mx = ((e.clientX - r.left) / r.width) * this.L.W;
      const k = this.start + Math.floor((mx - this.L.padL) / this.L.step);
      return k < this.start || k > this.end ? null : k;
    }
    render() {
      const d = this.data, o = this.o, bars = d.bars;
      if (!bars.length) { this.svg.innerHTML = ""; return; }
      const W = Math.max(280, this.el.clientWidth || 800), H = this.fitHeight(W);
      const maxPrice = Math.max(...d.bars.slice(this.start, this.end + 1).map((b) => b.h));
      const padL = 4, padR = maxPrice >= 10000 ? 92 : maxPrice >= 1000 ? 84 : 74, padT = 30, padB = 22;
      const volH = o.volume ? Math.round((H - padT - padB) * 0.15) : 0;
      const priceH = H - padT - padB - volH - (volH ? 8 : 0);
      const plotW = W - padL - padR;
      const s = this.start, e = this.end, count = e - s + 1;
      const step = plotW / count;
      const vis = bars.slice(s, e + 1);
      let lo = Math.min(...vis.map((b) => b.l)), hi = Math.max(...vis.map((b) => b.h));
      const lv = this.levelList();
      if (o.levels) lv.forEach((l) => { if (SM.isNum(l.p) && l.fit) { lo = Math.min(lo, l.p); hi = Math.max(hi, l.p); } });
      const pad = (hi - lo) * 0.06 || 1; lo -= pad; hi += pad;
      const x = (k) => padL + (k - s + 0.5) * step;
      const y = (p) => padT + ((hi - p) / (hi - lo)) * priceH;
      this.L = { W, H, padL, padR, padT, padB, step, x, y, priceH, volH, plotW, lo, hi };
      const off = d.offset || 0;
      const big = hi > 2000;
      const parts = [];
      const tags = []; // right-axis price tags, de-overlapped before drawing
      parts.push(`<defs><clipPath id="clip-${this.uid()}"><rect x="${padL}" y="${padT}" width="${plotW}" height="${priceH}"/></clipPath></defs>`);
      const clip = `clip-path="url(#clip-${this.uid()})"`;
      // grid & price axis
      for (const t of ticks(lo, hi, 6)) {
        parts.push(`<line x1="${padL}" x2="${padL + plotW}" y1="${y(t)}" y2="${y(t)}" stroke="var(--grid)"/>
          <text x="${W - padR + 6}" y="${y(t)}" dominant-baseline="middle" fill="var(--axis)" font-size="10.5">${pfmt(t, big)}</text>`);
      }
      // time axis
      const intraday = !["1D", "1W", "1M"].includes(d.timeframe);
      let lastLab = null, lastX = -1e9;
      for (let k = s; k <= e; k++) {
        const t = SM.parseT(bars[k].t);
        const lab = intraday ? `${t.getDate()} ${SM.months[t.getMonth()]}` : d.timeframe === "1D" ? (t.getMonth() === 0 ? String(t.getFullYear()) : SM.months[t.getMonth()]) : String(t.getFullYear());
        const key = intraday ? t.toDateString() : d.timeframe === "1D" ? t.getFullYear() * 12 + t.getMonth() : t.getFullYear();
        if (key !== lastLab) {
          if (x(k) - lastX > 56 && k > s) {
            parts.push(`<line x1="${x(k)}" x2="${x(k)}" y1="${padT}" y2="${H - padB}" stroke="var(--grid)"/>
              <text x="${x(k)}" y="${H - 6}" text-anchor="middle" fill="var(--axis)" font-size="10.5">${lab}</text>`);
            lastX = x(k);
          }
          lastLab = key;
        }
      }
      // zones
      if (o.zones) {
        (d.zones || []).forEach((z) => {
          const a = Math.max(s, z.origin_bar - off), b = Math.min(e, z.invalidation_bar != null ? z.invalidation_bar - off : bars.length - 1);
          if (b < s || a > e || a > b) return;
          const top = Math.max(z.proximal, z.distal), bot = Math.min(z.proximal, z.distal);
          const k = z.type === "DEMAND" ? "demand" : "supply";
          const x0 = x(a) - step / 2, w = x(b) - x(a) + step;
          const inval = z.status === "INVALIDATED";
          parts.push(`<g ${clip}><rect x="${x0}" y="${y(top)}" width="${w}" height="${Math.max(2, y(bot) - y(top))}" fill="var(--${k}-fill)" stroke="var(--${k})" stroke-opacity="${inval ? 0.5 : 0.9}" ${inval ? 'stroke-dasharray="4 3" fill-opacity="0.45"' : ""}>
            <title>${esc(z.type)} ${esc(z.pattern)} ${SM.fmt(z.proximal)}–${SM.fmt(z.distal)} · ${esc(z.status)} · created ${SM.date(z.creation_time)}</title></rect>
            ${w > 90 && !inval ? `<text x="${x0 + w - 6}" y="${y(top) + 12}" text-anchor="end" font-size="10.5" font-weight="700" fill="var(--${k})">${esc(SM.title(z.type))} (${esc(z.pattern)})${inval ? " · invalid" : ""}</text>` : ""}</g>`);
        });
      }
      // volume profile overlay
      const vp = d.profile;
      if (o.profile && vp) {
        const max = Math.max(...vp.volumes);
        const maxW = plotW * 0.2;
        const g = [];
        vp.volumes.forEach((v, k) => {
          const p0 = vp.price_low + k * vp.bin_size, p1 = p0 + vp.bin_size;
          if (p1 < lo || p0 > hi) return;
          const mid = (p0 + p1) / 2, inVA = mid >= vp.val && mid <= vp.vah;
          const w = (v / max) * maxW;
          g.push(`<rect x="${padL + plotW - w}" y="${y(p1) + 0.5}" width="${w}" height="${Math.max(1, y(p0) - y(p1) - 1)}" fill="${inVA ? "var(--profile-va)" : "var(--profile)"}" fill-opacity="${inVA ? 0.55 : 0.4}"/>`);
        });
        parts.push(`<g ${clip}>${g.join("")}
          <line x1="${padL}" x2="${padL + plotW}" y1="${y(vp.poc)}" y2="${y(vp.poc)}" stroke="var(--poc)" stroke-width="1.3" stroke-dasharray="6 4"/>
          <line x1="${padL + plotW - maxW}" x2="${padL + plotW}" y1="${y(vp.vah)}" y2="${y(vp.vah)}" stroke="var(--profile-va)" stroke-dasharray="2 3"/>
          <line x1="${padL + plotW - maxW}" x2="${padL + plotW}" y1="${y(vp.val)}" y2="${y(vp.val)}" stroke="var(--profile-va)" stroke-dasharray="2 3"/>
          ${(vp.hvn || []).filter((h) => h >= lo && h <= hi).map((h) => `<circle cx="${padL + plotW - maxW - 6}" cy="${y(h)}" r="3" fill="var(--accent)"><title>HVN ${SM.fmt(h)}</title></circle>`).join("")}
          ${(vp.lvn || []).filter((h) => h >= lo && h <= hi).map((h) => `<rect x="${padL + plotW - maxW - 9}" y="${y(h) - 3}" width="6" height="6" fill="var(--panel)" stroke="var(--muted)"><title>LVN ${SM.fmt(h)}</title></rect>`).join("")}</g>`);
        [["POC", vp.poc, "var(--poc)", "var(--bg)"], ["VAH", vp.vah, "var(--profile-va)", "var(--text)"], ["VAL", vp.val, "var(--profile-va)", "var(--text)"]].forEach(([n, p, c, ink]) => {
          if (p < lo || p > hi) return;
          tags.push({ y: y(p), text: `${n} ${pfmt(p, big)}`, bg: c, ink: n === "POC" ? "var(--accent-ink)" : ink, solid: n === "POC" });
        });
      }
      // volume bars
      if (o.volume) {
        const vmax = Math.max(...vis.map((b) => b.v)) || 1;
        const vy0 = padT + priceH + 8 + volH;
        const g = [];
        for (let k = s; k <= e; k++) {
          const b = bars[k], h = (b.v / vmax) * volH;
          g.push(`<rect x="${x(k) - Math.max(1, step * 0.32)}" y="${vy0 - h}" width="${Math.max(1, step * 0.64)}" height="${h}" fill="${b.c >= b.o ? "var(--candle-up)" : "var(--candle-down)"}" fill-opacity="0.45"/>`);
        }
        parts.push(g.join(""));
      }
      // candles
      const bw = Math.max(1, Math.min(13, step * 0.64));
      const cg = [];
      for (let k = s; k <= e; k++) {
        const b = bars[k], up = b.c >= b.o;
        const col = up ? "var(--candle-up)" : "var(--candle-down)";
        const top = y(Math.max(b.o, b.c)), bot = y(Math.min(b.o, b.c));
        cg.push(`<line x1="${x(k)}" x2="${x(k)}" y1="${y(b.h)}" y2="${y(b.l)}" stroke="${col}" stroke-width="1"/>`);
        const hollow = up && o.hollow && bw >= 3;
        cg.push(`<rect x="${x(k) - bw / 2}" y="${top}" width="${bw}" height="${Math.max(1, bot - top)}" fill="${hollow ? "var(--panel)" : col}" stroke="${col}" stroke-width="${hollow ? 1.2 : 0.6}"/>`);
      }
      parts.push(`<g ${clip}>${cg.join("")}</g>`);
      // zigzag
      const piv = (d.pivots || []).map((p, i) => ({ ...p, i, k: p.bar - off })).filter((p) => p.k >= 0);
      if (o.zigzag && piv.length) {
        const pts = piv.map((p) => `${x(p.k).toFixed(1)},${y(p.price).toFixed(1)}`);
        parts.push(`<g ${clip}><polyline points="${pts.join(" ")}" fill="none" stroke="var(--accent-2)" stroke-width="1.5" stroke-opacity="0.9"/>`);
        if (d.candidate) {
          const last = piv[piv.length - 1];
          parts.push(`<line x1="${x(last.k)}" y1="${y(last.price)}" x2="${x(d.candidate.bar - off)}" y2="${y(d.candidate.price)}" stroke="var(--accent-2)" stroke-width="1.3" stroke-dasharray="4 4"/>
            <circle cx="${x(d.candidate.bar - off)}" cy="${y(d.candidate.price)}" r="4" fill="none" stroke="var(--warn)" stroke-width="1.5"><title>Unconfirmed swing ${esc(d.candidate.type)} ${SM.fmt(d.candidate.price)} -- not used by the strategy</title></circle>`);
        }
        parts.push("</g>");
      }
      // pivot labels + confirmation markers
      if (o.labels) {
        piv.forEach((p) => {
          if (p.k < s || p.k > e) return;
          const isHigh = p.type === "HIGH";
          const py = y(p.price), dy = isHigh ? -10 : 16;
          const ck = p.confirmation_bar - off;
          const conf = ck >= s && ck <= e ? `<line x1="${x(p.k)}" x2="${x(ck)}" y1="${py}" y2="${py}" stroke="var(--muted)" stroke-dasharray="1 3"/>
            <path d="M${x(ck) - 3.5} ${py}L${x(ck)} ${py - 3.5}L${x(ck) + 3.5} ${py}L${x(ck)} ${py + 3.5}Z" fill="var(--panel)" stroke="var(--muted)"><title>Confirmed ${SM.date(p.confirmation_time)}</title></path>` : "";
          const lab = p.label || (isHigh ? "H" : "L");
          const good = ["HH", "HL"].includes(p.label), bad = ["LH", "LL"].includes(p.label);
          parts.push(`<g>${conf}<g class="pivot-hit" data-p="${p.i}" tabindex="-1"><circle cx="${x(p.k)}" cy="${py}" r="6" fill="transparent"/>
            <circle cx="${x(p.k)}" cy="${py}" r="2.6" fill="var(--accent-2)"/>
            <text x="${x(p.k)}" y="${py + dy}" text-anchor="middle" font-size="10.5" font-weight="700" fill="${good ? "var(--up)" : bad ? "var(--down)" : "var(--text-2)"}">${esc(lab)}</text>
            <title>${esc(lab)} ${SM.fmt(p.price)} · pivot ${SM.date(p.time)} · confirmed ${SM.date(p.confirmation_time)} (click for details)</title></g></g>`);
        });
      }
      // BOS / CHoCH
      if (o.events) {
        (d.events || []).forEach((ev) => {
          const a = Math.max(s, ev.level_bar - off), b = ev.bar - off;
          if (b < s || a > e) return;
          const col = ev.direction === "BULLISH" ? "var(--up)" : "var(--down)";
          parts.push(`<g ${clip}><line x1="${x(a)}" x2="${x(Math.min(b, e))}" y1="${y(ev.level)}" y2="${y(ev.level)}" stroke="${col}" stroke-dasharray="5 3" stroke-width="1.2"/>
            <text x="${(x(a) + x(Math.min(b, e))) / 2}" y="${y(ev.level) + (ev.direction === "BULLISH" ? -5 : 13)}" text-anchor="middle" font-size="10" font-weight="700" fill="${col}">${ev.type === "CHOCH" ? "CHoCH" : "BOS"}</text></g>`);
        });
      }
      // trade / plan levels
      if (o.levels) {
        lv.forEach((l) => {
          if (!SM.isNum(l.p) || l.p < lo || l.p > hi) return;
          parts.push(`<line x1="${padL}" x2="${padL + plotW}" y1="${y(l.p)}" y2="${y(l.p)}" stroke="${l.c}" stroke-width="${l.w || 1.3}" ${l.dash ? `stroke-dasharray="${l.dash}"` : ""}/>`);
          tags.push({ y: y(l.p), text: `${l.n} ${pfmt(l.p, big)}`, bg: l.c, ink: l.ink || "var(--bg)", solid: true });
        });
        const tr = d.trade;
        if (tr && tr.trail_history && tr.trail_history.length > 1) {
          const pts = [];
          tr.trail_history.forEach((h, i) => {
            const k = h.bar - off;
            const nk = i + 1 < tr.trail_history.length ? tr.trail_history[i + 1].bar - off : bars.length - 1;
            pts.push(`${x(Math.max(k, s))},${y(h.new)} ${x(Math.max(nk, s))},${y(h.new)}`);
          });
          parts.push(`<g ${clip}><polyline points="${pts.join(" ")}" fill="none" stroke="var(--warn)" stroke-width="1.6"/></g>`);
        }
      }
      // markers
      if (o.markers) {
        (d.markers || []).forEach((m) => {
          const k = m.bar - off;
          if (k < s || k > e) return;
          const long = m.direction === "LONG";
          const entry = m.kind === "entry";
          const below = entry ? long : !long;
          const b = bars[k];
          const py = below ? y(b.l) + 12 : y(b.h) - 12;
          const col = entry ? "var(--accent)" : "var(--warn)";
          const shape = entry
            ? (long ? `M${x(k)} ${py - 6}L${x(k) - 5} ${py + 3}L${x(k) + 5} ${py + 3}Z` : `M${x(k)} ${py + 6}L${x(k) - 5} ${py - 3}L${x(k) + 5} ${py - 3}Z`)
            : `M${x(k) - 4} ${py - 4}L${x(k) + 4} ${py + 4}M${x(k) + 4} ${py - 4}L${x(k) - 4} ${py + 4}`;
          parts.push(`<path d="${shape}" fill="${entry ? col : "none"}" stroke="${col}" stroke-width="${entry ? 1 : 2}"><title>${esc(m.kind === "entry" ? "Entry" : "Exit")} ${esc(m.direction)} ${SM.fmt(m.price)}${m.reason ? " · " + esc(m.reason) : ""} (${esc(m.trade_id)})</title></path>`);
        });
      }
      // last price
      const last = bars[bars.length - 1];
      if (last.c >= lo && last.c <= hi) {
        const col = last.c >= last.o ? "var(--up)" : "var(--down)";
        parts.push(`<line x1="${padL}" x2="${padL + plotW}" y1="${y(last.c)}" y2="${y(last.c)}" stroke="${col}" stroke-dasharray="1 3"/>`);
        tags.push({ y: y(last.c), text: pfmt(last.c, false), bg: col, ink: "var(--bg)", solid: true, prio: 1 });
      }
      // de-overlap: sort by y, push down to keep 19 px spacing, then pull back up inside the plot
      tags.sort((a, b) => a.y - b.y).forEach((t) => { t.y0 = t.y; });
      for (let k = 1; k < tags.length; k++) if (tags[k].y - tags[k - 1].y < 19) tags[k].y = tags[k - 1].y + 19;
      const maxY = padT + priceH - 9;
      for (let k = tags.length - 1; k >= 0; k--) {
        const limit = k === tags.length - 1 ? maxY : tags[k + 1].y - 19;
        if (tags[k].y > limit) tags[k].y = limit;
      }
      tags.forEach((t) => {
        if (Math.abs(t.y - t.y0) > 2) parts.push(`<line x1="${W - padR - 6}" x2="${W - padR + 1}" y1="${t.y0}" y2="${t.y}" stroke="${t.bg}" stroke-width="1"/>`);
        parts.push(this.tag(W - padR, t.y, t.text, t.bg, t.ink, t.solid));
      });
      parts.push(`<g class="xhair"></g>`);
      this.svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
      this.svg.setAttribute("height", H);
      this.svg.innerHTML = parts.join("");
      this.drawCursor();
    }
    uid() { if (!this._uid) this._uid = Math.random().toString(36).slice(2, 8); return this._uid; }
    tag(x0, yy, text, bg, ink, solid) {
      const w = Math.max(44, text.length * 6.4 + 10);
      return `<g><rect x="${x0 + 1}" y="${yy - 9}" width="${w}" height="18" rx="3" fill="${solid ? bg : "var(--panel)"}" stroke="${bg}"/>
        <text x="${x0 + 6}" y="${yy + 0.5}" dominant-baseline="middle" font-size="10.5" font-weight="700" fill="${solid ? ink : bg}">${esc(text)}</text></g>`;
    }
    levelList() {
      const d = this.data, out = [];
      const t = d.trade, p = d.plan;
      if (t) {
        out.push({ n: "Entry", p: t.entry, c: "var(--accent)", ink: "var(--accent-ink)", w: 1.6, fit: true });
        out.push({ n: "SL", p: t.current_stop, c: "var(--down)", w: 1.4, fit: true });
        if (t.current_stop !== t.initial_stop) out.push({ n: "Init SL", p: t.initial_stop, c: "var(--down)", dash: "2 3", fit: false });
        t.targets.forEach((v, i) => out.push({ n: `T${i + 1}`, p: v, c: "var(--up)", dash: t.targets_hit[i] ? "1 3" : "6 4", fit: i < 2 }));
      } else if (p && p.stop) {
        out.push({ n: "Entry", p: p.entry, c: "var(--accent)", ink: "var(--accent-ink)", w: 1.4, fit: true });
        out.push({ n: "SL", p: p.stop, c: "var(--down)", fit: true });
        ["t1", "t2", "t3"].forEach((k, i) => out.push({ n: `T${i + 1}`, p: p[k], c: "var(--up)", dash: "6 4", fit: i < 1 }));
      }
      return out;
    }
    drawCursor() {
      const L = this.L; if (!L) return;
      const g = this.svg.querySelector(".xhair");
      const k = this.cursor != null ? this.cursor : this.data.bars.length - 1;
      const b = this.data.bars[k];
      const prev = this.data.bars[k - 1];
      const chg = prev ? b.c - prev.c : 0;
      const pc = prev ? (chg / prev.c) * 100 : 0;
      const big = L.hi > 2000;
      this.readout.innerHTML = `<span>${SM.date(b.t)}${["1D", "1W", "1M"].includes(this.data.timeframe) ? "" : " " + SM.time(b.t)}</span>
        <span>O <b>${pfmt(b.o, false)}</b></span><span>H <b>${pfmt(b.h, false)}</b></span><span>L <b>${pfmt(b.l, false)}</b></span>
        <span>C <b>${pfmt(b.c, false)}</b></span><span class="${SM.dir(chg)}">${SM.signed(chg, 2)} (${SM.signed(pc, 2)}%)</span>
        <span>Vol <b>${SM.compact(b.v)}</b></span>`;
      if (!g) return;
      if (this.cursor == null) { g.innerHTML = ""; return; }
      const cx = L.x(k);
      g.innerHTML = `<line x1="${cx}" x2="${cx}" y1="${L.padT}" y2="${L.H - L.padB}" stroke="var(--muted)" stroke-dasharray="3 3" stroke-opacity="0.8"/>
        ${this.tag(L.W - L.padR, L.y(b.c), pfmt(b.c, big && false), "var(--text)", "var(--bg)", true)}`;
    }
  }
  charts.CandleChart = CandleChart;

  // ------------------------------------------------------------------ resize helper
  function observe(el, fn) {
    if (!window.ResizeObserver) return;
    let w = el.clientWidth;
    const ro = new ResizeObserver(SM.debounce(() => {
      if (!el.isConnected) { ro.disconnect(); return; }
      if (Math.abs(el.clientWidth - w) > 4) { w = el.clientWidth; fn(); }
    }, 120));
    ro.observe(el);
  }
})();
