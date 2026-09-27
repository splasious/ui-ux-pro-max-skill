"""Mathematically defined candlestick reversals (Section 19).

Notation for a candle: body = |C-O|, range = H-L, upper = H-max(O,C),
lower = min(O,C)-L, close location = (C-L)/range, ATR range = range/ATR.

Bullish definitions (bearish patterns are the exact mirror image, computed by
reflecting prices through zero so both sides share one implementation):

HAMMER            lower >= 2*body, upper <= 0.25*range, close loc >= 0.6
BULLISH PIN BAR   lower >= 0.66*range, body <= 0.33*range, close loc >= 0.6,
                  low < previous low, ATR range >= 0.8
BULLISH ENGULFING previous bearish, current bullish, O <= prev C, C >= prev O,
                  body > previous body
MORNING STAR      c[-2] bearish with body >= 0.6 ATR, c[-1] body <= 0.35 x c[-2]
                  body, c[0] bullish closing above c[-2] body midpoint
TWEEZER BOTTOM    previous bearish, current bullish, |L - prev L| <= 0.1 ATR,
                  both ranges >= 0.5 ATR
BULLISH REJECTION lower >= 0.5*range, close loc >= 0.7, ATR range >= 0.8,
                  low below the prior two lows

Every candle must also span at least ``min_range_atr`` x ATR (noise filter).
Confidence is a 0-1 blend of how far thresholds are exceeded and candle size.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from ..config.scoring_config import CANDLE_RULES as R
from ..indicators.utilities import clamp
from ..schemas import Bar, PatternResult

OHLC = Tuple[float, float, float, float]

MIRROR_NAMES = {
    "HAMMER": "SHOOTING STAR",
    "BULLISH PIN BAR": "BEARISH PIN BAR",
    "BULLISH ENGULFING": "BEARISH ENGULFING",
    "MORNING STAR": "EVENING STAR",
    "TWEEZER BOTTOM": "TWEEZER TOP",
    "BULLISH REJECTION": "BEARISH REJECTION",
}


def _ohlc(b: Bar) -> OHLC:
    return (b.open, b.high, b.low, b.close)


def _mirror(c: OHLC) -> OHLC:
    o, h, l, cl = c
    return (-o, -l, -h, -cl)


def candle_metrics(bar: Bar, atr: Optional[float]) -> Dict:
    rng = bar.high - bar.low
    body = abs(bar.close - bar.open)
    upper = bar.high - max(bar.open, bar.close)
    lower = min(bar.open, bar.close) - bar.low
    return {
        "range": round(rng, 4),
        "body_ratio": round(body / rng, 3) if rng else 0.0,
        "upper_wick_ratio": round(upper / rng, 3) if rng else 0.0,
        "lower_wick_ratio": round(lower / rng, 3) if rng else 0.0,
        "close_location": round((bar.close - bar.low) / rng, 3) if rng else 0.5,
        "atr_range": round(rng / atr, 2) if atr else None,
    }


def previous_relationship(cur: Bar, prev: Optional[Bar]) -> str:
    if prev is None:
        return "No previous candle"
    parts = []
    lo_b, hi_b = min(cur.open, cur.close), max(cur.open, cur.close)
    plo_b, phi_b = min(prev.open, prev.close), max(prev.open, prev.close)
    if lo_b <= plo_b and hi_b >= phi_b and (hi_b - lo_b) > (phi_b - plo_b):
        parts.append("body engulfs prior body")
    if cur.high <= prev.high and cur.low >= prev.low:
        parts.append("inside prior range")
    if cur.low < prev.low:
        parts.append("low below prior low")
    if cur.high > prev.high:
        parts.append("high above prior high")
    return ", ".join(parts) or "overlaps prior candle"


def _bullish(c0: OHLC, c1: Optional[OHLC], c2: Optional[OHLC], atr: float, min_range_atr: float,
             prior_lows: Sequence[float]) -> List[Tuple[str, float]]:
    o, h, l, c = c0
    rng = h - l
    if rng <= 0 or rng < min_range_atr * atr:
        return []
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l
    loc = (c - l) / rng
    size = clamp(rng / atr / 1.5)
    found: List[Tuple[str, float]] = []

    if lower >= R["hammer_wick_to_body"] * body and upper <= R["hammer_max_upper_frac"] * rng \
            and loc >= R["hammer_min_close_loc"]:
        found.append(("HAMMER", clamp(0.35 + 0.35 * clamp((lower / rng - 0.5) / 0.35) + 0.3 * size)))

    if c1 is not None:
        po, ph, pl, pc = c1
        if lower >= R["pin_min_wick_frac"] * rng and body <= R["pin_max_body_frac"] * rng \
                and loc >= R["pin_min_close_loc"] and l < pl and rng >= R["pin_min_range_atr"] * atr:
            found.append(("BULLISH PIN BAR", clamp(0.45 + 0.3 * clamp((lower / rng - R["pin_min_wick_frac"]) / 0.25)
                                                   + 0.25 * size)))
        pbody = abs(pc - po)
        if pc < po and c > o and o <= pc and c >= po and body > pbody:
            ratio = clamp((body / pbody - 1.0) if pbody else 1.0)
            found.append(("BULLISH ENGULFING", clamp(0.45 + 0.25 * ratio + 0.3 * size)))
        prng = ph - pl
        tw = R["tweezer_max_diff_atr"] * atr
        if pc < po and c > o and abs(l - pl) <= tw and rng >= R["tweezer_min_range_atr"] * atr \
                and prng >= R["tweezer_min_range_atr"] * atr:
            found.append(("TWEEZER BOTTOM", clamp(0.4 + 0.3 * (1 - abs(l - pl) / tw) + 0.3 * loc)))

    if c1 is not None and c2 is not None:
        o2, h2, l2, cl2 = c2
        o1, h1, l1, cl1 = c1
        b2 = o2 - cl2
        if b2 >= R["star_min_first_body_atr"] * atr and abs(cl1 - o1) <= R["star_max_middle_body_frac"] * b2 and c > o:
            mid = (o2 + cl2) / 2.0
            if c > mid:
                found.append(("MORNING STAR", clamp(0.5 + 0.5 * clamp((c - mid) / (o2 - mid) if o2 > mid else 1.0))))

    if prior_lows and lower >= R["rejection_min_wick_frac"] * rng and loc >= R["rejection_min_close_loc"] \
            and rng >= R["rejection_min_range_atr"] * atr and l < min(prior_lows):
        found.append(("BULLISH REJECTION", clamp(0.35 + 0.35 * clamp((loc - 0.7) / 0.3) + 0.3 * size)))
    return found


def detect_patterns(bars: Sequence[Bar], i: int, atr: Optional[float], min_range_atr: float = 0.5) -> List[PatternResult]:
    """All bullish and bearish patterns completing on bar ``i`` (uses bars <= i only)."""
    if atr is None or atr <= 0 or i < 0:
        return []
    c0 = _ohlc(bars[i])
    c1 = _ohlc(bars[i - 1]) if i >= 1 else None
    c2 = _ohlc(bars[i - 2]) if i >= 2 else None
    prior = bars[max(0, i - 2):i]
    metrics = candle_metrics(bars[i], atr)
    metrics["previous_relationship"] = previous_relationship(bars[i], bars[i - 1] if i >= 1 else None)
    out: List[PatternResult] = []
    for name, conf in _bullish(c0, c1, c2, atr, min_range_atr, [b.low for b in prior]):
        out.append(PatternResult(name, "BULLISH", i, conf, dict(metrics)))
    m = lambda x: None if x is None else _mirror(x)  # noqa: E731
    for name, conf in _bullish(m(c0), m(c1), m(c2), atr, min_range_atr, [-b.high for b in prior]):
        out.append(PatternResult(MIRROR_NAMES[name], "BEARISH", i, conf, dict(metrics)))
    return out


def best_pattern(patterns: List[PatternResult], direction: str) -> Optional[PatternResult]:
    want = "BULLISH" if direction == "LONG" else "BEARISH"
    cands = [p for p in patterns if p.direction == want]
    return max(cands, key=lambda p: p.confidence) if cands else None
