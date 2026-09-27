"""Core data schemas shared by every module.

Every record that participates in a trading decision carries the timestamp at
which it became *available* to the strategy.  The engine compares those
timestamps against the evaluation time so no module can read the future.

Conventions
-----------
* ``Bar.timestamp`` is the bar OPEN time; ``Bar.close_time`` is the moment
  the bar is complete.  A bar's OHLCV is usable only at/after ``close_time``.
* A pivot is usable only when ``current_time >= pivot.confirmation_timestamp``.
* Derivatives / positioning records expose ``available_at``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------------- #
# String enums (plain constants keep JSON serialisation trivial)
# --------------------------------------------------------------------------- #
class TF:
    M5 = "5m"
    M15 = "15m"
    H1 = "1H"
    H4 = "4H"
    D1 = "1D"
    W1 = "1W"
    MN = "1M"
    ALL = ("1M", "1W", "1D", "4H", "1H", "15m", "5m")
    INTRADAY = ("4H", "1H", "15m", "5m")


class Direction:
    LONG = "LONG"
    SHORT = "SHORT"


class Trend:
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    TRANSITION = "TRANSITION"
    CONSOLIDATION = "CONSOLIDATION"
    UNDEFINED = "UNDEFINED"


# Sector for symbols the data source does not classify; risk checks treat each as its own group.
UNCLASSIFIED_SECTOR = "Unclassified"


class Availability:
    DIRECT = "DIRECT"
    PROXY = "PROXY"
    UNAVAILABLE = "UNAVAILABLE"
    DEMO = "DEMO"


class ZoneStatus:
    FRESH = "FRESH"
    TESTED_ONCE = "TESTED ONCE"
    TESTED_MULTIPLE = "TESTED MULTIPLE TIMES"
    INVALIDATED = "INVALIDATED"


class ScanStatus:
    READY = "READY"
    WATCH = "WATCH"
    WAIT = "WAIT"
    REJECTED = "REJECTED"
    ACTIVE = "ACTIVE"


class ExitReason:
    INITIAL_SL = "INITIAL_SL"
    BREAKEVEN_SL = "BREAKEVEN_SL"
    TRAILING_SL = "TRAILING_SL"
    T3 = "T3"
    ZONE_INVALIDATION = "ZONE_INVALIDATION"
    STRUCTURAL_FAILURE = "STRUCTURAL_FAILURE"
    OPPOSITE_STRUCTURE = "OPPOSITE_STRUCTURE"
    MAX_HOLDING = "MAX_HOLDING"
    PORTFOLIO_RISK = "PORTFOLIO_RISK"
    END_OF_DATA = "END_OF_DATA"


# --------------------------------------------------------------------------- #
# Market data
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class Bar:
    timestamp: datetime  # bar open
    close_time: datetime  # bar complete -> data usable from here
    open: float
    high: float
    low: float
    close: float
    volume: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "t": self.timestamp.isoformat(),
            "o": round(self.open, 4),
            "h": round(self.high, 4),
            "l": round(self.low, 4),
            "c": round(self.close, 4),
            "v": round(self.volume, 2),
        }


@dataclass(slots=True)
class Instrument:
    symbol: str
    name: str
    sector: str
    segment: str = "EQ"  # EQ | INDEX
    lot_size: int = 1
    is_index: bool = False
    has_futures: bool = True
    has_options: bool = False
    strike_step: float = 0.0
    tradable: bool = True


# --------------------------------------------------------------------------- #
# Structure
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class Pivot:
    pivot_type: str  # HIGH | LOW
    pivot_price: float
    pivot_bar: int
    pivot_timestamp: datetime
    confirmation_bar: int
    confirmation_timestamp: datetime
    reversal_amount: float
    reversal_pct: float
    reversal_atr: Optional[float]
    label: Optional[str] = None  # HH / HL / LH / LL / EQH / EQL (None for first of its type)
    previous_price: Optional[float] = None
    seq: int = 0

    def available_at(self, current_time: datetime) -> bool:
        """The single rule for pivot usability (Section 2)."""
        return current_time >= self.confirmation_timestamp

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seq": self.seq,
            "type": self.pivot_type,
            "price": round(self.pivot_price, 4),
            "bar": self.pivot_bar,
            "time": self.pivot_timestamp.isoformat(),
            "confirmation_bar": self.confirmation_bar,
            "confirmation_time": self.confirmation_timestamp.isoformat(),
            "reversal_amount": round(self.reversal_amount, 4),
            "reversal_pct": round(self.reversal_pct, 3),
            "reversal_atr": None if self.reversal_atr is None else round(self.reversal_atr, 2),
            "label": self.label,
            "previous_price": None if self.previous_price is None else round(self.previous_price, 4),
            "status": "CONFIRMED",
        }


@dataclass(slots=True)
class StructureEvent:
    event_type: str  # BOS | CHOCH
    direction: str  # BULLISH | BEARISH
    level: float
    level_pivot_bar: int
    level_pivot_timestamp: datetime
    event_bar: int
    event_timestamp: datetime
    previous_structure: str
    current_structure: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.event_type,
            "direction": self.direction,
            "level": round(self.level, 4),
            "level_bar": self.level_pivot_bar,
            "level_time": self.level_pivot_timestamp.isoformat(),
            "bar": self.event_bar,
            "time": self.event_timestamp.isoformat(),
            "previous_structure": self.previous_structure,
            "current_structure": self.current_structure,
        }


# --------------------------------------------------------------------------- #
# Zones
# --------------------------------------------------------------------------- #
@dataclass
class Zone:
    zone_id: str
    symbol: str
    timeframe: str
    zone_type: str  # DEMAND | SUPPLY
    pattern: str  # RBR | DBR | RBD | DBD
    proximal: float
    distal: float
    origin_bar: int
    origin_timestamp: datetime
    creation_bar: int
    creation_timestamp: datetime
    base_bars: int
    base_quality: float
    departure_strength: float
    atr_at_creation: float
    trend_at_creation: str
    invalidation_mode: str = "CLOSE"
    touches: List[int] = field(default_factory=list)
    invalidation_bar: Optional[int] = None
    invalidation_timestamp: Optional[datetime] = None
    _inside: bool = False

    # ---- as-of accessors (never read lifecycle events from the future) ---- #
    def touches_as_of(self, bar_index: int) -> int:
        return sum(1 for t in self.touches if t <= bar_index)

    def is_invalidated_as_of(self, bar_index: int) -> bool:
        return self.invalidation_bar is not None and self.invalidation_bar <= bar_index

    def status_as_of(self, bar_index: int) -> str:
        if self.is_invalidated_as_of(bar_index):
            return ZoneStatus.INVALIDATED
        n = self.touches_as_of(bar_index)
        if n == 0:
            return ZoneStatus.FRESH
        if n == 1:
            return ZoneStatus.TESTED_ONCE
        return ZoneStatus.TESTED_MULTIPLE

    @property
    def top(self) -> float:
        return max(self.proximal, self.distal)

    @property
    def bottom(self) -> float:
        return min(self.proximal, self.distal)

    def to_dict(self, as_of: Optional[int] = None) -> Dict[str, Any]:
        i = as_of if as_of is not None else 10 ** 12
        return {
            "id": self.zone_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "type": self.zone_type,
            "pattern": self.pattern,
            "proximal": round(self.proximal, 4),
            "distal": round(self.distal, 4),
            "origin_bar": self.origin_bar,
            "origin_time": self.origin_timestamp.isoformat(),
            "creation_bar": self.creation_bar,
            "creation_time": self.creation_timestamp.isoformat(),
            "base_bars": self.base_bars,
            "base_quality": round(self.base_quality, 3),
            "departure_atr": round(self.departure_strength, 2),
            "touches": self.touches_as_of(i),
            "status": self.status_as_of(i),
            "invalidation_mode": self.invalidation_mode,
            "invalidation_bar": self.invalidation_bar if self.is_invalidated_as_of(i) else None,
            "invalidation_time": (
                self.invalidation_timestamp.isoformat()
                if self.invalidation_timestamp and self.is_invalidated_as_of(i)
                else None
            ),
            "trend_at_creation": self.trend_at_creation,
        }


# --------------------------------------------------------------------------- #
# Volume profile
# --------------------------------------------------------------------------- #
@dataclass
class VolumeProfile:
    profile_type: str
    start_bar: int
    end_bar: int
    price_low: float
    bin_size: float
    volumes: List[float]
    poc: float
    vah: float
    val: float
    hvn: List[float]
    lvn: List[float]
    total_volume: float

    def bin_edges(self, k: int) -> tuple:
        lo = self.price_low + k * self.bin_size
        return lo, lo + self.bin_size

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.profile_type,
            "start_bar": self.start_bar,
            "end_bar": self.end_bar,
            "price_low": round(self.price_low, 4),
            "bin_size": round(self.bin_size, 6),
            "volumes": [round(v, 1) for v in self.volumes],
            "poc": round(self.poc, 4),
            "vah": round(self.vah, 4),
            "val": round(self.val, 4),
            "hvn": [round(x, 4) for x in self.hvn],
            "lvn": [round(x, 4) for x in self.lvn],
            "total_volume": round(self.total_volume, 1),
        }


# --------------------------------------------------------------------------- #
# Positioning & derivatives
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class PositioningRecord:
    category: str  # COMMERCIAL | INSTITUTIONAL | RETAIL
    position_period: date
    publication_timestamp: datetime
    available_to_strategy_timestamp: datetime
    long: float
    short: float
    source: str
    source_type: str  # DIRECT | PROXY


@dataclass(slots=True)
class FuturesOIRecord:
    trade_date: date
    close: float
    open_interest: float
    change_in_oi: float
    available_at: datetime
    source_type: str = Availability.PROXY


@dataclass(slots=True)
class OptionStrike:
    strike: float
    call_oi: float
    put_oi: float
    call_change_oi: float
    put_change_oi: float


@dataclass
class OptionChainSnapshot:
    symbol: str
    trade_date: date
    expiry: date
    underlying: float
    strikes: List[OptionStrike]
    available_at: datetime
    expiry_rollover: bool = False
    source_type: str = Availability.PROXY
    # False when the source's per-strike change is not "vs the previous session" (ΔOI PCR then reports why)
    change_oi_available: bool = True


# --------------------------------------------------------------------------- #
# Price action / decisions
# --------------------------------------------------------------------------- #
@dataclass
class PatternResult:
    pattern: str
    direction: str  # BULLISH | BEARISH
    bar: int
    confidence: float
    metrics: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern": self.pattern,
            "direction": self.direction,
            "bar": self.bar,
            "confidence": round(self.confidence, 3),
            "metrics": self.metrics,
        }


@dataclass
class FactorResult:
    key: str
    name: str
    weight: float
    fraction: Optional[float]  # None -> unavailable
    source: str  # DIRECT | PROXY | DEMO | COMPUTED | UNAVAILABLE
    detail: str
    component: str  # ablation component that owns this factor

    @property
    def available(self) -> bool:
        return self.fraction is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "weight": self.weight,
            "fraction": None if self.fraction is None else round(self.fraction, 4),
            "points": None if self.fraction is None else round(self.weight * self.fraction, 2),
            "source": self.source,
            "detail": self.detail,
            "component": self.component,
            "status": "UNAVAILABLE" if self.fraction is None else ("PASS" if self.fraction >= 0.5 else "WEAK"),
        }


@dataclass
class RuleResult:
    rule: str
    passed: Optional[bool]  # None -> not applicable / disabled
    detail: str
    hard: bool = True
    component: str = "core"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule": self.rule,
            "passed": self.passed,
            "status": "SKIPPED" if self.passed is None else ("PASS" if self.passed else "FAIL"),
            "detail": self.detail,
            "hard": self.hard,
            "component": self.component,
        }


def to_jsonable(obj: Any) -> Any:
    """Recursively convert dataclasses / datetimes into JSON-safe values."""
    if hasattr(obj, "to_dict") and callable(obj.to_dict):
        return to_jsonable(obj.to_dict())
    if is_dataclass(obj):
        return to_jsonable(asdict(obj))
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):
            return None
        return obj
    return obj
