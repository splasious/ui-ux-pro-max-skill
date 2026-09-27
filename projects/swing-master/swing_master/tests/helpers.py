"""Test fixtures: deterministic bar builders."""
from __future__ import annotations

import math
import random
from datetime import date, timedelta
from typing import List, Sequence, Tuple

from swing_master.data.resampler import session_close, session_open
from swing_master.schemas import Bar


def weekdays(start: date, n: int) -> List[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def bars_from_ohlc(rows: Sequence[Tuple[float, float, float, float]], start: date = date(2024, 1, 1),
                   volume: float = 1000.0) -> List[Bar]:
    days = weekdays(start, len(rows))
    return [Bar(session_open(d), session_close(d), o, h, l, c, volume) for d, (o, h, l, c) in zip(days, rows)]


def bars_from_closes(closes: Sequence[float], start: date = date(2024, 1, 1), spread: float = 0.4) -> List[Bar]:
    rows, prev = [], closes[0]
    for c in closes:
        o = prev
        rows.append((o, max(o, c) + spread, min(o, c) - spread, c))
        prev = c
    return bars_from_ohlc(rows, start)


def random_walk_bars(n: int = 400, seed: int = 3, start: date = date(2023, 1, 2)) -> List[Bar]:
    rng = random.Random(seed)
    px, rows = 1000.0, []
    for _ in range(n):
        o = px * math.exp(rng.gauss(0, 0.003))
        c = px * math.exp(rng.gauss(0.0003, 0.013))
        h = max(o, c) * math.exp(abs(rng.gauss(0, 0.006)))
        lo = min(o, c) * math.exp(-abs(rng.gauss(0, 0.006)))
        rows.append((o, h, lo, c))
        px = c
    days = weekdays(start, n)
    vols = [1e6 * math.exp(rng.gauss(0, 0.3)) for _ in range(n)]
    return [Bar(session_open(d), session_close(d), o, h, l, c, v) for d, (o, h, l, c), v in zip(days, rows, vols)]
