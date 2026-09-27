"""Transparent zone scoring 0-100 (Section 10).

Each component returns a fraction 0..1 (or ``None`` when its input data is
unavailable).  :func:`score_components` turns the fractions into a score with
the configured weights and the configured unavailable-data policy.
"""
from __future__ import annotations

from typing import Dict, Iterable, Optional

from ..config.scoring_config import ZONE_SCORE_WEIGHTS
from ..indicators.utilities import clamp
from ..schemas import Pivot, StructureEvent, Trend, Zone


def freshness_fraction(prior_tests: int) -> float:
    return {0: 1.0, 1: 0.6}.get(prior_tests, 0.2)


def departure_fraction(departure_atr: float) -> float:
    """1 ATR of departure beyond the base = 0.5, 2 ATR or more = 1.0."""
    return clamp(departure_atr / 2.0)


def time_in_base_fraction(base_bars: int) -> float:
    return {1: 1.0, 2: 1.0, 3: 0.7, 4: 0.4}.get(base_bars, 0.2)


def pivot_alignment_fraction(zone: Zone, pivots: Iterable[Pivot], atr: float) -> float:
    """1.0 when a confirmed pivot in the zone's direction formed inside/at the zone."""
    want = "LOW" if zone.zone_type == "DEMAND" else "HIGH"
    pad = 0.25 * atr
    for p in pivots:
        if p.pivot_type != want:
            continue
        if zone.origin_bar - 2 <= p.pivot_bar <= zone.creation_bar + 1 and \
                zone.bottom - pad <= p.pivot_price <= zone.top + pad:
            return 1.0
    return 0.0


def bos_fraction(zone: Zone, events: Iterable[StructureEvent], as_of: int) -> float:
    want = "BULLISH" if zone.zone_type == "DEMAND" else "BEARISH"
    best = 0.0
    for ev in events:
        if ev.direction != want or ev.event_bar < zone.origin_bar or ev.event_bar > as_of:
            continue
        best = max(best, 1.0 if ev.event_type == "BOS" else 0.6)
    return best


def htf_fraction(zone_type: str, htf_trend: Optional[str]) -> Optional[float]:
    if htf_trend is None:
        return None
    bullish = zone_type == "DEMAND"
    if htf_trend == Trend.BULLISH:
        return 1.0 if bullish else 0.0
    if htf_trend == Trend.BEARISH:
        return 0.0 if bullish else 1.0
    return 0.5


def zone_components(zone: Zone, as_of: int, current_bar_touch: bool, pivots, events, atr: float,
                    htf_trend: Optional[str], poc_fraction: Optional[float], vp_fraction: Optional[float],
                    positioning_fraction: Optional[float], candle_fraction: Optional[float],
                    rr_frac: Optional[float]) -> Dict[str, Optional[float]]:
    touches = zone.touches_as_of(as_of)
    prior = max(0, touches - 1) if current_bar_touch else touches
    return {
        "freshness": freshness_fraction(prior),
        "base_quality": zone.base_quality,
        "departure": departure_fraction(zone.departure_strength),
        "time_in_base": time_in_base_fraction(zone.base_bars),
        "pivot_alignment": pivot_alignment_fraction(zone, pivots, atr),
        "bos_relationship": bos_fraction(zone, events, as_of),
        "htf_alignment": htf_fraction(zone.zone_type, htf_trend),
        "poc_relationship": poc_fraction,
        "volume_profile": vp_fraction,
        "positioning": positioning_fraction,
        "candlestick": candle_fraction,
        "risk_reward": rr_frac,
    }


def score_components(fractions: Dict[str, Optional[float]], weights: Dict[str, Dict],
                     policy: str = "RENORMALIZE", disabled: Iterable[str] = ()) -> Dict:
    """Generic weighted score used by BOTH the zone score and the confluence score.

    ``disabled`` holds ablation component names; factors owned by a disabled
    component are excluded entirely (neither earned nor available).
    """
    disabled = set(disabled)
    earned = available = total = 0.0
    rows = []
    for key, meta in weights.items():
        if meta["component"] in disabled:
            continue
        w = float(meta["weight"])
        total += w
        frac = fractions.get(key)
        if frac is None:
            rows.append((key, meta, None))
            continue
        available += w
        earned += w * frac
        rows.append((key, meta, frac))
    coverage = available / total if total else 0.0
    if policy == "ZERO":
        score = 100.0 * earned / total if total else 0.0
    else:  # RENORMALIZE and REJECT both report the available-factor score
        score = 100.0 * earned / available if available else 0.0
    return {
        "score": round(score, 2),
        "raw_points": round(earned, 2),
        "available_points": round(available, 2),
        "total_points": round(total, 2),
        "coverage": round(coverage, 4),
        "unavailable": [k for k, _, f in rows if f is None],
        "rows": [
            {"key": k, "name": m["name"], "weight": m["weight"], "component": m["component"],
             "fraction": None if f is None else round(f, 4),
             "points": None if f is None else round(m["weight"] * f, 2)}
            for k, m, f in rows
        ],
    }


def score_zone(fractions: Dict[str, Optional[float]], policy: str = "RENORMALIZE", disabled=()) -> Dict:
    return score_components(fractions, ZONE_SCORE_WEIGHTS, policy, disabled)
