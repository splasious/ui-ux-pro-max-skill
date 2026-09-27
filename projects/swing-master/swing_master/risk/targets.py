"""Profit targets T1 / T2 / T3 with ordering validation (Section 24).

T1: 1R | nearest POC | nearest HVN | nearest structural level | NEAREST of those
T2: previous confirmed HH (long) / LL (short) or the opposing zone, else 2R
T3: higher-timeframe opposing zone / major structural level, else 3R

Targets must be strictly ordered away from entry (entry < T1 < T2 < T3 for a
long).  Any structural candidate that breaks the ordering is replaced by its
R-multiple fallback and the substitution is reported.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from ..schemas import Pivot, VolumeProfile, Zone


def _beyond(spec, entry: float, level: float, min_dist: float) -> bool:
    return (level - entry) * spec.sign > min_dist


def _nearest(spec, entry: float, levels: Iterable[float], min_dist: float) -> Optional[float]:
    cands = [lv for lv in levels if _beyond(spec, entry, lv, min_dist)]
    if not cands:
        return None
    return min(cands, key=lambda lv: abs(lv - entry))


def compute_targets(spec, entry: float, stop: float, pivots: List[Pivot], zones: List[Zone],
                    vp: Optional[VolumeProfile], htf_zones: List[Zone], cfg) -> Dict:
    risk = abs(entry - stop)
    r = lambda k: entry + spec.sign * k * risk  # noqa: E731
    notes = []
    struct_levels = [p.pivot_price for p in pivots if p.pivot_type == spec.target_pivot_type]
    opp_zones = [z.proximal for z in zones if z.zone_type == spec.opposing_zone_type]

    # ---- T1 ---------------------------------------------------------------
    t1_cands = {
        "R": r(cfg.TARGET_1_R),
        "POC": _nearest(spec, entry, [vp.poc] if vp else [], 0.5 * risk),
        "HVN": _nearest(spec, entry, vp.hvn if vp else [], 0.5 * risk),
        "STRUCTURE": _nearest(spec, entry, struct_levels, 0.5 * risk),
    }
    method = cfg.T1_METHOD.upper()
    if method == "NEAREST":
        valid = [v for v in t1_cands.values() if v is not None]
        t1 = min(valid, key=lambda v: abs(v - entry))
        t1_how = "nearest of 1R / POC / HVN / structure"
    else:
        t1 = t1_cands.get(method)
        t1_how = f"{method}"
        if t1 is None:
            t1, t1_how = t1_cands["R"], f"{cfg.TARGET_1_R:g}R (no {method} level available)"
        elif method == "R":
            t1_how = f"{cfg.TARGET_1_R:g}R"

    # ---- T2 ---------------------------------------------------------------
    t2, t2_how = r(cfg.TARGET_2_R), f"{cfg.TARGET_2_R:g}R"
    if cfg.T2_METHOD.upper() == "STRUCTURE_OR_R":
        structural = _nearest(spec, entry, struct_levels + opp_zones, 1.5 * risk)
        if structural is not None and abs(structural - entry) <= 4 * risk:
            t2 = structural
            is_zone = structural in opp_zones
            t2_how = f"{'opposing ' + spec.opposing_zone_type.lower() if is_zone else 'prior confirmed ' + ('HH' if spec.sign > 0 else 'LL')}"

    # ---- T3 ---------------------------------------------------------------
    t3, t3_how = r(cfg.TARGET_3_R), f"{cfg.TARGET_3_R:g}R"
    if cfg.T3_METHOD.upper() == "HTF_OR_R":
        htf_levels = [z.proximal for z in htf_zones if z.zone_type == spec.opposing_zone_type]
        structural = _nearest(spec, entry, htf_levels, abs(t2 - entry) + 0.5 * risk)
        if structural is not None and abs(structural - entry) <= 8 * risk:
            t3, t3_how = structural, f"higher-TF {spec.opposing_zone_type.lower()}"

    targets = [t1, t2, t3]
    hows = [t1_how, t2_how, t3_how]
    fallbacks = [r(cfg.TARGET_1_R), r(cfg.TARGET_2_R), r(cfg.TARGET_3_R)]
    ok = validate_order(spec, entry, targets)
    if not ok:
        for k in range(3):
            prev = entry if k == 0 else targets[k - 1]
            if not _beyond(spec, prev, targets[k], 0.0):
                targets[k] = max(fallbacks[k], prev + spec.sign * 0.5 * risk) if spec.sign > 0 else \
                    min(fallbacks[k], prev + spec.sign * 0.5 * risk)
                notes.append(f"T{k + 1} {hows[k]} broke ordering; replaced with R-multiple")
                hows[k] = "R-multiple fallback"
    return {"t1": targets[0], "t2": targets[1], "t3": targets[2], "methods": hows, "notes": notes,
            "valid": validate_order(spec, entry, targets)}


def validate_order(spec, entry: float, targets: List[float]) -> bool:
    seq = [entry] + list(targets)
    return all((b - a) * spec.sign > 0 for a, b in zip(seq, seq[1:]))


def reward_risk(entry: float, stop: float, target: float) -> Optional[float]:
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    return abs(target - entry) / risk
