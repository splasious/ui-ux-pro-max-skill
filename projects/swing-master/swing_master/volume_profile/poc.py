"""Point of Control and high/low volume nodes."""
from __future__ import annotations

from typing import List, Tuple


def find_poc(volumes: List[float]) -> int:
    """Index of the highest-volume bin.  Ties resolve to the bin nearest the middle."""
    if not volumes:
        raise ValueError("empty profile")
    peak = max(volumes)
    mid = (len(volumes) - 1) / 2.0
    candidates = [k for k, v in enumerate(volumes) if v == peak]
    return min(candidates, key=lambda k: (abs(k - mid), k))


def smooth(volumes: List[float]) -> List[float]:
    n = len(volumes)
    out = []
    for k in range(n):
        lo, hi = max(0, k - 1), min(n, k + 2)
        window = volumes[lo:hi]
        out.append(sum(window) / len(window))
    return out


def volume_nodes(volumes: List[float], hvn_threshold: float, lvn_threshold: float) -> Tuple[List[int], List[int]]:
    """High / low volume nodes = local extrema of the 3-bin smoothed histogram.

    HVN: local maximum >= ``hvn_threshold`` x mean bin volume.
    LVN: local minimum <= ``lvn_threshold`` x mean, ignoring the two outermost
    bins (profile tails are always thin and are not meaningful LVNs).
    """
    n = len(volumes)
    if n < 5:
        return [], []
    s = smooth(volumes)
    mean = sum(s) / n
    hvn, lvn = [], []
    for k in range(1, n - 1):
        if s[k] >= s[k - 1] and s[k] > s[k + 1] and s[k] >= hvn_threshold * mean:
            hvn.append(k)
        if 2 <= k <= n - 3 and s[k] <= s[k - 1] and s[k] < s[k + 1] and s[k] <= lvn_threshold * mean:
            lvn.append(k)
    return hvn, lvn
