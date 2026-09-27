"""HH / HL / LH / LL classification from CONFIRMED pivots only (Section 7).

The trend is derived from the most recent confirmed high label and the most
recent confirmed low label:

    HH + HL -> BULLISH
    LH + LL -> BEARISH
    EQH/EQL involved -> CONSOLIDATION
    anything else -> TRANSITION

A single violating swing (e.g. one LL inside an uptrend) produces
TRANSITION, never an immediate reversal: BEARISH requires both a confirmed
LH and a confirmed LL.
"""
from __future__ import annotations

from bisect import bisect_right
from typing import List, Optional, Tuple

from ..schemas import Pivot, Trend


class MarketStructure:
    def __init__(self, equal_tolerance_atr: float = 0.1):
        self.equal_tolerance_atr = equal_tolerance_atr
        self.highs: List[Pivot] = []
        self.lows: List[Pivot] = []
        self.trend: str = Trend.UNDEFINED
        # (confirmation_bar, trend) change log for as-of queries
        self._history_bars: List[int] = []
        self._history_trends: List[str] = []

    def add_pivot(self, pivot: Pivot, atr: Optional[float]) -> str:
        tol = (atr or 0.0) * self.equal_tolerance_atr
        if pivot.pivot_type == "HIGH":
            prev = self.highs[-1] if self.highs else None
            if prev is not None:
                pivot.previous_price = prev.pivot_price
                if pivot.pivot_price > prev.pivot_price + tol:
                    pivot.label = "HH"
                elif pivot.pivot_price < prev.pivot_price - tol:
                    pivot.label = "LH"
                else:
                    pivot.label = "EQH"
            self.highs.append(pivot)
        else:
            prev = self.lows[-1] if self.lows else None
            if prev is not None:
                pivot.previous_price = prev.pivot_price
                if pivot.pivot_price > prev.pivot_price + tol:
                    pivot.label = "HL"
                elif pivot.pivot_price < prev.pivot_price - tol:
                    pivot.label = "LL"
                else:
                    pivot.label = "EQL"
            self.lows.append(pivot)

        new_trend = classify(self.last_high_label, self.last_low_label)
        if new_trend != self.trend or not self._history_bars:
            self.trend = new_trend
            self._history_bars.append(pivot.confirmation_bar)
            self._history_trends.append(new_trend)
        return self.trend

    @property
    def last_high_label(self) -> Optional[str]:
        return self.highs[-1].label if self.highs else None

    @property
    def last_low_label(self) -> Optional[str]:
        return self.lows[-1].label if self.lows else None

    def trend_as_of(self, bar_index: int) -> str:
        k = bisect_right(self._history_bars, bar_index)
        return self._history_trends[k - 1] if k else Trend.UNDEFINED

    def history(self) -> List[Tuple[int, str]]:
        return list(zip(self._history_bars, self._history_trends))


def classify(high_label: Optional[str], low_label: Optional[str]) -> str:
    if high_label is None or low_label is None:
        return Trend.UNDEFINED
    if high_label == "HH" and low_label == "HL":
        return Trend.BULLISH
    if high_label == "LH" and low_label == "LL":
        return Trend.BEARISH
    if high_label in ("EQH",) or low_label in ("EQL",):
        return Trend.CONSOLIDATION
    return Trend.TRANSITION
