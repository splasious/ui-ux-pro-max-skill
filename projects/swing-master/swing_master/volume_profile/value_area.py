"""Value area (VAH / VAL) around the POC."""
from __future__ import annotations

from typing import List, Tuple


def value_area(volumes: List[float], poc_index: int, percent: float = 0.70) -> Tuple[int, int]:
    """Expand from the POC one bin at a time toward the side with more volume
    until ``percent`` of total volume is enclosed.  Returns (low_bin, high_bin).
    Ties expand upward first so results are deterministic.
    """
    total = sum(volumes)
    if total <= 0:
        return poc_index, poc_index
    lo = hi = poc_index
    acc = volumes[poc_index]
    n = len(volumes)
    while acc < percent * total and (lo > 0 or hi < n - 1):
        up = volumes[hi + 1] if hi < n - 1 else -1.0
        dn = volumes[lo - 1] if lo > 0 else -1.0
        if up >= dn:
            hi += 1
            acc += up
        else:
            lo -= 1
            acc += dn
    return lo, hi
