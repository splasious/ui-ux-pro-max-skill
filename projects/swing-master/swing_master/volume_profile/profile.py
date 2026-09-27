"""Volume profile construction (Section 11).

OHLCV approximation (documented, deterministic)
-----------------------------------------------
Exchange data does not tell us at which prices a bar's volume traded.  We
spread each bar's volume UNIFORMLY across its high-low range and credit each
price bin with the share of the range it overlaps.  A zero-range bar credits
its whole volume to the bin containing its close.  This is the standard
"uniform range" approximation; it is unbiased for random intrabar paths and
never uses bars outside the requested window.

Profile windows (all end at the evaluation bar -- never later):
* FIXED           last ``lookback`` bars
* SWING           between the last two CONFIRMED pivots
* STRUCTURAL_LEG  from the last CONFIRMED pivot to the evaluation bar
* DAILY / WEEKLY  bars in the evaluation bar's calendar day / ISO week
* HIGHER_TF       last ``lookback`` x 5 bars (a higher-timeframe composite)
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from ..schemas import Bar, Pivot, VolumeProfile
from .poc import find_poc, volume_nodes
from .value_area import value_area

PROFILE_TYPES = ("FIXED", "SWING", "STRUCTURAL_LEG", "DAILY", "WEEKLY", "HIGHER_TF")


def build_profile(bars: Sequence[Bar], start: int, end: int, bins: int = 50, va_percent: float = 0.70,
                  profile_type: str = "FIXED", hvn_threshold: float = 1.25,
                  lvn_threshold: float = 0.5) -> Optional[VolumeProfile]:
    """Profile of ``bars[start..end]`` inclusive.  Never reads beyond ``end``."""
    if end < start or start < 0 or end >= len(bars):
        return None
    window = bars[start:end + 1]
    lo = min(b.low for b in window)
    hi = max(b.high for b in window)
    if hi <= lo:
        hi = lo + max(abs(lo) * 1e-4, 1e-6)
    size = (hi - lo) / bins
    vols = [0.0] * bins
    for b in window:
        v = b.volume
        if v <= 0:
            continue
        x0 = (b.low - lo) / size
        x1 = (b.high - lo) / size
        k0 = min(bins - 1, int(x0))
        k1 = min(bins - 1, int(x1))
        if x1 <= x0 or k0 == k1:
            vols[k0 if x1 > x0 else min(bins - 1, int((b.close - lo) / size))] += v
            continue
        per = v / (x1 - x0)  # volume per bin width (uniform over the bar's range)
        vols[k0] += per * (k0 + 1 - x0)
        for k in range(k0 + 1, k1):
            vols[k] += per
        vols[k1] += per * (x1 - k1)
    total = sum(vols)
    if total <= 0:
        return None
    poc_k = find_poc(vols)
    va_lo, va_hi = value_area(vols, poc_k, va_percent)
    hvn_k, lvn_k = volume_nodes(vols, hvn_threshold, lvn_threshold)
    centre = lambda k: lo + (k + 0.5) * size  # noqa: E731
    return VolumeProfile(
        profile_type=profile_type,
        start_bar=start,
        end_bar=end,
        price_low=lo,
        bin_size=size,
        volumes=vols,
        poc=centre(poc_k),
        vah=lo + (va_hi + 1) * size,
        val=lo + va_lo * size,
        hvn=[centre(k) for k in hvn_k],
        lvn=[centre(k) for k in lvn_k],
        total_volume=total,
    )


def profile_window(kind: str, bars: Sequence[Bar], end: int, confirmed_pivots: List[Pivot],
                   lookback: int = 120) -> Tuple[int, int]:
    """Resolve the [start, end] bar window for a profile type.

    ``confirmed_pivots`` must already be filtered to pivots confirmed at or
    before ``end``; that is the caller's contract and keeps this pure.
    """
    kind = kind.upper()
    if kind == "SWING" and len(confirmed_pivots) >= 2:
        a, b = confirmed_pivots[-2], confirmed_pivots[-1]
        return min(a.pivot_bar, b.pivot_bar), max(a.pivot_bar, b.pivot_bar)
    if kind == "STRUCTURAL_LEG" and confirmed_pivots:
        return confirmed_pivots[-1].pivot_bar, end
    if kind in ("DAILY", "WEEKLY"):
        ref = bars[end].timestamp
        start = end
        while start - 1 >= 0:
            t = bars[start - 1].timestamp
            same = (t.date() == ref.date()) if kind == "DAILY" else (t.isocalendar()[:2] == ref.isocalendar()[:2])
            if not same:
                break
            start -= 1
        return start, end
    if kind == "HIGHER_TF":
        return max(0, end - lookback * 5 + 1), end
    return max(0, end - lookback + 1), end
