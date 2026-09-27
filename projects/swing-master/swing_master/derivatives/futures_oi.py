"""Futures open-interest state classification (Section 17).

    PRICE up   + OI up   -> LONG BUILD-UP
    PRICE down + OI up   -> SHORT BUILD-UP
    PRICE up   + OI down -> SHORT COVERING
    PRICE down + OI down -> LONG UNWINDING

This is a POSITIONING PROXY -- it says nothing about *who* holds the
contracts, so it is never labelled commercial / institutional / retail.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from ..config.scoring_config import OI_STATE_SCORE_LONG
from ..schemas import Availability, FuturesOIRecord


def classify_oi(price_change_pct: float, oi_change_pct: float, price_thr: float = 0.1,
                oi_thr: float = 0.5) -> str:
    if abs(price_change_pct) < price_thr or abs(oi_change_pct) < oi_thr:
        return "NEUTRAL"
    if price_change_pct > 0 and oi_change_pct > 0:
        return "LONG BUILD-UP"
    if price_change_pct < 0 and oi_change_pct > 0:
        return "SHORT BUILD-UP"
    if price_change_pct > 0 and oi_change_pct < 0:
        return "SHORT COVERING"
    return "LONG UNWINDING"


class FuturesOISeries:
    """Chronological futures OI with as-of access keyed on ``available_at``."""

    def __init__(self, records: Sequence[FuturesOIRecord], price_thr: float = 0.1, oi_thr: float = 0.5):
        self.records: List[FuturesOIRecord] = sorted(records, key=lambda r: r.available_at)
        self._avail = [r.available_at for r in self.records]
        self.price_thr = price_thr
        self.oi_thr = oi_thr

    def __len__(self) -> int:
        return len(self.records)

    def index_as_of(self, as_of: datetime) -> int:
        return bisect_right(self._avail, as_of) - 1

    def state_as_of(self, as_of: datetime, lookback: int = 1) -> Optional[Dict]:
        k = self.index_as_of(as_of)
        if k < lookback:
            return None
        cur, prev = self.records[k], self.records[k - lookback]
        if prev.close <= 0 or prev.open_interest <= 0:
            return None
        p_chg = 100.0 * (cur.close / prev.close - 1.0)
        oi_chg = 100.0 * (cur.open_interest / prev.open_interest - 1.0)
        state = classify_oi(p_chg, oi_chg, self.price_thr, self.oi_thr)
        return {
            "date": cur.trade_date.isoformat(), "price": cur.close, "oi": cur.open_interest,
            "oi_change": cur.open_interest - prev.open_interest, "price_change_pct": round(p_chg, 3),
            "oi_change_pct": round(oi_chg, 3), "state": state, "lookback": lookback,
            "source": cur.source_type, "label": "POSITIONING PROXY",
        }

    def history(self, as_of: datetime, n: int = 30) -> List[Dict]:
        k = self.index_as_of(as_of)
        out = []
        for j in range(max(1, k - n + 1), k + 1):
            cur, prev = self.records[j], self.records[j - 1]
            if prev.close <= 0 or prev.open_interest <= 0:
                continue
            p_chg = 100.0 * (cur.close / prev.close - 1.0)
            oi_chg = 100.0 * (cur.open_interest / prev.open_interest - 1.0)
            out.append({"date": cur.trade_date.isoformat(), "price": round(cur.close, 2),
                        "oi": round(cur.open_interest), "oi_change": round(cur.open_interest - prev.open_interest),
                        "price_change_pct": round(p_chg, 3), "oi_change_pct": round(oi_chg, 3),
                        "state": classify_oi(p_chg, oi_chg, self.price_thr, self.oi_thr)})
        return out


def oi_fraction(direction: str, state: Optional[Dict]) -> Optional[float]:
    if state is None:
        return None
    v = OI_STATE_SCORE_LONG[state["state"]]
    return v if direction == "LONG" else 1.0 - v


UNAVAILABLE_OI = {"state": None, "source": Availability.UNAVAILABLE, "label": "POSITIONING PROXY"}
