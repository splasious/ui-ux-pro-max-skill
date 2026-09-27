"""Chronological research pipeline: one pass over a symbol's bars.

For each closed bar the analyzer updates, the higher-timeframe tracker is
advanced to that bar's close, and the signal engine evaluates any setup
moment.  The resulting :class:`SymbolDataset` is an immutable record of what
was known at each bar -- the backtester, walk-forward lab and scanner read
from it instead of recomputing (and possibly re-deriving differently).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

from ..data.derivatives import DerivativesContext
from ..data.resampler import resample
from ..schemas import Bar, Instrument
from .analyzer import HTFTracker, SymbolAnalyzer
from .signal_engine import SetupEvaluation, evaluate_bar


@dataclass
class SymbolDataset:
    instrument: Instrument
    timeframe: str
    analyzer: SymbolAnalyzer
    htf: HTFTracker
    derivs: Optional[DerivativesContext]
    evaluations: List[SetupEvaluation]
    date_index: Dict[date, int] = field(default_factory=dict)
    ts_index: Dict = field(default_factory=dict)

    @property
    def symbol(self) -> str:
        return self.instrument.symbol

    @property
    def bars(self) -> List[Bar]:
        return self.analyzer.bars

    def pivots_confirmed_at(self, i: int):
        return self.analyzer.pivots.by_conf_bar.get(i, [])

    def events_at(self, i: int):
        return self.analyzer.events.by_bar.get(i, [])


def analyze_symbol(instrument: Instrument, bars: List[Bar], cfg, positioning, provider=None, timeframe: str = "1D",
                   evaluate: bool = True) -> SymbolDataset:
    htf_tf = cfg.MTF_HIERARCHY.get(timeframe, timeframe)
    htf_bars = resample(bars, timeframe, htf_tf) if htf_tf != timeframe else []
    htf = HTFTracker(instrument.symbol, htf_tf, htf_bars, cfg)
    derivs = DerivativesContext(provider, instrument.symbol, cfg) if provider is not None else None
    an = SymbolAnalyzer(instrument.symbol, timeframe, cfg)
    evaluations: List[SetupEvaluation] = []
    vp_cache: Dict = {}
    for bar in bars:
        an.update(bar)
        htf.advance_to(bar.close_time)
        if evaluate:
            evaluations.extend(evaluate_bar(an, htf, derivs, positioning, instrument, cfg, vp_cache))
            vp_cache.clear()
    ds = SymbolDataset(instrument, timeframe, an, htf, derivs, evaluations)
    for k, b in enumerate(bars):
        ds.date_index.setdefault(b.timestamp.date(), k)
        ds.ts_index[b.timestamp] = k
    return ds
