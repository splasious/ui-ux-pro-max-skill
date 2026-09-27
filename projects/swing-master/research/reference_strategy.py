"""Phase A -- standalone reference strategy.

A deliberately independent, single-file, single-symbol implementation of the
complete trading logic, written straight from the specification and processed
strictly chronologically.  It shares NO code with ``swing_master``; the test
suite (``swing_master/tests/test_reference.py``) runs both on the same data and
requires them to agree on ATR, confirmed pivots, volume-profile levels and
position sizing.  Divergence means one of the two has a bug.

Components: ATR -> confirmed ZigZag -> HH/HL/LH/LL -> demand/supply zones ->
volume profile -> positioning percentile -> candlestick confirmation ->
risk sizing -> T1/T2/T3 -> structural trailing stop -> event-driven backtest.

Usage::

    python research/reference_strategy.py                 # self-contained random-walk demo
    python research/reference_strategy.py --csv DAILY.csv # date,open,high,low,close,volume
"""
from __future__ import annotations

import argparse
import csv
import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple


# --------------------------------------------------------------------------- data
@dataclass
class Candle:
    t: str
    o: float
    h: float
    l: float
    c: float
    v: float


# --------------------------------------------------------------------------- ATR (Wilder)
def wilder_atr(candles: Sequence[Candle], n: int = 14) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    seed: List[float] = []
    atr = None
    prev_c = None
    for k in candles:
        tr = k.h - k.l if prev_c is None else max(k.h - k.l, abs(k.h - prev_c), abs(k.l - prev_c))
        prev_c = k.c
        if atr is None:
            seed.append(tr)
            if len(seed) == n:
                atr = sum(seed) / n
        else:
            atr = (atr * (n - 1) + tr) / n
        out.append(atr)
    return out


# --------------------------------------------------------------------------- confirmed ZigZag
@dataclass
class RefPivot:
    kind: str  # H or L
    price: float
    bar: int
    confirm_bar: int
    label: Optional[str] = None


def confirmed_zigzag(candles: Sequence[Candle], atr: Sequence[Optional[float]], mult: float = 2.0,
                     pct: float = 5.0, method: str = "ATR") -> List[RefPivot]:
    """Reversal from the running extreme by the threshold confirms the extreme.

    A bar that makes a new extreme never confirms a reversal on the same bar.
    """
    def thr(ref: float, a: Optional[float]) -> Optional[float]:
        p = abs(ref) * pct / 100.0
        x = a * mult if a else None
        if method == "PERCENT":
            return p
        if method == "ATR":
            return x
        return p if x is None else max(p, x)

    piv: List[RefPivot] = []
    state = 0  # 0 init, +1 seeking high, -1 seeking low
    hs: List[float] = []
    ls: List[float] = []
    cand = cand_bar = None
    opp = opp_bar = None
    for i, k in enumerate(candles):
        a = atr[i]
        if state == 0:
            hs.append(k.h)
            ls.append(k.l)
            if i == 0:
                continue
            lo = min(ls[:-1]); lo_i = ls[:-1].index(lo)
            hi = max(hs[:-1]); hi_i = hs[:-1].index(hi)
            t_lo, t_hi = thr(lo, a), thr(hi, a)
            up = t_lo is not None and k.h - lo >= t_lo
            dn = t_hi is not None and hi - k.l >= t_hi
            if up and dn:
                up, dn = lo_i <= hi_i, hi_i < lo_i
            if up:
                piv.append(RefPivot("L", lo, lo_i, i))
                seg = hs[lo_i + 1:i + 1]; cand = max(seg); cand_bar = lo_i + 1 + seg.index(cand)
                state = 1
                if cand_bar < i:
                    s2 = ls[cand_bar + 1:i + 1]; opp = min(s2); opp_bar = cand_bar + 1 + s2.index(opp)
                else:
                    opp = opp_bar = None
            elif dn:
                piv.append(RefPivot("H", hi, hi_i, i))
                seg = ls[hi_i + 1:i + 1]; cand = min(seg); cand_bar = hi_i + 1 + seg.index(cand)
                state = -1
                if cand_bar < i:
                    s2 = hs[cand_bar + 1:i + 1]; opp = max(s2); opp_bar = cand_bar + 1 + s2.index(opp)
                else:
                    opp = opp_bar = None
            continue
        if state == 1:
            if k.h > cand:
                cand, cand_bar, opp, opp_bar = k.h, i, None, None
                continue
            if opp is None or k.l < opp:
                opp, opp_bar = k.l, i
            t = thr(cand, a)
            if t is not None and cand - opp >= t:
                piv.append(RefPivot("H", cand, cand_bar, i))
                state, cand, cand_bar, opp, opp_bar = -1, opp, opp_bar, None, None
        else:
            if k.l < cand:
                cand, cand_bar, opp, opp_bar = k.l, i, None, None
                continue
            if opp is None or k.h > opp:
                opp, opp_bar = k.h, i
            t = thr(cand, a)
            if t is not None and opp - cand >= t:
                piv.append(RefPivot("L", cand, cand_bar, i))
                state, cand, cand_bar, opp, opp_bar = 1, opp, opp_bar, None, None
    return piv


