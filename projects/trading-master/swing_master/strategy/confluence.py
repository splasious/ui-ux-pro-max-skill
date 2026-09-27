"""Confluence score 0-100 (Section 21) -- every contribution is exposed."""
from __future__ import annotations

from typing import Dict, Iterable, Optional

from ..config.scoring_config import CONFLUENCE_WEIGHTS
from ..schemas import Trend
from ..zones.zone_quality import score_components


def structure_fraction(spec, trend: str, last_low_label: Optional[str], last_high_label: Optional[str]) -> float:
    if trend == spec.trend:
        return 1.0
    if trend == spec.opposite_trend:
        return 0.0
    supportive = last_low_label == "HL" if spec.sign > 0 else last_high_label == "LH"
    if trend in (Trend.TRANSITION, Trend.CONSOLIDATION):
        return 0.5 if supportive else 0.3
    return 0.25


def bos_fraction_setup(spec, events: Iterable, origin_bar: int, as_of: int, lookback: int = 40) -> (float, str):
    """Bullish BOS since the zone formed = 1.0, CHoCH = 0.6; an opposite CHoCH/BOS afterwards cancels it."""
    best, detail, last_supportive = 0.0, "No structure break in setup direction", -1
    opposite_after = None
    for ev in events:
        if ev.event_bar > as_of or ev.event_bar < min(origin_bar, as_of - lookback):
            continue
        if ev.direction == spec.event_direction:
            frac = 1.0 if ev.event_type == "BOS" else 0.6
            if frac >= best:
                best, last_supportive = frac, ev.event_bar
                detail = f"{ev.direction.title()} {ev.event_type} through {ev.level:.2f}"
        elif ev.event_bar > last_supportive:
            opposite_after = ev
    if opposite_after is not None and opposite_after.event_bar > last_supportive:
        return 0.0, f"Opposite {opposite_after.event_type} at {opposite_after.level:.2f} after the last supportive break"
    return best, detail


def score_confluence(fractions: Dict[str, Optional[float]], policy: str = "RENORMALIZE", disabled=()) -> Dict:
    return score_components(fractions, CONFLUENCE_WEIGHTS, policy, disabled)
