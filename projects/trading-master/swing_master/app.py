"""Platform facade: builds and caches every research artefact the UI needs.

One ``Platform`` holds the provider, the per-symbol datasets (the single
chronological analysis pass), the full-history backtest, the paper-trading
replay, the scanner output and lazily computed labs (ablation, walk-forward).
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .backtest.attribution import attribution
from .backtest.engine import BacktestResult, PortfolioBacktester
from .backtest.metrics import chart_series, compute_metrics
from .backtest.walk_forward import WalkForwardLab
from .config import AppSettings, StrategyConfig
from .config.scoring_config import ABLATION_LADDER, COMPONENTS
from .data.demo import DemoMarketData
from .data.market_data import DataUnavailable, MarketDataProvider
from .execution.broker_interface import SafeBrokerGateway
from .execution.order_manager import OrderManager
from .execution.paper import PaperBroker
from .logging_utils import log
from .notifications import NotificationBus, TelegramNotifier
from .positioning import PositioningSuite
from .scanner import scan
from .strategy.pipeline import SymbolDataset, analyze_symbol

INTRADAY_SESSIONS = {"4H": 200, "1H": 90, "15m": 25, "5m": 8}

_WORKER: Dict = {}


def _analyze_worker(symbol: str) -> SymbolDataset:
    """Runs in a forked worker; the provider reference is stripped before pickling back."""
    prov, cfg, pos = _WORKER["provider"], _WORKER["cfg"], _WORKER["positioning"]
    ds = analyze_symbol(prov.instrument(symbol), prov.daily_bars(symbol), cfg, pos, prov)
    if ds.derivs is not None:
        ds.derivs.provider = None
    return ds


def analyze_universe(provider, instruments, cfg, positioning, workers: Optional[int] = None) -> Dict[str, SymbolDataset]:
    """One chronological pass per symbol, in parallel where the OS supports fork."""
    import multiprocessing
    import os
    workers = workers if workers is not None else int(os.environ.get("TM_WORKERS", "0") or 0) or (os.cpu_count() or 1)
    symbols = [i.symbol for i in instruments]
    if workers > 1 and len(symbols) > 4 and "fork" in multiprocessing.get_all_start_methods():
        from concurrent.futures import ProcessPoolExecutor
        _WORKER.update(provider=provider, cfg=cfg, positioning=positioning)
        try:
            with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("fork")) as ex:
                results = list(ex.map(_analyze_worker, symbols, chunksize=2))
        finally:
            _WORKER.clear()
        for ds in results:
            if ds.derivs is not None:
                ds.derivs.provider = provider
        return {ds.symbol: ds for ds in results}
    return {i.symbol: analyze_symbol(i, provider.daily_bars(i.symbol), cfg, positioning, provider) for i in instruments}


class Platform:
    def __init__(self, settings: Optional[AppSettings] = None, cfg: Optional[StrategyConfig] = None,
                 provider: Optional[MarketDataProvider] = None, persist: bool = True, symbols: Optional[List[str]] = None):
        self.settings = settings or AppSettings()
        self.cfg = cfg or StrategyConfig()
        self.cfg.validate()
        if provider is None:
            if self.settings.is_demo:
                provider = DemoMarketData(self.settings.DEMO_SEED, self.settings.DEMO_START, self.settings.DEMO_END)
            else:
                from .data.historical import CSVMarketData
                provider = CSVMarketData(self.settings.DATA_DIR)
        self.provider = provider
        self.symbols = symbols
        self.bus = NotificationBus()
        self.telegram = TelegramNotifier(self.settings.TELEGRAM_TOKEN_ENV, self.settings.TELEGRAM_CHAT_ENV)
        self.bus.subscribe(self.telegram)
        self.repo = None
        if persist:
            try:
                from .database import Repository
                self.repo = Repository(self.settings.raw_db_path, self.settings.analytics_db_path)
            except Exception as exc:  # the UI reports the database as DOWN; nothing is hidden
                log("error", f"database unavailable: {exc}")
        self.lock = threading.RLock()
        self.status = "building"
        self.timings: Dict[str, float] = {}
        self._chart_cache: Dict[Tuple[str, str], SymbolDataset] = {}
        self._ablation: Optional[List[Dict]] = None
        self._walk_forward: Optional[Dict] = None
        self._wf_state = "idle"
        self.custom_backtest: Optional[Dict] = None
        self.execution_mode = self.settings.EXECUTION_MODE
        self.build()

    # ------------------------------------------------------------------ #
    def build(self) -> None:
        with self.lock:
            self.status = "building"
            t0 = time.time()
            records = self.provider.positioning()
            if self.settings.POSITIONING_CSV:
                from pathlib import Path
                from .data.positioning_data import load_participant_oi_csv
                records = load_participant_oi_csv(Path(self.settings.POSITIONING_CSV),
                                                  self.cfg.POSITIONING_AVAILABILITY_DELAY_MIN)
            self.positioning = PositioningSuite(records, self.cfg.POSITIONING_MIN_HISTORY, self.cfg.POSITIONING_BANDS)
            self.universe = [i for i in self.provider.universe() if self.symbols is None or i.symbol in self.symbols]
            self.datasets: Dict[str, SymbolDataset] = analyze_universe(self.provider, self.universe, self.cfg,
                                                                       self.positioning)
            self.timings["analysis_s"] = round(time.time() - t0, 2)
            log("system", "analysis complete", symbols=len(self.datasets), seconds=self.timings["analysis_s"])

            t1 = time.time()
            self.backtest = PortfolioBacktester(self.datasets, self.cfg, label="Full history").run()
            self.backtest_report = self.report(self.backtest)
            self.timings["backtest_s"] = round(time.time() - t1, 2)

            t2 = time.time()
            self.paper_broker = PaperBroker()
            gateway = SafeBrokerGateway(self.paper_broker, self.cfg.MAX_DAILY_LOSS * self.cfg.INITIAL_CAPITAL,
                                        self.cfg.MAX_PORTFOLIO_RISK * self.cfg.INITIAL_CAPITAL * 10,
                                        rate_per_sec=1e6, burst=10 ** 6)
            self.order_manager = OrderManager("PAPER", gateway)
            anchor = self._anchor_symbol()
            start = self.datasets[anchor].bars[-self.settings.PAPER_REPLAY_BARS].timestamp
            self.paper = PortfolioBacktester(self.datasets, self.cfg, start=start, label="Paper session",
                                             on_event=self.bus.publish, order_sink=self.order_manager).run()
            self.paper_report = self.report(self.paper, with_attribution=False)
            self.timings["paper_s"] = round(time.time() - t2, 2)

            self.scan = scan(self.datasets, self.cfg, self.paper.open_trades)
            self._chart_cache.clear()
            self._ablation = None
            self._walk_forward = None
            self._wf_state = "idle"
            self.built_at = datetime.now()
            self.timings["total_s"] = round(time.time() - t0, 2)
            self.status = "ready"
            log("system", "platform ready", **self.timings)
            if self.repo is not None:
                try:
                    self.repo.save_run("full-history", self.backtest, self.backtest_report["metrics"])
                    self.repo.save_run("paper", self.paper, self.paper_report["metrics"])
                    self.repo.save_orders("paper", self.paper_broker.orders())
                    for ds in self.datasets.values():
                        self.repo.save_analysis(ds)
                except Exception as exc:
                    log("error", f"persistence failed: {exc}")

    def _anchor_symbol(self) -> str:
        return "NIFTY" if "NIFTY" in self.datasets else next(iter(self.datasets))

    def report(self, result: BacktestResult, with_attribution: bool = True) -> Dict:
        m = compute_metrics(result.trades, result.equity_curve, result.initial_capital, result.open_trades)
        out = {"metrics": m, "charts": chart_series(result.trades, result.equity_curve)}
        if with_attribution:
            out["attribution"] = attribution(result.trades)
        result.metrics = m
        return out

    # ------------------------------------------------------------------ #
    def reconfigure(self, overrides: Dict) -> StrategyConfig:
        new_cfg = self.cfg.with_overrides(**overrides)
        self.cfg = new_cfg
        self.build()
        return new_cfg

    def run_backtest(self, enabled_components: List[str], overrides: Dict) -> Dict:
        cfg = self.cfg.with_overrides(**overrides) if overrides else self.cfg
        if cfg.analysis_key() != self.cfg.analysis_key():
            raise ValueError("Parameters that change the analysis must be applied from Settings (full rebuild)")
        disabled = [c for c in COMPONENTS if c not in enabled_components]
        res = PortfolioBacktester(self.datasets, cfg, disabled, label="Custom run").run()
        rep = self.report(res)
        self.custom_backtest = {"result": res, "report": rep, "disabled": disabled, "overrides": overrides}
        return self.custom_backtest

    def ablation(self) -> List[Dict]:
        with self.lock:
            if self._ablation is None:
                rows = []
                for label, enabled in ABLATION_LADDER:
                    disabled = [c for c in COMPONENTS if c not in enabled]
                    res = PortfolioBacktester(self.datasets, self.cfg, disabled, label=label,
                                              record_rejections=False).run()
                    m = compute_metrics(res.trades, res.equity_curve, res.initial_capital, res.open_trades)
                    rows.append({"label": label, "enabled": enabled, "metrics": m})
                self._ablation = rows
            return self._ablation

    def walk_forward(self, background: bool = True) -> Dict:
        if self._walk_forward is not None:
            return {"state": "done", **self._walk_forward}
        if self._wf_state == "running":
            return {"state": "running"}

        def job():
            try:
                t = time.time()
                self._walk_forward = WalkForwardLab(self.datasets, self.cfg).run()
                self.timings["walk_forward_s"] = round(time.time() - t, 2)
                self._wf_state = "done"
            except Exception as exc:  # surfaced to the UI, never swallowed
                self._wf_state = f"error: {exc}"
                log("error", f"walk-forward failed: {exc}")

        self._wf_state = "running"
        if background:
            threading.Thread(target=job, daemon=True).start()
            return {"state": "running"}
        job()
        return {"state": self._wf_state, **(self._walk_forward or {})}

    # ------------------------------------------------------------------ #
    def dataset(self, symbol: str, timeframe: str = "1D") -> SymbolDataset:
        if symbol not in self.datasets:
            raise KeyError(symbol)
        if timeframe == "1D":
            return self.datasets[symbol]
        key = (symbol, timeframe)
        with self.lock:
            if key not in self._chart_cache:
                inst = self.provider.instrument(symbol)
                if timeframe in ("1W", "1M"):
                    from .data.resampler import resample
                    bars = resample(self.provider.daily_bars(symbol), "1D", timeframe)
                elif timeframe in INTRADAY_SESSIONS:
                    bars = self.provider.intraday_bars(symbol, timeframe, INTRADAY_SESSIONS[timeframe])
                else:
                    raise DataUnavailable(timeframe)
                self._chart_cache[key] = analyze_symbol(inst, bars, self.cfg, self.positioning, self.provider,
                                                        timeframe=timeframe)
            return self._chart_cache[key]

    @property
    def as_of(self) -> datetime:
        return self.provider.as_of()
