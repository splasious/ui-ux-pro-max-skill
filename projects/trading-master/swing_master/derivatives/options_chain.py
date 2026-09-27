"""Options chain helpers: ATM selection and strike-window filtering (Section 18)."""
from __future__ import annotations

from typing import List, Optional, Tuple

from ..schemas import OptionChainSnapshot, OptionStrike


def atm_strike(strikes: List[OptionStrike], underlying: float) -> Optional[float]:
    if not strikes:
        return None
    return min(strikes, key=lambda s: (abs(s.strike - underlying), s.strike)).strike


def select_strikes(chain: OptionChainSnapshot, n_each_side: int, min_oi: float = 0.0
                   ) -> Tuple[Optional[float], List[OptionStrike], List[float]]:
    """Return (atm, selected strikes, skipped illiquid strikes).

    Strikes are taken ATM +/- ``n_each_side`` by position in the sorted chain.
    A strike whose call AND put OI are both below ``min_oi`` is treated as
    illiquid and skipped (reported, never silently dropped).
    """
    ordered = sorted(chain.strikes, key=lambda s: s.strike)
    atm = atm_strike(ordered, chain.underlying)
    if atm is None:
        return None, [], []
    k = next(i for i, s in enumerate(ordered) if s.strike == atm)
    window = ordered[max(0, k - n_each_side): k + n_each_side + 1]
    selected, skipped = [], []
    for s in window:
        if s.call_oi < min_oi and s.put_oi < min_oi:
            skipped.append(s.strike)
        else:
            selected.append(s)
    return atm, selected, skipped
