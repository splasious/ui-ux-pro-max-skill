"""Incremental per-symbol analysis: ATR -> ZigZag -> structure -> BOS/CHoCH -> zones.

``SymbolAnalyzer.update(bar)`` is called once per CLOSED bar in time order.
After the call, every attribute describes the market exactly as it was known
at that bar's close -- the analyzer has no API for looking ahead.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from ..indicators.atr import ATR
from ..schemas import Bar, Trend, Zone
from ..structure.bos_choch import StructureEventDetector
from ..structure.market_structure import MarketStructure
from ..structure.pivots import PivotStore
from ..structure.zigzag import ZigZagEngine
from ..volume_profile.profile import build_profile, profile_window
from ..zones.demand_supply import ZoneEngine


class SymbolAnalyzer:
    def __init__(self, symbol: str, timeframe: str, cfg):
        self.symbol = symbol
        self.timeframe = timeframe
        self.cfg = cfg
        self.bars: List[Bar] = []
        self.atr_values: List[Optional[float]] = []
        self._atr = ATR(cfg.ATR_PERIOD)
        self.zigzag = ZigZagEngine(cfg.ZIGZAG_METHOD, cfg.ZIGZAG_PERCENT, cfg.ZIGZAG_ATR_MULTIPLIER,
                                   cfg.ZIGZAG_HYBRID_MODE)
        self.pivots = PivotStore()
        self.structure = MarketStructure(cfg.STRUCTURE_EQUAL_TOLERANCE_ATR)
        self.events = StructureEventDetector(cfg.BOS_BREAK_MODE)
        self.zones = ZoneEngine(symbol, timeframe, cfg)
        self.trend_by_bar: List[str] = []

    @property
    def i(self) -> int:
        return len(self.bars) - 1

    @property
    def atr(self) -> Optional[float]:
        return self.atr_values[-1] if self.atr_values else None

    @property
    def now(self) -> Optional[datetime]:
        return self.bars[-1].close_time if self.bars else None

    def update(self, bar: Bar) -> int:
        if self.bars and bar.timestamp <= self.bars[-1].timestamp:
            raise ValueError("Bars must arrive in strictly increasing time order")
        self.bars.append(bar)
        i = len(self.bars) - 1
        atr = self._atr.update(bar.high, bar.low, bar.close)
        self.atr_values.append(atr)
        pivot = self.zigzag.update(i, bar, atr)
        if pivot is not None:
            self.structure.add_pivot(pivot, atr)
            self.pivots.add(pivot)
        self.events.update(i, bar, self.structure)
        self.zones.update(i, self.bars, atr, self.structure.trend)
        self.trend_by_bar.append(self.structure.trend)
        return i

    def active_zones(self, zone_type: Optional[str] = None) -> List[Zone]:
        i = self.i
        return [z for z in self.zones.active()
                if z.creation_bar < i and not z.is_invalidated_as_of(i)
                and (zone_type is None or z.zone_type == zone_type)]

    def profile(self, kind: Optional[str] = None, end: Optional[int] = None):
        end = self.i if end is None else end
        kind = kind or self.cfg.VP_SETUP_PROFILE
        pivots = self.pivots.confirmed_as_of(end)
        start, stop = profile_window(kind, self.bars, end, pivots, self.cfg.VP_LOOKBACK_BARS)
        return build_profile(self.bars, start, stop, self.cfg.VOLUME_PROFILE_BINS, self.cfg.VALUE_AREA_PERCENT,
                             kind, self.cfg.HVN_THRESHOLD, self.cfg.LVN_THRESHOLD)


class HTFTracker:
    """Feeds higher-timeframe bars into their own analyzer only once COMPLETE."""

    def __init__(self, symbol: str, timeframe: str, htf_bars: List[Bar], cfg):
        self.analyzer = SymbolAnalyzer(symbol, timeframe, cfg)
        self._bars = htf_bars
        self._next = 0

    def advance_to(self, as_of: datetime) -> None:
        while self._next < len(self._bars) and self._bars[self._next].close_time <= as_of:
            self.analyzer.update(self._bars[self._next])
            self._next += 1

    @property
    def trend(self) -> str:
        return self.analyzer.structure.trend if self.analyzer.bars else Trend.UNDEFINED

    @property
    def completed_bars(self) -> int:
        return self._next
