"""Scoring weights and interpretation tables (Sections 10, 14, 18, 21).

All weights are configurable; every contribution is exposed to the UI so the
score is never a black box.
"""
from __future__ import annotations

from typing import Dict

# Section 21 -- confluence score, total 100.  component = ablation switch owning the factor.
CONFLUENCE_WEIGHTS: Dict[str, Dict] = {
    "structure": {"name": "Market Structure", "weight": 15, "component": "structure"},
    "zone": {"name": "Demand / Supply", "weight": 15, "component": "zones"},
    "volume_profile": {"name": "Volume Profile", "weight": 15, "component": "volume_profile"},
    "htf": {"name": "Higher-TF", "weight": 10, "component": "structure"},
    "candlestick": {"name": "Candlestick", "weight": 10, "component": "candlestick"},
    "smart_money": {"name": "Commercial / Institutional", "weight": 10, "component": "commercial"},
    "retail": {"name": "Retail", "weight": 5, "component": "retail"},
    "oi_pcr": {"name": "OI / PCR", "weight": 5, "component": "oi"},
    "bos": {"name": "BOS / CHoCH", "weight": 5, "component": "bos"},
    "risk_reward": {"name": "Risk / Reward", "weight": 10, "component": "core"},
}

# Section 10 -- zone score, total 100.
ZONE_SCORE_WEIGHTS: Dict[str, Dict] = {
    "freshness": {"name": "Freshness", "weight": 15, "component": "zones"},
    "base_quality": {"name": "Base quality", "weight": 10, "component": "zones"},
    "departure": {"name": "Departure strength", "weight": 15, "component": "zones"},
    "time_in_base": {"name": "Time in base", "weight": 5, "component": "zones"},
    "pivot_alignment": {"name": "Pivot alignment", "weight": 10, "component": "structure"},
    "bos_relationship": {"name": "BOS relationship", "weight": 10, "component": "bos"},
    "htf_alignment": {"name": "Higher-TF alignment", "weight": 10, "component": "structure"},
    "poc_relationship": {"name": "POC relationship", "weight": 8, "component": "volume_profile"},
    "volume_profile": {"name": "Volume profile", "weight": 5, "component": "volume_profile"},
    "positioning": {"name": "Positioning", "weight": 4, "component": "commercial"},
    "candlestick": {"name": "Candlestick confirmation", "weight": 4, "component": "candlestick"},
    "risk_reward": {"name": "Risk / reward", "weight": 4, "component": "core"},
}

# Ablation components (Section 40)
COMPONENTS = ["structure", "zones", "volume_profile", "candlestick", "commercial",
              "institutional", "retail", "oi", "pcr", "bos"]

ABLATION_LADDER = [
    ("Structure only", ["structure"]),
    ("Structure + Zones", ["structure", "zones"]),
    ("+ Volume", ["structure", "zones", "volume_profile"]),
    ("+ Price Action", ["structure", "zones", "volume_profile", "candlestick", "bos"]),
    ("+ Positioning", ["structure", "zones", "volume_profile", "candlestick", "bos",
                       "commercial", "institutional", "retail"]),
    ("+ Derivatives", COMPONENTS),
]

# Section 14 -- classification to directional support.  Retail is read contrarian.
POSITION_CLASS_SCORE_LONG = {
    "STRONG LONG": 1.0, "LONG": 0.75, "NEUTRAL": 0.5, "SHORT": 0.25, "STRONG SHORT": 0.0,
}

# Section 17 -- futures OI state support for a LONG setup (mirrored for shorts).
OI_STATE_SCORE_LONG = {
    "LONG BUILD-UP": 1.0, "SHORT COVERING": 0.75, "NEUTRAL": 0.5,
    "LONG UNWINDING": 0.25, "SHORT BUILD-UP": 0.0,
}

# Section 18 -- PCR interpretation bands for a LONG setup: (upper bound, score, label).
PCR_BANDS_LONG = [
    (0.6, 0.15, "Very low PCR: call writing dominates"),
    (0.8, 0.35, "Low PCR: bearish tilt"),
    (1.2, 0.60, "Balanced PCR"),
    (1.6, 0.85, "High PCR: put writing supports price"),
    (float("inf"), 0.55, "Extreme PCR: crowded, contrarian caution"),
]

# Section 19 / 54 -- candlestick definitions (bullish side; bearish patterns mirror them).
CANDLE_RULES: Dict[str, float] = {
    "hammer_wick_to_body": 2.0,          # lower wick >= x * body
    "hammer_max_upper_frac": 0.25,       # upper wick <= x * range
    "hammer_min_close_loc": 0.6,         # close in the top 40 %
    "pin_min_wick_frac": 0.66,           # wick >= x * range
    "pin_max_body_frac": 0.33,           # body <= x * range
    "pin_min_close_loc": 0.6,
    "pin_min_range_atr": 0.8,
    "star_min_first_body_atr": 0.6,      # morning/evening star first candle body >= x ATR
    "star_max_middle_body_frac": 0.35,   # middle body <= x * first body
    "tweezer_max_diff_atr": 0.1,         # lows/highs within x ATR
    "tweezer_min_range_atr": 0.5,
    "rejection_min_wick_frac": 0.5,
    "rejection_min_close_loc": 0.7,
    "rejection_min_range_atr": 0.8,
}

# Reward:risk (to T2) -> score fraction.
RR_SCORE_BANDS = [(3.0, 1.0), (2.5, 0.9), (2.0, 0.8), (1.75, 0.65), (1.5, 0.5), (1.0, 0.2)]


def rr_fraction(rr: float) -> float:
    for threshold, frac in RR_SCORE_BANDS:
        if rr >= threshold:
            return frac
    return 0.0


def pcr_fraction_long(pcr: float):
    for upper, frac, label in PCR_BANDS_LONG:
        if pcr < upper:
            return frac, label
    return 0.5, "Balanced PCR"
