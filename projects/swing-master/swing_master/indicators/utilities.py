"""Small numerical helpers (pure Python, no external dependencies)."""
from __future__ import annotations

import math
from typing import Iterable, List, Optional, Sequence


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def is_finite(x) -> bool:
    try:
        return x is not None and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def safe_div(num: float, den: float) -> Optional[float]:
    """Division that returns ``None`` instead of raising / producing inf."""
    if den == 0 or not is_finite(num) or not is_finite(den):
        return None
    return num / den


def ema_series(values: Sequence[float], period: int) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    k = 2.0 / (period + 1)
    ema: Optional[float] = None
    seed: List[float] = []
    for v in values:
        if ema is None:
            seed.append(v)
            if len(seed) == period:
                ema = sum(seed) / period
            out.append(ema)
        else:
            ema = v * k + ema * (1 - k)
            out.append(ema)
    return out


def sma(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def mean_std(values: Sequence[float]):
    n = len(values)
    if n == 0:
        return None, None
    m = sum(values) / n
    if n < 2:
        return m, 0.0
    var = sum((v - m) ** 2 for v in values) / (n - 1)
    return m, math.sqrt(var)


def percentile_rank(history: Sequence[float], value: float) -> Optional[float]:
    """Share (0-100) of observations <= value.  ``history`` must contain only past data."""
    if not history:
        return None
    below = sum(1 for h in history if h <= value)
    return 100.0 * below / len(history)


def zscore(history: Sequence[float], value: float) -> Optional[float]:
    m, s = mean_std(history)
    if m is None or not s:
        return None
    return (value - m) / s


def pearson(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    n = min(len(a), len(b))
    if n < 3:
        return None
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va == 0 or vb == 0:
        return None
    return cov / math.sqrt(va * vb)


def pct_returns(closes: Iterable[float]) -> List[float]:
    out, prev = [], None
    for c in closes:
        if prev:
            out.append(c / prev - 1.0)
        prev = c
    return out


def volatility_profile(atr_values: Sequence[Optional[float]], closes: Sequence[float], lookback: int = 252) -> dict:
    """ATR as % of price and its percentile within the trailing ``lookback`` ATR readings (causal)."""
    hist = [a for a in atr_values[-lookback:] if a]
    if not hist or not closes:
        return {"atr": None, "atr_pct": None, "percentile": None, "regime": "UNAVAILABLE"}
    cur = hist[-1]
    pct = 100.0 * sum(1 for a in hist if a <= cur) / len(hist)
    regime = "LOW" if pct < 25 else "HIGH" if pct > 75 else "NORMAL"
    prev = hist[-11] if len(hist) > 10 else hist[0]
    trend = "EXPANDING" if cur > prev * 1.1 else "CONTRACTING" if cur < prev * 0.9 else "STABLE"
    return {"atr": round(cur, 4), "atr_pct": round(100.0 * cur / closes[-1], 3), "percentile": round(pct, 1),
            "regime": regime, "trend": trend, "lookback": len(hist)}


def median(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2
