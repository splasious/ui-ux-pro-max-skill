"""Factor attribution (Section 42): performance grouped by the context each trade was taken in."""
from __future__ import annotations

from typing import Callable, Dict, List


def _bucket_score(x) -> str:
    if x is None:
        return "n/a"
    for lo in (90, 80, 75, 70, 60):
        if x >= lo:
            return f"{lo}+"
    return "<60"


def _pcr_range(x) -> str:
    if x is None:
        return "UNAVAILABLE"
    if x < 0.8:
        return "< 0.8"
    if x < 1.2:
        return "0.8 - 1.2"
    if x < 1.6:
        return "1.2 - 1.6"
    return ">= 1.6"


DIMENSIONS: Dict[str, Callable] = {
    "Confluence score": lambda t: _bucket_score(t.snapshot.get("confluence")),
    "Zone score": lambda t: _bucket_score(t.snapshot.get("zone_score")),
    "Zone freshness": lambda t: "FRESH" if t.snapshot.get("zone_prior_tests") == 0 else "TESTED",
    "Structure": lambda t: t.snapshot.get("structure") or "n/a",
    "Higher-TF structure": lambda t: t.snapshot.get("htf_structure") or "n/a",
    "POC relationship": lambda t: t.snapshot.get("poc_relation") or "n/a",
    "Pattern": lambda t: t.snapshot.get("candlestick") or "NONE",
    "Commercial": lambda t: t.snapshot.get("commercial") or "UNAVAILABLE",
    "Institutional": lambda t: t.snapshot.get("institutional") or "UNAVAILABLE",
    "Retail": lambda t: t.snapshot.get("retail") or "UNAVAILABLE",
    "Positioning divergence": lambda t: "UNAVAILABLE" if t.snapshot.get("retail") in (None, "UNAVAILABLE") else "EVALUATED",
    "OI state": lambda t: t.snapshot.get("oi_state") or "UNAVAILABLE",
    "PCR range": lambda t: _pcr_range(t.snapshot.get("pcr")),
    "Timeframe": lambda t: t.timeframe,
    "Direction": lambda t: t.direction,
    "Exit reason": lambda t: t.exit_reason or "OPEN",
}


def attribution(trades: List) -> List[Dict]:
    out = []
    for dim, keyf in DIMENSIONS.items():
        groups: Dict[str, List] = {}
        for t in trades:
            groups.setdefault(str(keyf(t)), []).append(t)
        rows = []
        for key, ts in sorted(groups.items()):
            rs = [x.r_multiple() or 0.0 for x in ts]
            pnl = [x.net_pnl for x in ts]
            gw = sum(p for p in pnl if p > 0)
            gl = -sum(p for p in pnl if p <= 0)
            rows.append({"bucket": key, "trades": len(ts), "win_rate": round(sum(1 for p in pnl if p > 0) / len(ts), 3),
                         "avg_r": round(sum(rs) / len(ts), 3), "net_pnl": round(sum(pnl), 2),
                         "profit_factor": round(gw / gl, 2) if gl > 0 else None})
        out.append({"dimension": dim, "rows": rows})
    return out