def label_pivots(piv: List[RefPivot], atr: Sequence[Optional[float]], tol: float = 0.1) -> None:
    last: Dict[str, RefPivot] = {}
    for p in piv:
        prev = last.get(p.kind)
        if prev is not None:
            eps = (atr[p.confirm_bar] or 0.0) * tol
            if p.kind == "H":
                p.label = "HH" if p.price > prev.price + eps else ("LH" if p.price < prev.price - eps else "EQH")
            else:
                p.label = "HL" if p.price > prev.price + eps else ("LL" if p.price < prev.price - eps else "EQL")
        last[p.kind] = p


def trend_at(piv: List[RefPivot], i: int) -> str:
    """Trend from the latest CONFIRMED high label and low label as of bar i."""
    hi = lo = None
    for p in piv:
        if p.confirm_bar > i:
            break
        if p.kind == "H":
            hi = p.label
        else:
            lo = p.label
    if hi is None or lo is None:
        return "UNDEFINED"
    if hi == "HH" and lo == "HL":
        return "BULLISH"
    if hi == "LH" and lo == "LL":
        return "BEARISH"
    return "CONSOLIDATION" if "EQ" in (hi or "") + (lo or "") else "TRANSITION"


# --------------------------------------------------------------------------- zones
@dataclass
class RefZone:
    kind: str  # DEMAND / SUPPLY
    proximal: float
    distal: float
    created: int
    touches: int = 0
    dead_at: Optional[int] = None
    inside: bool = False


def _body_ratio(k: Candle) -> float:
    r = k.h - k.l
    return abs(k.c - k.o) / r if r > 0 else 0.0


def detect_zone(c: Sequence[Candle], i: int, a: Optional[float]) -> Optional[RefZone]:
    if a is None or i < 3:
        return None
    out = c[i]
    if _body_ratio(out) < 0.5 or out.h - out.l < 0.8 * a or _body_ratio(c[i - 1]) > 0.5:
        return None
    s = i - 1
    while s - 1 >= 1 and i - s < 4 and _body_ratio(c[s - 1]) <= 0.5:
        s -= 1
    base = c[s:i]
    if _body_ratio(c[s - 1]) < 0.3:
        return None
    bh, bl = max(k.h for k in base), min(k.l for k in base)
    if bh - bl > 1.6 * a:
        return None
    if out.c > out.o:
        z = RefZone("DEMAND", max(max(k.o, k.c) for k in base), min(bl, out.l), i)
        dep = (out.c - bh) / a
    else:
        z = RefZone("SUPPLY", min(min(k.o, k.c) for k in base), max(bh, out.h), i)
        dep = (bl - out.c) / a
    return z if dep >= 0.6 and z.proximal != z.distal else None


