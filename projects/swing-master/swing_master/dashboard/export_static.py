"""Export a self-contained, read-only HTML snapshot of the dashboard.

Every API response the UI needs is pre-computed and embedded as
``window.__SM_SNAPSHOT__``; the front end reads it instead of calling the
server.  Screens or symbols that were not exported say so explicitly.

    python -m swing_master.main export-static dist/swing-master.html
    python -m swing_master.main export-static dist/page.html --artifact   # no <html>/<head>/<body> wrapper
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from urllib.parse import quote

from ..schemas import to_jsonable
from . import api

UI = Path(__file__).resolve().parent / "application_ui"
SCRIPTS = ["core.js", "components.js", "charts.js", "views-market.js", "views-analysis.js", "views-exec.js",
           "views-research.js", "views-system.js", "app.js"]
FONTS = ("https://fonts.googleapis.com/css2?family=Cinzel:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600;700"
         "&family=JetBrains+Mono:wght@400;500;600&family=Manrope:wght@400;500;600;700;800"
         "&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Rajdhani:wght@500;600;700"
         "&family=Sora:wght@500;600;700&display=swap")


def _enc(v: Any) -> str:
    # mirrors JavaScript encodeURIComponent
    return quote(str(v), safe="-_.!~*'()")


def key(path: str, params: Dict[str, Any] = None) -> str:
    params = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
    if not params:
        return path
    return path + "?" + "&".join(f"{_enc(k)}={_enc(params[k])}" for k in sorted(params))


def collect(p) -> Dict[str, Any]:
    data: Dict[str, Any] = {}

    def put(path, params, fn):
        try:
            data[key(path, params)] = to_jsonable(fn())
        except Exception as exc:  # recorded, not hidden: the UI shows the view as unavailable
            data.setdefault("__errors__", []).append(f"{key(path, params)}: {exc}")

    put("/api/meta", {}, lambda: api.meta(p))
    ov = api.overview(p)
    data[key("/api/overview")] = to_jsonable(ov)
    for path, fn in [("/api/scanner", lambda: api.scanner(p)), ("/api/positioning", lambda: api.positioning_payload(p)),
                     ("/api/trades", lambda: api.trades_payload(p)), ("/api/risk", lambda: api.risk_payload(p)),
                     ("/api/backtest", lambda: api.backtest_payload(p)), ("/api/backtest/ablation", lambda: api.ablation_payload(p)),
                     ("/api/reports", lambda: api.reports_payload(p)), ("/api/health", lambda: api.health_payload(p)),
                     ("/api/settings", lambda: api.settings_payload(p)),
                     ("/api/notifications", lambda: api.notifications_payload(p)), ("/api/proposals", p.proposals)]:
        put(path, {}, fn)
    put("/api/walkforward", {}, lambda: api.walk_forward_payload(p, background=False))
    put("/api/reports", {}, lambda: api.reports_payload(p))  # again, now with the walk-forward summary
    put("/api/rejected", {"limit": 300}, lambda: api.rejected_payload(p, limit=180))
    put("/api/scanner", {"tf": "1W"}, lambda: api.scanner(p, tf="1W"))
    for src in ("backtest", "paper"):
        put("/api/journal", {"source": src}, lambda s=src: api.journal_payload(p, s))

    focus = {ov["focus_symbol"], p._anchor_symbol()}
    mtf_syms = focus | {r["symbol"] for r in p.scan["rows"] if r["status"] != "REJECTED"}
    for s in sorted(mtf_syms):
        put("/api/mtf", {"symbol": s}, lambda s=s: api.mtf_payload(p, s))
    for inst in p.universe:
        s = inst.symbol
        put("/api/chart", {"symbol": s, "tf": "1D", "profile": "FIXED"}, lambda s=s: api.chart(p, s, "1D", "FIXED", 260))
        put("/api/setup", {"symbol": s, "tf": "1D"}, lambda s=s: api.setup_payload(p, s, "1D"))
        put("/api/zones", {"symbol": s, "tf": "1D"}, lambda s=s: api.zones_payload(p, s, "1D"))
        put("/api/volume-profile", {"symbol": s, "tf": "1D", "type": "FIXED"},
            lambda s=s: api.volume_profile_payload(p, s, "1D", "FIXED"))
        put("/api/candles", {"symbol": s, "tf": "1D", "lookback": 60}, lambda s=s: api.candles_payload(p, s, "1D", 60))
        put("/api/derivatives", {"symbol": s, "days": 30}, lambda s=s: api.derivatives_payload(p, s, 30))
    for s in focus:
        for tf in ("1M", "1W", "4H", "1H", "15m", "5m"):
            put("/api/chart", {"symbol": s, "tf": tf, "profile": "FIXED"}, lambda s=s, tf=tf: api.chart(p, s, tf, "FIXED", 260))
        for prof in ("SWING", "STRUCTURAL_LEG", "DAILY", "WEEKLY"):
            put("/api/chart", {"symbol": s, "tf": "1D", "profile": prof}, lambda s=s, pr=prof: api.chart(p, s, "1D", pr, 260))
            put("/api/volume-profile", {"symbol": s, "tf": "1D", "type": prof},
                lambda s=s, pr=prof: api.volume_profile_payload(p, s, "1D", pr))
        put("/api/zones", {"symbol": s, "tf": "1W"}, lambda s=s: api.zones_payload(p, s, "1W"))
        for days in (20, 60, 90):
            put("/api/derivatives", {"symbol": s, "days": days}, lambda s=s, d=days: api.derivatives_payload(p, s, d))
        for n in (5, 15):
            put("/api/derivatives", {"symbol": s, "days": 30, "strikes": n}, lambda s=s, n=n: api.derivatives_payload(p, s, 30, n))
        for lb in (60, 250):
            put("/api/volume-profile", {"symbol": s, "tf": "1D", "type": "FIXED", "lookback": lb},
                lambda s=s, lb=lb: api.volume_profile_payload(p, s, "1D", "FIXED", lb))
        put("/api/volume-profile", {"symbol": s, "tf": "1D", "type": "HIGHER_TF"},
            lambda s=s: api.volume_profile_payload(p, s, "1D", "HIGHER_TF"))
    for t in list(p.backtest.trades) + list(p.paper.trades) + list(p.paper.open_trades):
        put(f"/api/journal/{_enc(t.trade_id)}", {}, lambda tid=t.trade_id: api.journal_detail(p, tid))
    return data


def build_html(p, artifact: bool = False) -> str:
    data = collect(p)
    payload = json.dumps({"generated": p.as_of.isoformat(), "data": data}, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")
    css = (UI / "css" / "themes.css").read_text() + "\n" + (UI / "css" / "app.css").read_text()
    js = "\n".join((UI / "js" / f).read_text() for f in SCRIPTS)
    head = f"""<title>Swing Master</title>
<meta name="description" content="Swing-trading research terminal with five interchangeable themes (static demo snapshot).">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS}">
<style>
{css}
</style>
<script>try {{ var s = JSON.parse(localStorage.getItem("tm.skin") || '"auto"'); if (s && s !== "auto") document.documentElement.setAttribute("data-skin", s); }} catch (e) {{}}</script>"""
    body = f"""<div id="app"><div class="loading" role="status">Loading Swing Master…</div></div>
<script>window.__SM_SNAPSHOT__ = {payload};</script>
<script>
{js}
</script>"""
    if artifact:
        return head + "\n" + body + "\n"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
{head}
</head>
<body>
{body}
</body>
</html>
"""


def export(p, out: str, artifact: bool = False) -> int:
    html = build_html(p, artifact)
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return len(html.encode("utf-8"))
