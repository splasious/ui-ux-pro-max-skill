"""Structural stop placement (Section 23).

LONG : below the demand distal line OR the last confirmed swing low, minus an ATR buffer.
SHORT: above the supply distal line OR the last confirmed swing high, plus an ATR buffer.

STOP_REFERENCE = ZONE | SWING | WIDER (the more protective of the two).
"""
from __future__ import annotations

from typing import Iterable, Optional, Tuple

from ..schemas import Pivot, Zone


def structural_stop(spec, zone: Zone, pivots: Iterable[Pivot], atr: float, entry: float, reference: str,
                    buffer_atr: float) -> Tuple[Optional[float], str]:
    buf = buffer_atr * atr
    zone_level = zone.distal
    swing: Optional[Pivot] = None
    for p in reversed(list(pivots)):
        if p.pivot_type == spec.stop_pivot_type and spec.better(entry, p.pivot_price):
            swing = p
            break
    reference = reference.upper()
    if reference == "SWING" and swing is not None:
        level, why = swing.pivot_price, f"confirmed swing {spec.stop_pivot_type.lower()} {swing.pivot_price:.2f}"
    elif reference == "WIDER" and swing is not None:
        level = min(zone_level, swing.pivot_price) if spec.sign > 0 else max(zone_level, swing.pivot_price)
        why = "wider of zone distal and confirmed swing"
    else:
        level, why = zone_level, f"{zone.zone_type.lower()} distal {zone_level:.2f}"
    stop = level - buf if spec.sign > 0 else level + buf
    if not spec.better(entry, stop):
        return None, "stop would sit on the wrong side of entry"
    return stop, f"{why} {'-' if spec.sign > 0 else '+'} {buffer_atr:g} ATR"
