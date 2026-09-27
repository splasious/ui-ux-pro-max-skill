"""Trading-universe selection.

Swing Master trades NSE F&O underlyings only (``SM_UNIVERSE=FNO``, the
default).  A stock is eligible when it has exchange-traded stock futures,
which on NSE always come with stock options.  Index underlyings with futures
(NIFTY, BANKNIFTY, ...) stay in as market-context anchors.

Membership comes from, in order of precedence:

1. ``SM_FNO_LIST``: a file with the current F&O list.  NSE's
   ``fo_mktlots.csv`` works as-is (the lot size of the nearest listed month is
   taken); so does any CSV with a ``SYMBOL`` column, or a plain text file with
   one symbol per line.
2. The data source's instrument master (``has_futures``).

``SM_UNIVERSE=ALL`` disables the filter.
"""
from __future__ import annotations

import csv
import dataclasses
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..schemas import Instrument

UNIVERSE_MODES = ("FNO", "ALL")


def load_fno_list(path: Path) -> Dict[str, Optional[int]]:
    """Return ``{symbol: lot_size or None}`` from an F&O list file."""
    text = Path(path).read_text(encoding="utf-8-sig")
    rows = [[c.strip() for c in r] for r in csv.reader(text.splitlines()) if any(c.strip() for c in r)]
    if not rows:
        return {}
    header = [c.upper() for c in rows[0]]
    out: Dict[str, Optional[int]] = {}
    if "SYMBOL" in header:
        col = header.index("SYMBOL")
        for r in rows[1:]:
            if len(r) <= col or not r[col] or r[col].upper() == "SYMBOL":
                continue  # NSE's file repeats its header before each section
            lot = next((int(float(c)) for c in r[col + 1:] if _is_number(c)), None)
            out[r[col].upper()] = lot
    else:
        for r in rows:
            out[r[0].upper()] = int(float(r[1])) if len(r) > 1 and _is_number(r[1]) else None
    return out


def _is_number(s: str) -> bool:
    try:
        return float(s) > 0
    except ValueError:
        return False


def select_universe(instruments: List[Instrument], mode: str = "FNO",
                    fno_list: Optional[Dict[str, Optional[int]]] = None) -> Tuple[List[Instrument], Dict]:
    """Filter ``instruments`` to the configured universe; also return a summary for the UI."""
    mode = (mode or "FNO").upper()
    if mode not in UNIVERSE_MODES:
        raise ValueError(f"SM_UNIVERSE must be one of {UNIVERSE_MODES}, got {mode!r}")
    kept: List[Instrument] = []
    excluded: List[str] = []
    for inst in instruments:
        if mode == "ALL":
            kept.append(inst)
        elif inst.is_index:
            if inst.has_futures:
                kept.append(inst)
            else:
                excluded.append(inst.symbol)
        elif fno_list is not None:
            if inst.symbol.upper() in fno_list:
                lot = fno_list[inst.symbol.upper()]
                kept.append(dataclasses.replace(inst, has_futures=True, lot_size=lot or inst.lot_size))
            else:
                excluded.append(inst.symbol)
        elif inst.has_futures:
            kept.append(inst)
        else:
            excluded.append(inst.symbol)
    stocks = sum(1 for i in kept if not i.is_index)
    indices = len(kept) - stocks
    if mode == "ALL":
        label, source = f"All instruments: {stocks} stocks + {indices} indices", "no filter"
    else:
        label = f"NSE F&O: {stocks} stocks + {indices} indices"
        source = "F&O list file" if fno_list is not None else "instrument master (stocks with futures)"
    missing = sorted(set(fno_list or {}) - {i.symbol.upper() for i in instruments}) if mode == "FNO" else []
    return kept, {"mode": mode, "label": label, "source": source, "stocks": stocks, "indices": indices,
                  "excluded": excluded, "missing_data": missing}
