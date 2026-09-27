"""Historical CSV provider for real data (requires files you supply).

Directory layout (``SM_DATA_DIR``)::

    universe.csv            symbol,name,sector,segment,lot_size,is_index,has_futures,has_options,strike_step
                            (has_futures=1 marks an F&O stock; ``fno`` is accepted as an alias)
    ohlcv/<SYMBOL>.csv      date,open,high,low,close,volume          (daily, ascending)
    intraday/<SYMBOL>.csv   timestamp,open,high,low,close,volume     (5m bars, optional)
    futures_oi/<SYMBOL>.csv date,close,open_interest                 (optional)
    vix.csv                 date,open,high,low,close                 (optional)
    participant_oi.csv      NSE participant-wise OI (see positioning_data.py, optional)

Rows are validated; invalid rows raise instead of being silently repaired.
"""
from __future__ import annotations

import csv
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List

from ..schemas import UNCLASSIFIED_SECTOR, Availability, Bar, FuturesOIRecord, Instrument
from .market_data import DataUnavailable, MarketDataProvider
from .positioning_data import load_participant_oi_csv
from .resampler import TF_MINUTES, resample_intraday, session_close, session_open


class DataValidationError(ValueError):
    pass


def _f(row: Dict[str, str], key: str, path: Path, line: int) -> float:
    try:
        v = float(row[key])
    except (KeyError, ValueError) as exc:
        raise DataValidationError(f"{path}:{line} bad '{key}'") from exc
    if not math.isfinite(v):
        raise DataValidationError(f"{path}:{line} non-finite '{key}'")
    return v


def validate_bars(bars: List[Bar], path: Path) -> List[str]:
    """Return a list of data gaps / warnings; raise on hard errors."""
    warnings = []
    prev = None
    for k, b in enumerate(bars):
        if not (b.low <= min(b.open, b.close) and b.high >= max(b.open, b.close) and b.low <= b.high):
            raise DataValidationError(f"{path}: inconsistent OHLC at row {k + 2}")
        if b.volume < 0:
            raise DataValidationError(f"{path}: negative volume at row {k + 2}")
        if prev is not None:
            if b.timestamp <= prev.timestamp:
                raise DataValidationError(f"{path}: timestamps not strictly increasing at row {k + 2}")
            gap = (b.timestamp.date() - prev.timestamp.date()).days
            if gap > 4:
                warnings.append(f"{prev.timestamp.date()} -> {b.timestamp.date()} ({gap} calendar days)")
        prev = b
    return warnings


