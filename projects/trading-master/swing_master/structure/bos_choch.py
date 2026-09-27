"""Break of Structure / Change of Character (Section 8).

* BOS  -- a close through the latest confirmed swing level IN the direction
          of the prevailing bias (continuation).
* CHoCH -- the first close through a confirmed swing level AGAINST the
          prevailing bias.  It is an early warning only: it never changes
          the HH/HL-derived trend state by itself.

Bias = confirmed trend when BULLISH/BEARISH, otherwise the direction of the
most recent structure event.  Each swing level can be broken only once.
"""
from __future__ import annotations

from typing import List, Optional

from ..schemas import Bar, StructureEvent, Trend
from .market_structure import MarketStructure


class StructureEventDetector:
    def __init__(self, break_mode: str = "CLOSE"):
        self.break_mode = break_mode.upper()
        self.events: List[StructureEvent] = []
        self._broken: set = set()  # pivot seq numbers already broken
        self._last_direction: Optional[str] = None
        self.state: str = Trend.UNDEFINED
        self.by_bar = {}

    def update(self, i: int, bar: Bar, structure: MarketStructure) -> List[StructureEvent]:
        out: List[StructureEvent] = []
        trend = structure.trend
        bias = trend if trend in (Trend.BULLISH, Trend.BEARISH) else self._last_direction

        hi = structure.highs[-1] if structure.highs else None
        lo = structure.lows[-1] if structure.lows else None
        up_price = bar.close if self.break_mode == "CLOSE" else bar.high
        dn_price = bar.close if self.break_mode == "CLOSE" else bar.low

        if hi is not None and hi.seq not in self._broken and hi.confirmation_bar < i and up_price > hi.pivot_price:
            out.append(self._emit("BULLISH", hi, i, bar, trend, bias))
        if lo is not None and lo.seq not in self._broken and lo.confirmation_bar < i and dn_price < lo.pivot_price:
            out.append(self._emit("BEARISH", lo, i, bar, trend, bias))
        if out:
            self.by_bar[i] = out
        return out

    def _emit(self, direction: str, pivot, i: int, bar: Bar, trend: str, bias: Optional[str]) -> StructureEvent:
        self._broken.add(pivot.seq)
        if bias is None or bias == direction:
            etype = "BOS"
        else:
            etype = "CHOCH"
        previous = self.state if self.state != Trend.UNDEFINED else trend
        if etype == "BOS":
            current = direction
        else:
            current = f"{direction}_WARNING"
        ev = StructureEvent(
            event_type=etype,
            direction=direction,
            level=pivot.pivot_price,
            level_pivot_bar=pivot.pivot_bar,
            level_pivot_timestamp=pivot.pivot_timestamp,
            event_bar=i,
            event_timestamp=bar.close_time,
            previous_structure=previous,
            current_structure=current,
        )
        self.state = current
        self._last_direction = direction
        self.events.append(ev)
        return ev

    def last_event(self, bar_index: int, direction: Optional[str] = None) -> Optional[StructureEvent]:
        for ev in reversed(self.events):
            if ev.event_bar <= bar_index and (direction is None or ev.direction == direction):
                return ev
        return None
