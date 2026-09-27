"""Derivatives data access: futures OI series and option chains with as-of rules."""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, Optional

from ..derivatives.futures_oi import FuturesOISeries
from ..derivatives.pcr import compute_pcr
from .market_data import MarketDataProvider


class DerivativesContext:
    """Per-symbol derivatives access that never returns data before it was published."""

    def __init__(self, provider: MarketDataProvider, symbol: str, cfg):
        self.provider = provider
        self.symbol = symbol
        self.cfg = cfg
        inst = provider.instrument(symbol)
        self.has_options = inst.has_options
        records = provider.futures_oi(symbol) if inst.has_futures else []
        self.futures = FuturesOISeries(records, cfg.PRICE_CHANGE_THRESHOLD_PCT, cfg.OI_CHANGE_THRESHOLD_PCT) \
            if records else None
        self._pcr_cache: Dict[date, Dict] = {}

    def oi_state(self, as_of: datetime) -> Optional[Dict]:
        if self.futures is None:
            return None
        return self.futures.state_as_of(as_of)

    def pcr(self, trade_date: date, as_of: datetime) -> Optional[Dict]:
        """PCR for ``trade_date`` only if that chain was published by ``as_of``."""
        if not self.has_options:
            return None
        if trade_date not in self._pcr_cache:
            chain = self.provider.option_chain(self.symbol, trade_date)
            info = compute_pcr(chain, self.cfg.PCR_STRIKES_EACH_SIDE, self.cfg.PCR_MIN_STRIKE_OI)
            info["_available_at"] = chain.available_at if chain else None
            self._pcr_cache[trade_date] = info
        info = self._pcr_cache[trade_date]
        if info.get("_available_at") is None or info["_available_at"] > as_of:
            return None
        return {k: v for k, v in info.items() if not k.startswith("_")}
