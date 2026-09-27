"""Centralised strategy configuration (Section 54).

One ``StrategyConfig`` instance is the single authoritative source of every
trading rule parameter.  Backtest, scanner, paper and live execution all read
the same object, so they cannot drift apart.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field, fields, replace
from typing import Any, Dict


def _default_mtf() -> Dict[str, str]:
    # structure timeframe -> higher-timeframe context
    return {"1M": "1M", "1W": "1M", "1D": "1W", "4H": "1D", "1H": "4H", "15m": "1H", "5m": "15m"}


@dataclass(frozen=True)
class StrategyConfig:
    # ---- capital & risk -------------------------------------------------- #
    INITIAL_CAPITAL: float = 1_000_000
    RISK_PER_TRADE: float = 0.01

    # ---- ATR --------------------------------------------------------------- #
    ATR_PERIOD: int = 14

    # ---- ZigZag ------------------------------------------------------------ #
    ZIGZAG_METHOD: str = "ATR"  # PERCENT | ATR | HYBRID
    ZIGZAG_PERCENT: float = 5.0
    ZIGZAG_ATR_MULTIPLIER: float = 2.0
    ZIGZAG_HYBRID_MODE: str = "MAX"  # MAX (stricter) | MIN (looser)

    # ---- structure --------------------------------------------------------- #
    STRUCTURE_EQUAL_TOLERANCE_ATR: float = 0.10
    BOS_BREAK_MODE: str = "CLOSE"  # CLOSE | WICK

    # ---- demand / supply --------------------------------------------------- #
    ZONE_BASE_MAX_BARS: int = 4
    ZONE_BASE_MAX_BODY_RATIO: float = 0.5
    ZONE_BASE_MAX_RANGE_ATR: float = 1.6
    ZONE_LEG_MIN_BODY_RATIO: float = 0.5
    ZONE_LEGIN_MIN_BODY_RATIO: float = 0.3
    ZONE_LEG_MIN_RANGE_ATR: float = 0.8
    ZONE_MIN_DEPARTURE_ATR: float = 0.6
    ZONE_INVALIDATION_MODE: str = "CLOSE"  # CLOSE | WICK
    ZONE_MAX_ACTIVE_PER_SIDE: int = 12
    ZONE_MAX_PRIOR_TESTS: int = 1
    ZONE_TOUCH_BUFFER_ATR: float = 0.10

    # ---- volume profile ---------------------------------------------------- #
    VOLUME_PROFILE_BINS: int = 50
    VALUE_AREA_PERCENT: float = 0.70
    VP_LOOKBACK_BARS: int = 120
    VP_SETUP_PROFILE: str = "FIXED"  # FIXED | SWING | STRUCTURAL_LEG
    VP_NEAR_ATR: float = 1.0
    HVN_THRESHOLD: float = 1.25  # x mean bin volume
    LVN_THRESHOLD: float = 0.50

    # ---- positioning ------------------------------------------------------- #
    POSITIONING_MIN_HISTORY: int = 20
    POSITIONING_BANDS: tuple = (10.0, 30.0, 70.0, 90.0)  # percentile band edges
    POSITIONING_AVAILABILITY_DELAY_MIN: int = 120  # after publication

    # ---- derivatives ------------------------------------------------------- #
    OI_CHANGE_THRESHOLD_PCT: float = 0.5
    PRICE_CHANGE_THRESHOLD_PCT: float = 0.1
    FUTURES_OI_PUBLICATION_DELAY_MIN: int = 180  # EOD bhavcopy after close
    PCR_STRIKES_EACH_SIDE: int = 10
    PCR_MIN_STRIKE_OI: float = 1000.0

    # ---- candlesticks ------------------------------------------------------ #
    MIN_PATTERN_CONFIDENCE: float = 0.45
    PATTERN_MIN_RANGE_ATR: float = 0.5

    # ---- scoring ----------------------------------------------------------- #
    # The build prompt suggests 70 / 70.  With the calibrated component
    # functions and no participant-positioning feed, 70 / 70 admits only a
    # handful of setups on the demo universe, so the shipped defaults are
    # 60 / 65; the Walk-Forward lab re-selects both out of sample.
    MIN_ZONE_SCORE: float = 60
    MIN_CONFLUENCE_SCORE: float = 65
    MIN_FACTOR_COVERAGE: float = 0.60  # share of weight that must be available
    UNAVAILABLE_FACTOR_POLICY: str = "RENORMALIZE"  # RENORMALIZE | ZERO | REJECT

    # ---- gate policies ----------------------------------------------------- #
    HTF_POLICY: str = "NOT_OPPOSITE"  # ALIGNED | NOT_OPPOSITE | OFF
    STRUCTURE_POLICY: str = "TREND"  # TREND | NOT_OPPOSITE

    # ---- entry ------------------------------------------------------------- #
    ENTRY_MODE: str = "NEXT_OPEN"  # REVERSAL_CLOSE | NEXT_OPEN | BREAK_OF_REVERSAL | LIMIT_IN_ZONE
    ENTRY_ORDER_VALIDITY_BARS: int = 2
    EOD_DECISION_DELAY_MIN: int = 300  # EOD scan runs 5h after close (after bhavcopy)

    # ---- stops & targets --------------------------------------------------- #
    STOP_REFERENCE: str = "ZONE"  # ZONE | SWING | WIDER
    STOP_ATR_BUFFER: float = 0.5
    TRAIL_ATR_BUFFER: float = 0.5
    TARGET_1_R: float = 1.0
    TARGET_2_R: float = 2.0
    TARGET_3_R: float = 3.0
    T1_METHOD: str = "R"  # R | POC | HVN | STRUCTURE | NEAREST
    T2_METHOD: str = "STRUCTURE_OR_R"  # STRUCTURE_OR_R | R
    T3_METHOD: str = "HTF_OR_R"  # HTF_OR_R | R
    TARGET_1_EXIT_PERCENT: float = 0.30
    TARGET_2_EXIT_PERCENT: float = 0.30
    RUNNER_PERCENT: float = 0.40
    BREAKEVEN_MODE: str = "ENTRY"  # KEEP | ENTRY | ENTRY_PLUS_COSTS | ATR_ADJUSTED
    BREAKEVEN_ATR: float = 0.25
    TRAIL_ACTIVATION: str = "IMMEDIATE"  # IMMEDIATE | AFTER_T1 | AFTER_T2
    MIN_RR: float = 1.5

    # ---- exits ------------------------------------------------------------- #
    MAX_HOLDING_BARS: int = 40
    EXIT_ON_ZONE_INVALIDATION: bool = True
    EXIT_ON_STRUCTURAL_FAILURE: bool = True
    EXIT_ON_OPPOSITE_EVENT: str = "OFF"  # OFF | CHOCH | BOS
    SAME_BAR_POLICY: str = "STOP_FIRST"  # conservative: stop assumed first
    GAP_POLICY: str = "CANCEL"  # cancel entries that gap through stop or T1

    # ---- portfolio --------------------------------------------------------- #
    MAX_POSITIONS: int = 5
    MAX_POSITION_PERCENT: float = 0.20
    MAX_PORTFOLIO_RISK: float = 0.05
    MAX_SECTOR_EXPOSURE: float = 0.40
    MAX_POSITIONS_PER_SECTOR: int = 2
    MAX_DAILY_LOSS: float = 0.02
    PORTFOLIO_EXIT_ON_DAILY_LOSS: bool = True  # flatten everything when the day's loss breaches MAX_DAILY_LOSS
    MAX_DRAWDOWN_HALT: float = 0.20  # flatten and stop new entries beyond this peak-to-trough drawdown
    ATR_PERCENTILE_LOOKBACK: int = 252  # volatility comparison window (Section 5)
    CORRELATION_WARNING: float = 0.70
    CORRELATION_LOOKBACK: int = 60

    ALLOW_LONG: bool = True
    ALLOW_SHORT: bool = True

    MTF_HIERARCHY: Dict[str, str] = field(default_factory=_default_mtf)
    WARMUP_BARS: int = 60

    # ---- execution costs (NSE equity delivery approximation) --------------- #
    SLIPPAGE_BPS: float = 5.0
    BROKERAGE_PER_ORDER: float = 20.0
    STT_PCT: float = 0.001
    EXCHANGE_PCT: float = 0.0000297
    SEBI_PCT: float = 0.000001
    GST_PCT: float = 0.18
    STAMP_PCT_BUY: float = 0.00015

    # ------------------------------------------------------------------------ #
    def with_overrides(self, **overrides: Any) -> "StrategyConfig":
        known = {f.name: f for f in fields(self)}
        clean: Dict[str, Any] = {}
        for key, value in overrides.items():
            if key not in known:
                raise KeyError(f"Unknown config parameter: {key}")
            current = getattr(self, key)
            clean[key] = _coerce(value, current)
        cfg = replace(self, **clean)
        cfg.validate()
        return cfg

    def validate(self) -> None:
        problems = []
        if not (0 < self.RISK_PER_TRADE <= 0.05):
            problems.append("RISK_PER_TRADE must be in (0, 0.05]")
        split = self.TARGET_1_EXIT_PERCENT + self.TARGET_2_EXIT_PERCENT + self.RUNNER_PERCENT
        if not math.isclose(split, 1.0, abs_tol=1e-6):
            problems.append("T1 + T2 + runner allocation must equal 100%")
        if not (self.TARGET_1_R < self.TARGET_2_R < self.TARGET_3_R):
            problems.append("TARGET_1_R < TARGET_2_R < TARGET_3_R required")
        if self.ZIGZAG_METHOD not in ("PERCENT", "ATR", "HYBRID"):
            problems.append("ZIGZAG_METHOD must be PERCENT, ATR or HYBRID")
        if self.ENTRY_MODE not in ("REVERSAL_CLOSE", "NEXT_OPEN", "BREAK_OF_REVERSAL", "LIMIT_IN_ZONE"):
            problems.append("Unknown ENTRY_MODE")
        if self.UNAVAILABLE_FACTOR_POLICY not in ("RENORMALIZE", "ZERO", "REJECT"):
            problems.append("Unknown UNAVAILABLE_FACTOR_POLICY")
        if not (0 < self.VALUE_AREA_PERCENT < 1):
            problems.append("VALUE_AREA_PERCENT must be in (0, 1)")
        if self.VOLUME_PROFILE_BINS < 5:
            problems.append("VOLUME_PROFILE_BINS must be >= 5")
        if self.MAX_PORTFOLIO_RISK < self.RISK_PER_TRADE:
            problems.append("MAX_PORTFOLIO_RISK must be >= RISK_PER_TRADE")
        if problems:
            raise ValueError("; ".join(problems))

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["POSITIONING_BANDS"] = list(self.POSITIONING_BANDS)
        return d

    def analysis_key(self) -> str:
        """Parameters that change the precomputed analysis (pivots, zones, candidates)."""
        keys = [
            "ATR_PERIOD", "ZIGZAG_METHOD", "ZIGZAG_PERCENT", "ZIGZAG_ATR_MULTIPLIER", "ZIGZAG_HYBRID_MODE",
            "STRUCTURE_EQUAL_TOLERANCE_ATR", "BOS_BREAK_MODE", "ZONE_BASE_MAX_BARS", "ZONE_BASE_MAX_BODY_RATIO",
            "ZONE_BASE_MAX_RANGE_ATR", "ZONE_LEG_MIN_BODY_RATIO", "ZONE_LEGIN_MIN_BODY_RATIO",
            "ZONE_LEG_MIN_RANGE_ATR", "ZONE_MIN_DEPARTURE_ATR", "ZONE_INVALIDATION_MODE",
            "ZONE_MAX_ACTIVE_PER_SIDE", "ZONE_TOUCH_BUFFER_ATR", "VOLUME_PROFILE_BINS", "VALUE_AREA_PERCENT",
            "VP_LOOKBACK_BARS", "VP_SETUP_PROFILE", "VP_NEAR_ATR", "HVN_THRESHOLD", "LVN_THRESHOLD",
            "ENTRY_MODE", "EOD_DECISION_DELAY_MIN", "STOP_REFERENCE", "STOP_ATR_BUFFER", "TARGET_1_R",
            "TARGET_2_R", "TARGET_3_R", "T1_METHOD", "T2_METHOD", "T3_METHOD", "PATTERN_MIN_RANGE_ATR",
            "OI_CHANGE_THRESHOLD_PCT", "PRICE_CHANGE_THRESHOLD_PCT", "PCR_STRIKES_EACH_SIDE",
            "WARMUP_BARS",
        ]
        return json.dumps({k: getattr(self, k) for k in keys}, sort_keys=True)


def _coerce(value: Any, current: Any) -> Any:
    if isinstance(current, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(current, int) and not isinstance(current, bool):
        return int(float(value))
    if isinstance(current, float):
        v = float(value)
        if not math.isfinite(v):
            raise ValueError("Config values must be finite")
        return v
    if isinstance(current, tuple):
        return tuple(value)
    return value


# Parameters exposed for editing in the Settings screen (key -> help text).
EDITABLE_PARAMETERS: Dict[str, str] = {
    "RISK_PER_TRADE": "Fraction of equity risked per trade",
    "ZIGZAG_METHOD": "PERCENT, ATR or HYBRID reversal threshold",
    "ZIGZAG_ATR_MULTIPLIER": "ATR multiple required to confirm a pivot",
    "ZIGZAG_PERCENT": "Percent reversal required to confirm a pivot",
    "MIN_ZONE_SCORE": "Minimum zone score (0-100)",
    "MIN_CONFLUENCE_SCORE": "Minimum confluence score (0-100)",
    "UNAVAILABLE_FACTOR_POLICY": "How unavailable data factors are scored",
    "ENTRY_MODE": "Entry trigger",
    "STOP_ATR_BUFFER": "ATR buffer beyond the zone distal line",
    "TRAIL_ATR_BUFFER": "ATR buffer beyond the confirmed HL/LH",
    "BREAKEVEN_MODE": "Stop handling after T1",
    "TRAIL_ACTIVATION": "When the structural trail starts",
    "MIN_RR": "Minimum reward:risk to T2",
    "MAX_POSITIONS": "Maximum simultaneous positions",
    "MAX_PORTFOLIO_RISK": "Maximum open risk as a fraction of equity",
    "MAX_HOLDING_BARS": "Maximum holding period in bars",
    "ALLOW_LONG": "Allow long setups",
    "ALLOW_SHORT": "Allow short setups",
    "HTF_POLICY": "Higher-timeframe requirement",
}
