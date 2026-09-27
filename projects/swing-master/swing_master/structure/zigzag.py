"""Confirmed, non-repainting ZigZag (Section 6).

A swing extreme becomes a *pivot* only when price has subsequently reversed
from it by the threshold.  The pivot keeps its original ``pivot_bar`` /
``pivot_timestamp`` (where the extreme printed) but is stamped with the
``confirmation_bar`` / ``confirmation_timestamp`` at which the reversal was
known.  The strategy may only read a pivot at/after its confirmation.

Engineering choices that keep it causal and conservative:

* The engine processes one closed bar at a time and never revisits history.
* If a bar makes a new extreme we do NOT also confirm a reversal on that bar,
  because OHLC data cannot tell us whether the opposite wick printed after
  the extreme.
* Thresholds use the ATR value known at the confirming bar.
* The in-progress (unconfirmed) extreme is exposed separately via
  :meth:`candidate` for display only and is never used by the strategy.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from ..schemas import Bar, Pivot


class ZigZagEngine:
    def __init__(self, method: str = "ATR", percent: float = 5.0, atr_multiplier: float = 2.0,
                 hybrid_mode: str = "MAX"):
        method = method.upper()
        if method not in ("PERCENT", "ATR", "HYBRID"):
            raise ValueError("method must be PERCENT, ATR or HYBRID")
        self.method = method
        self.percent = percent
        self.atr_multiplier = atr_multiplier
        self.hybrid_mode = hybrid_mode.upper()
        self.pivots: List[Pivot] = []

        self._ts: List = []
        self._dir = 0  # 0 = initialising, +1 = tracking a HIGH, -1 = tracking a LOW
        # initialisation trackers
        self._init_h: List[float] = []
        self._init_l: List[float] = []
        # active candidate extreme
        self._cand_price: Optional[float] = None
        self._cand_bar: Optional[int] = None
        # most extreme opposite price printed after the candidate (exclusive of its bar)
        self._opp_price: Optional[float] = None
        self._opp_bar: Optional[int] = None

    # ------------------------------------------------------------------ #
    def threshold(self, ref_price: float, atr: Optional[float]) -> Optional[float]:
        pct_thr = abs(ref_price) * self.percent / 100.0
        atr_thr = atr * self.atr_multiplier if atr else None
        if self.method == "PERCENT":
            return pct_thr
        if self.method == "ATR":
            return atr_thr
        if atr_thr is None:
            return pct_thr
        return max(pct_thr, atr_thr) if self.hybrid_mode == "MAX" else min(pct_thr, atr_thr)

    def candidate(self) -> Optional[Tuple[str, float, int]]:
        """Unconfirmed in-progress extreme (display only)."""
        if self._dir == 0 or self._cand_price is None:
            return None
        return ("HIGH" if self._dir == 1 else "LOW", self._cand_price, self._cand_bar)

    # ------------------------------------------------------------------ #
    def update(self, i: int, bar: Bar, atr: Optional[float]) -> Optional[Pivot]:
        """Process closed bar ``i``; return a pivot confirmed by this bar, if any."""
        self._ts.append(bar.timestamp)
        if self._dir == 0:
            return self._update_init(i, bar, atr)

        if self._dir == 1:  # tracking a swing HIGH
            if bar.high > self._cand_price:
                self._cand_price, self._cand_bar = bar.high, i
                self._opp_price = self._opp_bar = None
                return None
            if self._opp_price is None or bar.low < self._opp_price:
                self._opp_price, self._opp_bar = bar.low, i
            thr = self.threshold(self._cand_price, atr)
            move = self._cand_price - self._opp_price
            if thr is not None and move >= thr:
                pivot = self._make_pivot("HIGH", self._cand_price, self._cand_bar, i, bar, move, atr)
                self._dir = -1
                self._cand_price, self._cand_bar = self._opp_price, self._opp_bar
                self._opp_price = self._opp_bar = None
                return pivot
            return None

        # tracking a swing LOW
        if bar.low < self._cand_price:
            self._cand_price, self._cand_bar = bar.low, i
            self._opp_price = self._opp_bar = None
            return None
        if self._opp_price is None or bar.high > self._opp_price:
            self._opp_price, self._opp_bar = bar.high, i
        thr = self.threshold(self._cand_price, atr)
        move = self._opp_price - self._cand_price
        if thr is not None and move >= thr:
            pivot = self._make_pivot("LOW", self._cand_price, self._cand_bar, i, bar, move, atr)
            self._dir = 1
            self._cand_price, self._cand_bar = self._opp_price, self._opp_bar
            self._opp_price = self._opp_bar = None
            return pivot
        return None

    # ------------------------------------------------------------------ #
    def _update_init(self, i: int, bar: Bar, atr: Optional[float]) -> Optional[Pivot]:
        self._init_h.append(bar.high)
        self._init_l.append(bar.low)
        if i == 0:
            return None
        prev_h, prev_l = self._init_h[:-1], self._init_l[:-1]
        lo = min(prev_l)
        lo_bar = prev_l.index(lo)
        hi = max(prev_h)
        hi_bar = prev_h.index(hi)
        thr_lo = self.threshold(lo, atr)
        thr_hi = self.threshold(hi, atr)
        up = thr_lo is not None and bar.high - lo >= thr_lo
        down = thr_hi is not None and hi - bar.low >= thr_hi
        if up and down:
            # both reversals visible: the older extreme is the first pivot
            up, down = (lo_bar <= hi_bar), (hi_bar < lo_bar)
        if up:
            segment = self._init_h[lo_bar + 1: i + 1]
            peak = max(segment)
            peak_bar = lo_bar + 1 + segment.index(peak)
            pivot = self._make_pivot("LOW", lo, lo_bar, i, bar, peak - lo, atr)
            self._dir = 1
            self._cand_price, self._cand_bar = peak, peak_bar
            self._set_opp_after(peak_bar, i, low_side=True)
            return pivot
        if down:
            segment = self._init_l[hi_bar + 1: i + 1]
            trough = min(segment)
            trough_bar = hi_bar + 1 + segment.index(trough)
            pivot = self._make_pivot("HIGH", hi, hi_bar, i, bar, hi - trough, atr)
            self._dir = -1
            self._cand_price, self._cand_bar = trough, trough_bar
            self._set_opp_after(trough_bar, i, low_side=False)
            return pivot
        return None

    def _set_opp_after(self, cand_bar: int, i: int, low_side: bool) -> None:
        if cand_bar >= i:
            self._opp_price = self._opp_bar = None
            return
        if low_side:
            seg = self._init_l[cand_bar + 1: i + 1]
            val = min(seg)
        else:
            seg = self._init_h[cand_bar + 1: i + 1]
            val = max(seg)
        self._opp_price, self._opp_bar = val, cand_bar + 1 + seg.index(val)

    def _make_pivot(self, ptype: str, price: float, pbar: int, i: int, bar: Bar, move: float,
                    atr: Optional[float]) -> Pivot:
        pivot = Pivot(
            pivot_type=ptype,
            pivot_price=price,
            pivot_bar=pbar,
            pivot_timestamp=self._ts[pbar],
            confirmation_bar=i,
            confirmation_timestamp=bar.close_time,
            reversal_amount=move,
            reversal_pct=100.0 * move / price if price else 0.0,
            reversal_atr=(move / atr) if atr else None,
            seq=len(self.pivots),
        )
        self.pivots.append(pivot)
        return pivot
