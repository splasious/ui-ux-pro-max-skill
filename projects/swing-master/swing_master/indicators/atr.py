"""Average True Range (Wilder), computed strictly causally (Section 5)."""
from __future__ import annotations

from typing import List, Optional, Sequence

from ..schemas import Bar


def true_range(high: float, low: float, prev_close: Optional[float]) -> float:
    if prev_close is None:
        return high - low
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


class ATR:
    """Incremental Wilder ATR.  ``update`` returns the ATR known at this bar's close.

    The first ``period - 1`` bars return ``None``; the seed value is the simple
    mean of the first ``period`` true ranges, after which Wilder smoothing
    ``atr = (atr_prev * (n - 1) + tr) / n`` is applied.
    """

    def __init__(self, period: int = 14):
        if period < 1:
            raise ValueError("ATR period must be >= 1")
        self.period = period
        self._prev_close: Optional[float] = None
        self._seed: List[float] = []
        self.value: Optional[float] = None

    def update(self, high: float, low: float, close: float) -> Optional[float]:
        tr = true_range(high, low, self._prev_close)
        self._prev_close = close
        if self.value is None:
            self._seed.append(tr)
            if len(self._seed) == self.period:
                self.value = sum(self._seed) / self.period
                self._seed = []
            return self.value
        self.value = (self.value * (self.period - 1) + tr) / self.period
        return self.value


def atr_series(bars: Sequence[Bar], period: int = 14) -> List[Optional[float]]:
    calc = ATR(period)
    return [calc.update(b.high, b.low, b.close) for b in bars]
