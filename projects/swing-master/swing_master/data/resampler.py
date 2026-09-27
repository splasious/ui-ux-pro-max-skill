"""NSE-session-aligned resampling and completed-higher-timeframe views (Section 4).

Session: 09:15-15:30 IST (naive datetimes are IST throughout).

* Intraday buckets are anchored at 09:15: 1H = 09:15, 10:15 ... 15:15 (last
  bucket is 15 minutes), 4H = 09:15-13:15 and 13:15-15:30.
* Weekly bars close at Friday 15:30 of their ISO week and monthly bars at
  the last weekday of the month, 15:30 -- the calendar end of the period.
  A period whose last trading day falls earlier (holiday) is therefore only
  treated as complete once that calendar boundary has passed.  This is
  conservative by design: an incomplete higher-timeframe candle can never
  leak into a lower-timeframe decision.
"""
from __future__ import annotations

from bisect import bisect_right
from calendar import monthrange
from datetime import date, datetime, time, timedelta
from typing import Callable, Dict, List, Sequence

from ..schemas import Bar

SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)
TF_MINUTES = {"5m": 5, "15m": 15, "1H": 60, "4H": 240}


def session_open(d: date) -> datetime:
    return datetime.combine(d, SESSION_OPEN)


def session_close(d: date) -> datetime:
    return datetime.combine(d, SESSION_CLOSE)


def week_close(d: date) -> datetime:
    friday = d + timedelta(days=4 - d.weekday())
    return session_close(friday)


def month_close(d: date) -> datetime:
    last = date(d.year, d.month, monthrange(d.year, d.month)[1])
    while last.weekday() >= 5:
        last -= timedelta(days=1)
    return session_close(last)


def _aggregate(group: Sequence[Bar], ts: datetime, close_time: datetime) -> Bar:
    return Bar(
        timestamp=ts,
        close_time=close_time,
        open=group[0].open,
        high=max(b.high for b in group),
        low=min(b.low for b in group),
        close=group[-1].close,
        volume=sum(b.volume for b in group),
    )


def resample_intraday(bars: Sequence[Bar], tf: str) -> List[Bar]:
    """Aggregate 5m (or finer) bars into a session-anchored intraday timeframe."""
    minutes = TF_MINUTES[tf]
    out: List[Bar] = []
    group: List[Bar] = []
    key = None
    for b in bars:
        mins = (b.timestamp - session_open(b.timestamp.date())).total_seconds() / 60.0
        k = (b.timestamp.date(), int(mins // minutes))
        if key is not None and k != key:
            out.append(_close_bucket(group, key, minutes))
            group = []
        key = k
        group.append(b)
    if group:
        out.append(_close_bucket(group, key, minutes))
    return out


def _close_bucket(group: List[Bar], key, minutes: int) -> Bar:
    d, idx = key
    start = session_open(d) + timedelta(minutes=idx * minutes)
    end = min(start + timedelta(minutes=minutes), session_close(d))
    return _aggregate(group, start, end)


def resample_daily(bars: Sequence[Bar]) -> List[Bar]:
    return _resample_by(bars, lambda t: t.date(), lambda d: (session_open(d), session_close(d)))


def resample_weekly(daily: Sequence[Bar]) -> List[Bar]:
    def key(t: datetime):
        iso = t.date().isocalendar()
        return (iso[0], iso[1])
    return _resample_group(daily, key, lambda first: week_close(first.timestamp.date()))


def resample_monthly(daily: Sequence[Bar]) -> List[Bar]:
    return _resample_group(daily, lambda t: (t.year, t.month), lambda first: month_close(first.timestamp.date()))


def _resample_by(bars, keyf: Callable, bounds: Callable) -> List[Bar]:
    out, group, key = [], [], None
    for b in bars:
        k = keyf(b.timestamp)
        if key is not None and k != key:
            s, e = bounds(key)
            out.append(_aggregate(group, s, e))
            group = []
        key = k
        group.append(b)
    if group:
        s, e = bounds(key)
        out.append(_aggregate(group, s, e))
    return out


def _resample_group(bars, keyf: Callable, closef: Callable) -> List[Bar]:
    out, group, key = [], [], None
    for b in bars:
        k = keyf(b.timestamp)
        if key is not None and k != key:
            out.append(_aggregate(group, group[0].timestamp, closef(group[0])))
            group = []
        key = k
        group.append(b)
    if group:
        out.append(_aggregate(group, group[0].timestamp, closef(group[0])))
    return out


def resample(bars: Sequence[Bar], source_tf: str, target_tf: str) -> List[Bar]:
    if target_tf == source_tf:
        return list(bars)
    if target_tf in TF_MINUTES:
        return resample_intraday(bars, target_tf)
    daily = bars if source_tf == "1D" else resample_daily(bars)
    if target_tf == "1D":
        return list(daily)
    if target_tf == "1W":
        return resample_weekly(daily)
    if target_tf == "1M":
        return resample_monthly(daily)
    raise ValueError(f"Unsupported resample {source_tf} -> {target_tf}")


class HTFView:
    """Higher-timeframe bars filtered to those COMPLETE at a given moment."""

    def __init__(self, bars: Sequence[Bar]):
        self.bars = list(bars)
        self._closes = [b.close_time for b in self.bars]

    def completed_count(self, as_of: datetime) -> int:
        return bisect_right(self._closes, as_of)

    def completed(self, as_of: datetime) -> List[Bar]:
        return self.bars[: self.completed_count(as_of)]


def is_complete(bar: Bar, as_of: datetime) -> bool:
    return bar.close_time <= as_of


TIMEFRAME_SECONDS: Dict[str, int] = {"5m": 300, "15m": 900, "1H": 3600, "4H": 14400, "1D": 86400,
                                     "1W": 604800, "1M": 2592000}