# --------------------------------------------------------------------------- volume profile
def volume_profile(c: Sequence[Candle], start: int, end: int, bins: int = 50, va: float = 0.70) -> Dict:
    w = c[start:end + 1]
    lo, hi = min(k.l for k in w), max(k.h for k in w)
    if hi <= lo:
        hi = lo + max(abs(lo) * 1e-4, 1e-6)
    size = (hi - lo) / bins
    vol = [0.0] * bins
    for k in w:
        if k.v <= 0:
            continue
        if k.h <= k.l:
            vol[min(bins - 1, int((k.c - lo) / size))] += k.v
            continue
        for b in range(bins):
            b_lo = lo + b * size
            ov = min(k.h, b_lo + size) - max(k.l, b_lo)
            if ov > 0:
                vol[b] += k.v * ov / (k.h - k.l)
    peak = max(vol)
    mid = (bins - 1) / 2
    poc = min((b for b in range(bins) if vol[b] == peak), key=lambda b: (abs(b - mid), b))
    a = b = poc
    acc, tot = vol[poc], sum(vol)
    while acc < va * tot and (a > 0 or b < bins - 1):
        up = vol[b + 1] if b < bins - 1 else -1.0
        dn = vol[a - 1] if a > 0 else -1.0
        if up >= dn:
            b += 1; acc += up
        else:
            a -= 1; acc += dn
    return {"poc": lo + (poc + 0.5) * size, "vah": lo + (b + 1) * size, "val": lo + a * size, "volumes": vol}


# --------------------------------------------------------------------------- positioning (expanding percentile)
def positioning_percentile(net_history: Sequence[float]) -> Optional[float]:
    """Percentile of the latest value within ONLY the values seen so far."""
    if len(net_history) < 20:
        return None
    cur = net_history[-1]
    return 100.0 * sum(1 for x in net_history if x <= cur) / len(net_history)


# --------------------------------------------------------------------------- candles
def bullish_confirmation(c: Sequence[Candle], i: int, a: float) -> Optional[str]:
    k, p = c[i], c[i - 1]
    r = k.h - k.l
    if r <= 0 or r < 0.5 * a:
        return None
    body, lower, upper = abs(k.c - k.o), min(k.o, k.c) - k.l, k.h - max(k.o, k.c)
    if p.c < p.o and k.c > k.o and k.o <= p.c and k.c >= p.o and body > abs(p.c - p.o):
        return "BULLISH ENGULFING"
    if lower >= 2 * body and upper <= 0.25 * r and (k.c - k.l) / r >= 0.6:
        return "HAMMER"
    return None


# --------------------------------------------------------------------------- risk
def size_position(equity: float, risk_pct: float, entry: float, stop: float, lot: int = 1,
                  max_pos_pct: float = 1.0, cash: float = float("inf")) -> int:
    if not all(math.isfinite(x) for x in (equity, risk_pct, entry, stop)) or entry <= 0:
        return 0
    rps = abs(entry - stop)
    if rps <= 0:
        return 0
    q = int(math.floor(equity * risk_pct / rps / lot)) * lot
    if q * entry > equity * max_pos_pct:
        q = int(math.floor(equity * max_pos_pct / entry / lot)) * lot
    if q * entry > cash:
        q = int(math.floor(max(cash, 0) / entry / lot)) * lot
    return q if q >= lot else 0


# --------------------------------------------------------------------------- backtest (single symbol, long only)
@dataclass
class RefTrade:
    entry_bar: int
    entry: float
    stop: float
    targets: Tuple[float, float, float]
    qty: int
    left: int
    init_stop: float = 0.0
    hit: List[bool] = field(default_factory=lambda: [False, False, False])
    pnl: float = 0.0
    exit_bar: Optional[int] = None
    reason: str = ""


