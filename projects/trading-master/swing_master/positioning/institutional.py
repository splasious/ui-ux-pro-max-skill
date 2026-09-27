"""Institutional participant engine (NSE participant-wise OI: FII + DII)."""
from .positioning_score import ParticipantEngine


class InstitutionalEngine(ParticipantEngine):
    category = "INSTITUTIONAL"
    source_hint = "Load NSE participant-wise OI (FII + DII columns) via data/positioning_data.py."