class CSVMarketData(MarketDataProvider):
    source_label = "CSV (historical files)"

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        if not (self.data_dir / "universe.csv").exists():
            raise FileNotFoundError(f"{self.data_dir / 'universe.csv'} not found")
        self._universe = self._load_universe()
        self._bars: Dict[str, List[Bar]] = {}
        self.gaps: Dict[str, List[str]] = {}

    def _load_universe(self) -> List[Instrument]:
        out = []
        with open(self.data_dir / "universe.csv", newline="") as fh:
            for row in csv.DictReader(fh):
                out.append(Instrument(
                    symbol=row["symbol"], name=row.get("name") or row["symbol"], sector=row.get("sector") or UNCLASSIFIED_SECTOR,
                    segment=row.get("segment") or "EQ", lot_size=int(row.get("lot_size") or 1),
                    is_index=(row.get("is_index") or "0") in ("1", "true", "True"),
                    has_futures=(row.get("has_futures") or row.get("fno") or "0") in ("1", "true", "True"),
                    has_options=(row.get("has_options") or "0") in ("1", "true", "True"),
                    strike_step=float(row.get("strike_step") or 0)))
        return out

    def universe(self) -> List[Instrument]:
        return list(self._universe)

    def daily_bars(self, symbol: str) -> List[Bar]:
        if symbol in self._bars:
            return self._bars[symbol]
        path = self.data_dir / "ohlcv" / f"{symbol}.csv"
        if not path.exists():
            raise DataUnavailable(f"{path} missing")
        bars = []
        with open(path, newline="") as fh:
            for line, row in enumerate(csv.DictReader(fh), start=2):
                d = date.fromisoformat(row["date"][:10])
                bars.append(Bar(session_open(d), session_close(d), _f(row, "open", path, line),
                                _f(row, "high", path, line), _f(row, "low", path, line),
                                _f(row, "close", path, line), _f(row, "volume", path, line)))
        self.gaps[symbol] = validate_bars(bars, path)
        self._bars[symbol] = bars
        return bars

    def intraday_bars(self, symbol: str, timeframe: str, sessions: int) -> List[Bar]:
        path = self.data_dir / "intraday" / f"{symbol}.csv"
        if timeframe not in TF_MINUTES or not path.exists():
            raise DataUnavailable(f"No intraday file for {symbol}")
        bars = []
        with open(path, newline="") as fh:
            for line, row in enumerate(csv.DictReader(fh), start=2):
                ts = datetime.fromisoformat(row["timestamp"])
                close_time = min(ts + timedelta(minutes=5), session_close(ts.date()))
                bars.append(Bar(ts, close_time, _f(row, "open", path, line), _f(row, "high", path, line),
                                _f(row, "low", path, line), _f(row, "close", path, line),
                                _f(row, "volume", path, line)))
        days = sorted({b.timestamp.date() for b in bars})[-sessions:]
        keep = set(days)
        bars = [b for b in bars if b.timestamp.date() in keep]
        return bars if timeframe == "5m" else resample_intraday(bars, timeframe)

    def futures_oi(self, symbol: str) -> List[FuturesOIRecord]:
        path = self.data_dir / "futures_oi" / f"{symbol}.csv"
        if not path.exists():
            return []
        out, prev = [], None
        with open(path, newline="") as fh:
            for line, row in enumerate(csv.DictReader(fh), start=2):
                d = date.fromisoformat(row["date"][:10])
                oi = _f(row, "open_interest", path, line)
                out.append(FuturesOIRecord(d, _f(row, "close", path, line), oi, oi - prev if prev is not None else 0.0,
                                           datetime(d.year, d.month, d.day, 18, 30), Availability.PROXY))
                prev = oi
        return out

    def volatility_index(self) -> List[Bar]:
        path = self.data_dir / "vix.csv"
        if not path.exists():
            return []
        out = []
        with open(path, newline="") as fh:
            for line, row in enumerate(csv.DictReader(fh), start=2):
                d = date.fromisoformat(row["date"][:10])
                out.append(Bar(session_open(d), session_close(d), _f(row, "open", path, line),
                               _f(row, "high", path, line), _f(row, "low", path, line), _f(row, "close", path, line), 0))
        return out

    def positioning(self):
        path = self.data_dir / "participant_oi.csv"
        return load_participant_oi_csv(path) if path.exists() else []

    def health(self) -> Dict[str, Dict]:
        gaps = sum(len(v) for v in self.gaps.values())
        return {
            "market_feed": {"status": "OK", "detail": f"CSV files in {self.data_dir}"},
            "websocket": {"status": "NOT CONFIGURED", "detail": "No live feed configured"},
            "historical_sync": {"status": "OK", "detail": f"{len(self._bars)} symbols loaded"},
            "futures_oi": {"status": "OK" if (self.data_dir / "futures_oi").exists() else "UNAVAILABLE",
                           "detail": "futures_oi/*.csv"},
            "options_feed": {"status": "UNAVAILABLE", "detail": "No option-chain loader configured"},
            "positioning_feed": {"status": "OK" if (self.data_dir / "participant_oi.csv").exists() else "UNAVAILABLE",
                                 "detail": "participant_oi.csv"},
            "last_candle": {"status": "OK", "detail": self.as_of().isoformat()},
            "latency": {"status": "N/A", "detail": "Historical files"},
            "data_gaps": {"status": "WARN" if gaps else "OK", "detail": f"{gaps} gaps > 4 calendar days"},
        }