def run(candles: List[Candle], equity: float = 1_000_000, risk: float = 0.01) -> Dict:
    atr = wilder_atr(candles)
    piv = confirmed_zigzag(candles, atr)
    label_pivots(piv, atr)
    zones: List[RefZone] = []
    trades: List[RefTrade] = []
    open_t: Optional[RefTrade] = None
    pending = None
    for i, k in enumerate(candles):
        a = atr[i]
        # fill pending entry at the open
        if pending is not None and open_t is None:
            stop, zone = pending
            q = size_position(equity, risk, k.o, stop)
            if q and k.o > stop:
                r = k.o - stop
                open_t = RefTrade(i, k.o, stop, (k.o + r, k.o + 2 * r, k.o + 3 * r), q, q, stop)
            pending = None
        # manage trade: stop first on ambiguous bars
        if open_t is not None and i >= open_t.entry_bar:
            t = open_t
            if k.l <= t.stop:
                t.pnl += (t.stop - t.entry) * t.left; t.left = 0; t.exit_bar, t.reason = i, "STOP"
            else:
                for n, (tg, frac) in enumerate(zip(t.targets, (0.3, 0.3, 1.0))):
                    if not t.hit[n] and k.h >= tg:
                        t.hit[n] = True
                        q = t.left if n == 2 else min(t.left, int(t.qty * frac))
                        t.pnl += (tg - t.entry) * q; t.left -= q
                if t.left == 0:
                    t.exit_bar, t.reason = i, "T3"
                else:
                    for p in piv:  # trail only on pivots CONFIRMED this bar, formed after entry
                        if p.confirm_bar == i and p.kind == "L" and p.label == "HL" and p.bar > t.entry_bar:
                            t.stop = max(t.stop, p.price - 0.5 * (a or 0))
            if t.left == 0:
                equity += t.pnl; trades.append(t); open_t = None
        # zone lifecycle, then detection at this bar's close
        for z in zones:
            if z.dead_at is None and i > z.created:
                entered = k.l <= z.proximal if z.kind == "DEMAND" else k.h >= z.proximal
                if entered and not z.inside:
                    z.touches += 1
                z.inside = entered
                if (k.c < z.distal) if z.kind == "DEMAND" else (k.c > z.distal):
                    z.dead_at = i
        nz = detect_zone(candles, i, a)
        if nz:
            zones.append(nz)
        # setup: bullish trend, price in a live demand zone, bullish confirmation candle
        if open_t is None and pending is None and a and i >= 60 and trend_at(piv, i) == "BULLISH":
            for z in reversed(zones):
                if z.kind == "DEMAND" and z.dead_at is None and z.created < i and z.touches <= 2 \
                        and k.l <= z.proximal and k.c >= z.distal and bullish_confirmation(candles, i, a):
                    pending = (z.distal - 0.5 * a, z)
                    break
    rs = [t.pnl / ((t.entry - t.init_stop) * t.qty) for t in trades]
    return {"trades": len(trades), "pivots": len(piv), "zones": len(zones), "final_equity": round(equity, 2),
            "wins": sum(1 for t in trades if t.pnl > 0),
            "avg_r": round(sum(rs) / len(rs), 3) if rs else None, "_r": rs}


def random_walk(n: int = 900, seed: int = 7) -> List[Candle]:
    rng = random.Random(seed)
    px, out = 1000.0, []
    for d in range(n):
        r = rng.gauss(0.0004, 0.012)
        o = px * math.exp(rng.gauss(0, 0.003))
        c = px * math.exp(r)
        h = max(o, c) * math.exp(abs(rng.gauss(0, 0.006)))
        lo = min(o, c) * math.exp(-abs(rng.gauss(0, 0.006)))
        out.append(Candle(str(d), o, h, lo, c, 1e6 * math.exp(rng.gauss(0, 0.3))))
        px = c
    return out


def load_csv(path: str) -> List[Candle]:
    with open(path, newline="") as fh:
        return [Candle(r["date"], float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]),
                       float(r["volume"])) for r in csv.DictReader(fh)]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Reference strategy (Phase A)")
    ap.add_argument("--csv")
    args = ap.parse_args()
    data = load_csv(args.csv) if args.csv else random_walk()
    res = run(data)
    res.pop("_r")
    print(res)
