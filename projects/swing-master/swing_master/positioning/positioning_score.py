"""Participant positioning engine (Sections 13-16).

Hard rules
* Positioning is NEVER derived from OHLCV.  Without a genuine participant
  source every engine reports ``UNAVAILABLE`` and returns no numbers.
* A record is used only when ``available_to_strategy_timestamp <= as_of``.
* Percentile / z-score / min / max use only observations available at
  ``as_of`` (expanding window, no future data).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from ..config.scoring_config import POSITION_CLASS_SCORE_LONG
from ..indicators.utilities import percentile_rank, zscore
from ..schemas import Availability, PositioningRecord

CLASSES = ("STRONG SHORT", "SHORT", "NEUTRAL", "LONG", "STRONG LONG")


def classify_percentile(pct: Optional[float], bands=(10.0, 30.0, 70.0, 90.0)) -> Optional[str]:
    if pct is None:
        return None
    b1, b2, b3, b4 = bands
    if pct < b1:
        return "STRONG SHORT"
    if pct < b2:
        return "SHORT"
    if pct <= b3:
        return "NEUTRAL"
    if pct <= b4:
        return "LONG"
    return "STRONG LONG"


@dataclass
class PositioningSnapshot:
    category: str
    status: str  # DIRECT | PROXY | UNAVAILABLE
    source: str
    as_of: Optional[datetime] = None
    period: Optional[str] = None
    long: Optional[float] = None
    short: Optional[float] = None
    net: Optional[float] = None
    net_pct: Optional[float] = None
    hist_min: Optional[float] = None
    hist_max: Optional[float] = None
    percentile: Optional[float] = None
    zscore: Optional[float] = None
    change_1: Optional[float] = None
    change_5: Optional[float] = None
    change_20: Optional[float] = None
    classification: Optional[str] = None
    observations: int = 0
    note: str = ""

    def to_dict(self) -> Dict:
        r = lambda x, n=2: None if x is None else round(x, n)  # noqa: E731
        return {
            "category": self.category, "status": self.status, "source": self.source,
            "as_of": self.as_of.isoformat() if self.as_of else None, "period": self.period,
            "long": r(self.long, 0), "short": r(self.short, 0), "net": r(self.net, 0),
            "net_pct": r(self.net_pct, 4), "min": r(self.hist_min, 4), "max": r(self.hist_max, 4),
            "percentile": r(self.percentile, 1), "zscore": r(self.zscore, 2),
            "change_1": r(self.change_1, 4), "change_5": r(self.change_5, 4), "change_20": r(self.change_20, 4),
            "classification": self.classification, "observations": self.observations, "note": self.note,
        }


class ParticipantEngine:
    category = "GENERIC"
    source_hint = ""

    def __init__(self, records: Optional[Sequence[PositioningRecord]] = None, min_history: int = 20,
                 bands=(10.0, 30.0, 70.0, 90.0)):
        recs = [r for r in (records or []) if r.category == self.category]
        self.records: List[PositioningRecord] = sorted(recs, key=lambda r: r.available_to_strategy_timestamp)
        self.min_history = min_history
        self.bands = bands

    def available(self, as_of: datetime) -> List[PositioningRecord]:
        return [r for r in self.records if r.available_to_strategy_timestamp <= as_of]

    def snapshot(self, as_of: datetime) -> PositioningSnapshot:
        usable = self.available(as_of)
        if not usable:
            return PositioningSnapshot(
                category=self.category, status=Availability.UNAVAILABLE, source="none",
                note=f"No {self.category.lower()} positioning source loaded. {self.source_hint}".strip())
        nets = [(r.long - r.short) / (r.long + r.short) if (r.long + r.short) else 0.0 for r in usable]
        cur = usable[-1]
        cur_net_pct = nets[-1]
        pct = percentile_rank(nets, cur_net_pct) if len(nets) >= self.min_history else None
        zs = zscore(nets, cur_net_pct) if len(nets) >= self.min_history else None

        def change(n: int) -> Optional[float]:
            return nets[-1] - nets[-1 - n] if len(nets) > n else None

        note = "" if pct is not None else f"Needs {self.min_history} observations for percentile/z-score"
        return PositioningSnapshot(
            category=self.category, status=cur.source_type, source=cur.source, as_of=cur.available_to_strategy_timestamp,
            period=cur.position_period.isoformat(), long=cur.long, short=cur.short, net=cur.long - cur.short,
            net_pct=cur_net_pct, hist_min=min(nets), hist_max=max(nets), percentile=pct, zscore=zs,
            change_1=change(1), change_5=change(5), change_20=change(20),
            classification=classify_percentile(pct, self.bands), observations=len(nets), note=note)


def divergence(commercial: PositioningSnapshot, institutional: PositioningSnapshot,
               retail: PositioningSnapshot) -> Dict:
    """Smart money (commercial/institutional) vs retail disagreement (Section 15).  Context only."""
    smart = [s.classification for s in (commercial, institutional) if s.classification]
    if not smart or not retail.classification:
        return {"status": "UNAVAILABLE", "signal": None,
                "detail": "Divergence needs commercial or institutional AND retail classifications."}
    smart_score = sum(POSITION_CLASS_SCORE_LONG[c] for c in smart) / len(smart)
    retail_score = POSITION_CLASS_SCORE_LONG[retail.classification]
    if smart_score >= 0.75 and retail_score <= 0.25:
        sig = "BULLISH POSITIONING DIVERGENCE"
    elif smart_score <= 0.25 and retail_score >= 0.75:
        sig = "BEARISH POSITIONING DIVERGENCE"
    else:
        sig = "NO DIVERGENCE"
    return {"status": "AVAILABLE", "signal": sig, "smart_score": round(smart_score, 2),
            "retail_score": round(retail_score, 2),
            "detail": "Contextual confluence only; not a standalone signal."}


def smart_money_fraction(direction: str, commercial: PositioningSnapshot,
                         institutional: PositioningSnapshot) -> Optional[float]:
    vals = [POSITION_CLASS_SCORE_LONG[s.classification] for s in (commercial, institutional) if s.classification]
    if not vals:
        return None
    v = sum(vals) / len(vals)
    return v if direction == "LONG" else 1.0 - v


def retail_fraction(direction: str, retail: PositioningSnapshot) -> Optional[float]:
    """Retail is read contrarian: crowded retail shorts support longs."""
    if not retail.classification:
        return None
    v = 1.0 - POSITION_CLASS_SCORE_LONG[retail.classification]
    return v if direction == "LONG" else 1.0 - v
