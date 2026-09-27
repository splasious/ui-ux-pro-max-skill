"""Chronological pivot queries.  All helpers answer "as of bar i" questions."""
from __future__ import annotations

from bisect import bisect_right
from datetime import datetime
from typing import Dict, List, Optional

from ..schemas import Pivot


class PivotStore:
    """Pivots in confirmation order with O(log n) as-of lookups."""

    def __init__(self, pivots: Optional[List[Pivot]] = None):
        self.pivots: List[Pivot] = []
        self._conf_bars: List[int] = []
        self.by_conf_bar: Dict[int, List[Pivot]] = {}
        for p in pivots or []:
            self.add(p)

    def add(self, pivot: Pivot) -> None:
        if self._conf_bars and pivot.confirmation_bar < self._conf_bars[-1]:
            raise ValueError("Pivots must be added in confirmation order")
        self.pivots.append(pivot)
        self._conf_bars.append(pivot.confirmation_bar)
        self.by_conf_bar.setdefault(pivot.confirmation_bar, []).append(pivot)

    def confirmed_as_of(self, bar_index: int) -> List[Pivot]:
        return self.pivots[: bisect_right(self._conf_bars, bar_index)]

    def usable_at(self, current_time: datetime) -> List[Pivot]:
        return [p for p in self.pivots if p.available_at(current_time)]

    def last(self, bar_index: int, pivot_type: Optional[str] = None) -> Optional[Pivot]:
        n = bisect_right(self._conf_bars, bar_index)
        for p in reversed(self.pivots[:n]):
            if pivot_type is None or p.pivot_type == pivot_type:
                return p
        return None

    def last_n(self, bar_index: int, n: int, pivot_type: Optional[str] = None) -> List[Pivot]:
        out: List[Pivot] = []
        k = bisect_right(self._conf_bars, bar_index)
        for p in reversed(self.pivots[:k]):
            if pivot_type is None or p.pivot_type == pivot_type:
                out.append(p)
                if len(out) == n:
                    break
        return list(reversed(out))


def pivot_details(pivot: Pivot, previous: Optional[Pivot], current_time: datetime) -> Dict:
    """Payload shown when a pivot is clicked on the chart (Section 30)."""
    d = pivot.to_dict()
    d["previous_pivot"] = previous.to_dict() if previous else None
    d["status"] = "CONFIRMED" if pivot.available_at(current_time) else "PENDING"
    d["bars_to_confirm"] = pivot.confirmation_bar - pivot.pivot_bar
    return d
