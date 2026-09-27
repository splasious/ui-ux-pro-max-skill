"""Structural trailing stop (Section 26).

LONG : ENTRY -> HH1 -> confirmed HL1 -> trail below HL1 -> HH2 -> confirmed HL2 -> ...
SHORT: mirrored with confirmed LH.

Rules
* Only a CONFIRMED pivot formed after entry can move the stop.
* The stop may tighten but never loosen.
"""
from __future__ import annotations

from typing import Optional

from ..schemas import Pivot


def trail_candidate(spec, pivot: Pivot, entry_bar: int, atr: Optional[float], buffer_atr: float) -> Optional[float]:
    if pivot.label != spec.trail_label or pivot.pivot_bar <= entry_bar:
        return None
    buf = (atr or 0.0) * buffer_atr
    return pivot.pivot_price - buf if spec.sign > 0 else pivot.pivot_price + buf


def tighten(spec, current: float, proposed: Optional[float]) -> float:
    """Return the new stop: ``proposed`` only if it is tighter, otherwise ``current``."""
    if proposed is None:
        return current
    return max(current, proposed) if spec.sign > 0 else min(current, proposed)
