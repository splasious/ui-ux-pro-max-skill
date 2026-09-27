"""Retail participant engine (NSE participant-wise OI: Client)."""
from .positioning_score import ParticipantEngine


class RetailEngine(ParticipantEngine):
    category = "RETAIL"
    source_hint = "Load NSE participant-wise OI (Client column) via data/positioning_data.py."
