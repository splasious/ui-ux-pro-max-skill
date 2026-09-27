"""Commercial participant engine.

For NSE the closest genuine category is "Pro" (proprietary / trading-member
own account) in the exchange's participant-wise open-interest file.
"""
from .positioning_score import ParticipantEngine


class CommercialEngine(ParticipantEngine):
    category = "COMMERCIAL"
    source_hint = "Load NSE participant-wise OI (Pro column) via data/positioning_data.py."
