"""LONG setup specification (Section 20).

    Bullish Higher TF -> Confirmed HH/HL -> Bullish BOS where applicable
    -> Retracement -> Qualified Demand -> Volume/POC Confluence
    -> Participant Positioning -> OI/PCR Context -> Bullish Reversal
    -> Minimum Confluence -> LONG CANDIDATE

The rule chain itself lives once in ``signal_engine`` and is parameterised by
this spec; SHORT is the exact mirror (``short_setup.SHORT_SPEC``), so the two
directions can never drift apart.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SetupSpec:
    direction: str
    sign: int  # +1 long, -1 short (price distance orientation)
    zone_type: str
    opposing_zone_type: str
    pattern_direction: str
    trend: str
    opposite_trend: str
    stop_pivot_type: str
    target_pivot_type: str
    trail_label: str  # confirmed pivot label that advances the trailing stop
    failure_label: str  # confirmed pivot label that marks structural failure
    event_direction: str
    config_flag: str

    def better(self, a: float, b: float) -> bool:
        """True when price ``a`` is more favourable than ``b`` for this direction."""
        return a > b if self.sign > 0 else a < b


LONG_SPEC = SetupSpec(
    direction="LONG", sign=1, zone_type="DEMAND", opposing_zone_type="SUPPLY", pattern_direction="BULLISH",
    trend="BULLISH", opposite_trend="BEARISH", stop_pivot_type="LOW", target_pivot_type="HIGH",
    trail_label="HL", failure_label="LL", event_direction="BULLISH", config_flag="ALLOW_LONG",
)
