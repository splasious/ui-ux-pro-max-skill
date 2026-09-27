"""Participant positioning loader (Sections 13 & 16).

Source: NSE "participant wise open interest" daily file, which genuinely
classifies futures & options open interest by participant type:

    Client -> RETAIL      FII + DII -> INSTITUTIONAL      Pro -> COMMERCIAL

Because the exchange itself labels the categories, records loaded from that
file are ``DIRECT``.  They describe index-futures positioning for the whole
market, so they are market-wide context (not stock specific).

Release-time integrity: NSE publishes the file after the close.  Each record
stores the trading date (``position_period``), a conservative
``publication_timestamp`` (20:00 IST on that date) and
``available_to_strategy_timestamp`` (publication + configured processing
delay).  The engine only reads records whose availability time has passed.

Expected CSV columns (one row per date and participant)::

    date,participant,future_index_long,future_index_short
"""
from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List

from ..schemas import Availability, PositioningRecord

PARTICIPANT_MAP = {"CLIENT": "RETAIL", "FII": "INSTITUTIONAL", "DII": "INSTITUTIONAL", "PRO": "COMMERCIAL"}
PUBLICATION_TIME = (20, 0)


def load_participant_oi_csv(path: Path, availability_delay_min: int = 120) -> List[PositioningRecord]:
    agg = {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            participant = (row.get("participant") or "").strip().upper()
            if participant not in PARTICIPANT_MAP:
                continue
            d = date.fromisoformat(row["date"][:10])
            cat = PARTICIPANT_MAP[participant]
            lo = float(row["future_index_long"])
            sh = float(row["future_index_short"])
            cur = agg.setdefault((d, cat), [0.0, 0.0])
            cur[0] += lo
            cur[1] += sh
    out = []
    for (d, cat), (lo, sh) in sorted(agg.items()):
        pub = datetime(d.year, d.month, d.day, *PUBLICATION_TIME)
        out.append(PositioningRecord(cat, d, pub, pub + timedelta(minutes=availability_delay_min), lo, sh,
                                     "NSE participant-wise OI", Availability.DIRECT))
    return out
