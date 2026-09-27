"""Zone lifecycle: touches and invalidation, processed one closed bar at a time.

A zone can only be touched on bars AFTER its creation bar.  A new touch is
counted when price re-enters the zone after having been outside it.

Invalidation modes (Section 9):
* WICK  -- any trade beyond the distal line invalidates.
* CLOSE -- a close beyond the distal line invalidates.
"""
from __future__ import annotations

from ..schemas import Bar, Zone


def update_zone(zone: Zone, i: int, bar: Bar, touch_buffer: float = 0.0) -> None:
    if i <= zone.creation_bar or zone.invalidation_bar is not None:
        return
    if zone.zone_type == "DEMAND":
        entered = bar.low <= zone.proximal + touch_buffer
        broken = (bar.low < zone.distal) if zone.invalidation_mode == "WICK" else (bar.close < zone.distal)
    else:
        entered = bar.high >= zone.proximal - touch_buffer
        broken = (bar.high > zone.distal) if zone.invalidation_mode == "WICK" else (bar.close > zone.distal)

    if entered and not zone._inside:
        zone.touches.append(i)
    zone._inside = entered
    if broken:
        zone.invalidation_bar = i
        zone.invalidation_timestamp = bar.close_time


def price_interacts(zone: Zone, bar: Bar, buffer: float) -> bool:
    """True when this bar traded into the zone (plus buffer) without closing through it."""
    if zone.zone_type == "DEMAND":
        return bar.low <= zone.proximal + buffer and bar.close >= zone.distal
    return bar.high >= zone.proximal - buffer and bar.close <= zone.distal


def distance_to_zone(zone: Zone, price: float) -> float:
    """Signed distance from price to the zone's proximal line (positive = not yet reached)."""
    if zone.zone_type == "DEMAND":
        return price - zone.proximal
    return zone.proximal - price
