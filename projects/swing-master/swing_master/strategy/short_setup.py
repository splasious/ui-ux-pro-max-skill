"""SHORT setup specification -- the mirror of LONG using LH/LL, supply and
bearish confirmation.  Short trading is switchable via ``ALLOW_SHORT``."""
from .long_setup import LONG_SPEC, SetupSpec

SHORT_SPEC = SetupSpec(
    direction="SHORT", sign=-1, zone_type="SUPPLY", opposing_zone_type="DEMAND", pattern_direction="BEARISH",
    trend="BEARISH", opposite_trend="BULLISH", stop_pivot_type="HIGH", target_pivot_type="LOW",
    trail_label="LH", failure_label="HH", event_direction="BEARISH", config_flag="ALLOW_SHORT",
)


def spec_for(direction: str) -> SetupSpec:
    return LONG_SPEC if direction == "LONG" else SHORT_SPEC
