"""POC / value-area confluence with an active zone (Section 12).

Each level (POC, VAH, VAL, every HVN/LVN) is classified INSIDE / NEAR / FAR
relative to the zone, with distance normalised by ATR.  The combined score is
a transparent weighted sum:

    0.45 x POC   (INSIDE 1.0, NEAR 0.6, FAR 0)
  + 0.30 x value edge on the zone's side (VAL for demand, VAH for supply)
  + 0.25 x best HVN          (INSIDE 1.0, NEAR 0.5)
  - 0.15 if an LVN sits inside the zone (thin acceptance, price slips through)
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..indicators.utilities import clamp
from ..schemas import VolumeProfile, Zone


def relation(level: float, zone: Zone, atr: float, near_atr: float) -> Dict:
    lo, hi = zone.bottom, zone.top
    if lo <= level <= hi:
        dist = 0.0
        rel = "INSIDE"
    else:
        dist = (lo - level) if level < lo else (level - hi)
        rel = "NEAR" if atr and dist <= near_atr * atr else "FAR"
    return {"level": round(level, 4), "relation": rel,
            "distance_atr": round(dist / atr, 2) if atr else None}


_POC = {"INSIDE": 1.0, "NEAR": 0.6, "FAR": 0.0}
_HVN = {"INSIDE": 1.0, "NEAR": 0.5, "FAR": 0.0}


def zone_profile_confluence(zone: Zone, vp: Optional[VolumeProfile], atr: float, near_atr: float = 0.5) -> Dict:
    if vp is None or not atr:
        return {"available": False, "score": None, "poc_fraction": None, "levels": {}}
    poc = relation(vp.poc, zone, atr, near_atr)
    edge_level = vp.val if zone.zone_type == "DEMAND" else vp.vah
    edge = relation(edge_level, zone, atr, near_atr)
    hvns: List[Dict] = [relation(h, zone, atr, near_atr) for h in vp.hvn]
    lvns: List[Dict] = [relation(x, zone, atr, near_atr) for x in vp.lvn]
    best_hvn = max((_HVN[h["relation"]] for h in hvns), default=0.0)
    lvn_inside = any(x["relation"] == "INSIDE" for x in lvns)
    score = clamp(0.45 * _POC[poc["relation"]] + 0.30 * _POC[edge["relation"]] + 0.25 * best_hvn
                  - (0.15 if lvn_inside else 0.0))
    poc_frac = {"INSIDE": 1.0, "NEAR": 0.6, "FAR": 0.2}[poc["relation"]]
    return {
        "available": True,
        "score": round(score, 4),
        "poc_fraction": poc_frac,
        "levels": {
            "POC": poc,
            "VAH": relation(vp.vah, zone, atr, near_atr),
            "VAL": relation(vp.val, zone, atr, near_atr),
            "HVN": hvns,
            "LVN": lvns,
        },
        "lvn_inside": lvn_inside,
    }


def price_location(price: float, vp: Optional[VolumeProfile]) -> Optional[str]:
    if vp is None:
        return None
    if price > vp.vah:
        return "ABOVE VALUE"
    if price < vp.val:
        return "BELOW VALUE"
    return "INSIDE VALUE"
