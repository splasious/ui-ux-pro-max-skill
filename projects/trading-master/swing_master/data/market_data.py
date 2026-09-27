"""Market-data provider interface.

Every provider declares *where* its data comes from.  Consumers never
substitute one feed for another silently: a missing feed is reported as
UNAVAILABLE through :meth:`MarketDataProvider.health`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Dict, List, Optional

from ..schemas import Bar, FuturesOIRecord, Instrument, OptionChainSnapshot, PositioningRecord


class DataUnavailable(Exception):
    """Raised when a caller asks for data the provider genuinely does not have."""


class MarketDataProvider(ABC):
    source_label: str = "UNKNOWN"
    is_demo: bool = False

    @abstractmethod
    def universe(self) -> List[Instrument]: ...

    def instrument(self, symbol: str) -> Instrument:
        for inst in self.universe():
            if inst.symbol == symbol:
                return inst
        raise KeyError(symbol)

    @abstractmethod
    def daily_bars(self, symbol: str) -> List[Bar]: ...

    def intraday_bars(self, symbol: str, timeframe: str, sessions: int) -> List[Bar]:
        raise DataUnavailable(f"{timeframe} data not available from {self.source_label}")

    def futures_oi(self, symbol: str) -> List[FuturesOIRecord]:
        return []

    def option_chain(self, symbol: str, trade_date: date) -> Optional[OptionChainSnapshot]:
        return None

    def positioning(self) -> List[PositioningRecord]:
        return []

    def volatility_index(self) -> List[Bar]:
        return []

    def as_of(self) -> datetime:
        latest = None
        for inst in self.universe():
            bars = self.daily_bars(inst.symbol)
            if bars and (latest is None or bars[-1].close_time > latest):
                latest = bars[-1].close_time
        return latest or datetime.now()

    @abstractmethod
    def health(self) -> Dict[str, Dict]: ...
