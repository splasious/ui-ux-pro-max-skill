"""Live feed interface and tick -> candle aggregation.

REQUIRES EXTERNAL / LIVE DATA: a concrete ``LiveFeed`` must wrap a broker or
vendor websocket (e.g. Kite Ticker).  None ships enabled.

``CandleBuilder`` is the piece the strategy relies on: it emits a bar only
after the bar's period has fully elapsed, so partially formed candles never
reach the analysis engine.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

from ..schemas import Bar
from .resampler import TF_MINUTES, session_close, session_open


class LiveFeed(ABC):
    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def subscribe(self, symbols: List[str], on_tick: Callable[[str, datetime, float, float], None]) -> None: ...

    @abstractmethod
    def status(self) -> Dict: ...


class CandleBuilder:
    def __init__(self, timeframe: str = "5m"):
        self.minutes = TF_MINUTES[timeframe]
        self._open: Dict[str, Bar] = {}
        self.completed: Dict[str, List[Bar]] = {}

    def _bucket(self, ts: datetime):
        start_day = session_open(ts.date())
        k = int((ts - start_day).total_seconds() // (60 * self.minutes))
        start = start_day + timedelta(minutes=k * self.minutes)
        end = min(start + timedelta(minutes=self.minutes), session_close(ts.date()))
        return start, end

    def on_tick(self, symbol: str, ts: datetime, price: float, qty: float = 0.0) -> Optional[Bar]:
        """Feed a tick; return the bar that this tick proves complete (if any)."""
        if ts < session_open(ts.date()) or ts >= session_close(ts.date()):
            return None
        start, end = self._bucket(ts)
        emitted = None
        cur = self._open.get(symbol)
        if cur is not None and cur.timestamp != start:
            emitted = self._finalise(symbol)
            cur = None
        if cur is None:
            self._open[symbol] = Bar(start, end, price, price, price, price, qty)
        else:
            cur.high = max(cur.high, price)
            cur.low = min(cur.low, price)
            cur.close = price
            cur.volume += qty
        return emitted

    def on_clock(self, now: datetime) -> List[Bar]:
        """Close bars whose period has elapsed even if no further tick arrived."""
        out = []
        for sym, bar in list(self._open.items()):
            if now >= bar.close_time:
                out.append(self._finalise(sym))
        return out

    def _finalise(self, symbol: str) -> Bar:
        bar = self._open.pop(symbol)
        self.completed.setdefault(symbol, []).append(bar)
        return bar
