from datetime import datetime
from typing import Dict, Optional, Sequence

from ..schemas import PositioningRecord
from .commercial import CommercialEngine
from .institutional import InstitutionalEngine
from .positioning_score import (PositioningSnapshot, classify_percentile, divergence, retail_fraction,
                                smart_money_fraction)
from .retail import RetailEngine


class PositioningSuite:
    """Bundles the three independent engines."""

    def __init__(self, records: Optional[Sequence[PositioningRecord]] = None, min_history: int = 20,
                 bands=(10.0, 30.0, 70.0, 90.0)):
        self.commercial = CommercialEngine(records, min_history, bands)
        self.institutional = InstitutionalEngine(records, min_history, bands)
        self.retail = RetailEngine(records, min_history, bands)

    def snapshot(self, as_of: datetime) -> Dict[str, PositioningSnapshot]:
        return {
            "COMMERCIAL": self.commercial.snapshot(as_of),
            "INSTITUTIONAL": self.institutional.snapshot(as_of),
            "RETAIL": self.retail.snapshot(as_of),
        }


__all__ = ["PositioningSuite", "CommercialEngine", "InstitutionalEngine", "RetailEngine", "PositioningSnapshot",
           "classify_percentile", "divergence", "smart_money_fraction", "retail_fraction"]
