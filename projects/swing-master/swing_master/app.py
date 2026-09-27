"""Platform facade: builds and caches every research artefact the UI needs.

One ``Platform`` holds the provider, the per-symbol datasets (the single
chronological analysis pass), the full-history backtest, the paper-trading
replay, the scanner output and lazily computed labs (ablation, walk-forward).
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .backtest.attribution import attribution
from .backtest.engine import BacktestResult, PortfolioBacktester
from .backtest.metrics import chart_series, compute_metrics
from .backtest.walk_forward import WalkForwardLab
from .config import AppSettings, StrategyConfig
from .config.scoring_config import ABLATION_LADDER, COMPONENTS
from .data.demo import DemoMarketData
from .data.market_data import DataUnavailable, MarketDataProvider
from .data.universe import load_fno_list, select_universe
from .execution.broker_interface import SafeBrokerGateway
from .execution.order_manager import OrderManager
from .execution.paper import PaperBroker
from .logging_utils import clear as clear_logs, log, recent as recent_logs
from .notifications import EVENT_TYPES, NotificationBus, TelegramNotifier
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
    workers = workers if workers is not None else int(os.environ.get("SM_WORKERS", "0") or 0) or (os.cpu_count() or 1)
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
            source = self.settings.DATA_SOURCE.upper()
            if source == "DEMO":
                provider = DemoMarketData(self.settings.DEMO_SEED, self.settings.DEMO_START, self.settings.DEMO_END)
            elif source == "TRADINGMASTER":
                from .data.tradingmaster import from_settings
                provider = from_settings(self.settings)
            elif source == "CSV":
                from .data.historical import CSVMarketData
                provider = CSVMarketData(self.settings.DATA_DIR)
            else:
                raise ValueError(f"SM_DATA_SOURCE must be DEMO, CSV or TRADINGMASTER, got {source!r}")
        self.provider = provider
        self.symbols = symbols
        self.bus = NotificationBus()
        self.notify_events = set(EVENT_TYPES)
        self.telegram = TelegramNotifier(self.settings.TELEGRAM_TOKEN_ENV, self.settings.TELEGRAM_CHAT_ENV)
        self.bus.subscribe(lambda kind, payload: self.telegram(kind, payload) if kind in self.notify_events else None)
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
        self._scan_cache: Dict[str, Dict] = {}
        self._mtf_cache: Dict[str, Dict] = {}
        self.proposal_state: Dict[str, Dict] = {}
        self.persist_state = "idle"
        self.build()

    # ------------------------------------------------------------------ #
    def build(self) -> None:
        with self.lock:
            self.status = "building"
            t0 = time.time()
            records = self.provider.positioning()
            if self.settings.POSITIONING_CSV:
                from .data.positioning_data import load_participant_oi_csv
                records = load_participant_oi_csv(Path(self.settings.POSITIONING_CSV),
                                                  self.cfg.POSITIONING_AVAILABILITY_DELAY_MIN)
            self.positioning = PositioningSuite(records, self.cfg.POSITIONING_MIN_HISTORY, self.cfg.POSITIONING_BANDS)
            fno_list = load_fno_list(Path(self.settings.FNO_LIST)) if self.settings.FNO_LIST else None
            selected, self.universe_info = select_universe(self.provider.universe(), self.settings.UNIVERSE, fno_list)
            self.universe = [i for i in selected if self.symbols is None or i.symbol in self.symbols]
            log("market_data", self.universe_info["label"], source=self.universe_info["source"],
                excluded=len(self.universe_info["excluded"]))
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
            self._scan_cache = {"1D": self.scan}
            self._mtf_cache.clear()
            self.proposal_state.clear()
            self._chart_cache.clear()
            self._ablation = None
            self._walk_forward = None
            self._wf_state = "idle"
            self.built_at = datetime.now()
            self.timings["total_s"] = round(time.time() - t0, 2)
            self.status = "ready"
            clear_logs()
            self._audit_log()
            log("system", "platform ready", **self.timings)
            if self.repo is not None:
                self.persist_state = "running"
                threading.Thread(target=self._persist, daemon=True).start()

    # ------------------------------------------------------------------ #
    def _persist(self) -> None:
        """Section 50: raw data and derived analytics, written off the request path."""
        try:
            t = time.time()
            repo = self.repo
            for inst in self.universe:
                bars = self.provider.daily_bars(inst.symbol)
                repo.save_bars(inst.symbol, "1D", bars, self.provider.source_label)
                repo.save_futures_oi(inst.symbol, self.provider.futures_oi(inst.symbol))
                from .data.resampler import resample
                repo.save_derived_bars(inst.symbol, "1W", resample(bars, "1D", "1W"))
                ds = self.datasets[inst.symbol]
                repo.save_analysis(ds)
                vp = ds.analyzer.profile()
                if vp is not None:
                    repo.save_volume_profile(inst.symbol, "1D", ds.bars[-1].timestamp.isoformat(), vp)
                if inst.has_options:
                    chain = self.provider.option_chain(inst.symbol, bars[-1].timestamp.date())
                    if chain is not None:
                        repo.save_option_snapshot(chain)
            repo.save_positioning(self.positioning.commercial.records + self.positioning.institutional.records
                                  + self.positioning.retail.records)
            repo.save_run("full-history", self.backtest, self.backtest_report["metrics"])
            repo.save_run("paper", self.paper, self.paper_report["metrics"])
            repo.save_orders("paper", self.paper_broker.orders())
            from .journal import chart_snapshot
            for run_id, res in (("full-history", self.backtest), ("paper", self.paper)):
                for tr in list(res.trades) + list(res.open_trades):
                    repo.save_chart_snapshot(run_id, tr.trade_id, "entry_exit", chart_snapshot(self.datasets[tr.symbol], tr))
            repo.save_logs(recent_logs(10_000))
            self.timings["persist_s"] = round(time.time() - t, 2)
            self.persist_state = "done"
        except Exception as exc:  # reported on the Data Health screen
            self.persist_state = f"error: {exc}"
            log("error", f"persistence failed: {exc}")

    def _audit_log(self) -> None:
        """Section 57: structured, auditable events for the paper-session window."""
        start = self.paper.start
        rows = []
        for ds in self.datasets.values():
            an, sym = ds.analyzer, ds.symbol
            for p in an.pivots.pivots:
                if p.confirmation_timestamp >= start:
                    rows.append(("pivot", p.confirmation_timestamp, f"{sym} {p.label or p.pivot_type} {p.pivot_price:.2f} confirmed",
                                 {"symbol": sym, "pivot_time": p.pivot_timestamp.isoformat(), "bars_to_confirm": p.confirmation_bar - p.pivot_bar}))
            for e in an.events.events:
                if e.event_timestamp >= start:
                    rows.append(("structure", e.event_timestamp, f"{sym} {e.direction.lower()} {e.event_type} through {e.level:.2f}",
                                 {"symbol": sym, "previous": e.previous_structure, "current": e.current_structure}))
            for z in an.zones.zones:
                if z.creation_timestamp >= start:
                    rows.append(("zone", z.creation_timestamp, f"{sym} {z.zone_type.lower()} {z.pattern} created {z.proximal:.2f}-{z.distal:.2f}",
                                 {"symbol": sym, "zone_id": z.zone_id}))
                for tb in z.touches:
                    if an.bars[tb].close_time >= start:
                        rows.append(("zone", an.bars[tb].close_time, f"{sym} {z.zone_type.lower()} {z.pattern} touched", {"zone_id": z.zone_id}))
                if z.invalidation_timestamp and z.invalidation_timestamp >= start:
                    rows.append(("zone", z.invalidation_timestamp, f"{sym} {z.zone_type.lower()} {z.pattern} invalidated", {"zone_id": z.zone_id}))
        for s in self.paper.signals:
            rows.append(("signal", datetime.fromisoformat(s["time"]).replace(hour=15, minute=30),
                         f"{s['symbol']} {s['direction']} {s['status'].lower()} score {s['score']}",
                         {"reason": s["reason"], "eval_id": s["eval_id"]}))
        kinds = {"TRADE_TRIGGERED": "execution", "SL_MODIFIED": "stop", "TRAILING_SL_CHANGED": "stop", "T1_HIT": "target",
                 "T2_HIT": "target", "T3_HIT": "target", "POSITION_CLOSED": "execution", "RISK_LIMIT_REACHED": "risk"}
        for e in self.paper.events:
            if e["type"] in kinds:
                rows.append((kinds[e["type"]], datetime.fromisoformat(e["time"]),
                             f"{e.get('symbol', '')} {e['type'].replace('_', ' ').lower()}".strip(),
                             {k: v for k, v in e.items() if k not in ("type", "time")}))
        for o in self.order_manager.log:
            if o["action"] in ("PLACE", "FILL", "CANCEL", "EXPIRE"):
                rows.append(("order", None, f"{o.get('symbol', '')} {o['action'].lower()} {o.get('qty', '')}".strip(),
                             {k: v for k, v in o.items() if k != "action"}))
        rows.sort(key=lambda r: r[1] or start)
        for cat, when, msg, data in rows[-5000:]:
            log(cat, msg, at=when.isoformat(timespec="seconds") if when else None, **data)
        log("market_data", f"{len(self.datasets)} symbols loaded from {self.provider.source_label}",
            at=self.as_of.isoformat(timespec="seconds"))

    # ------------------------------------------------------------------ #
    def scan_tf(self, tf: str) -> Dict:
        """Scanner on another timeframe (Section 28).  Intraday frames are computed on demand."""
        if tf not in self._scan_cache:
            sets = {i.symbol: self.dataset(i.symbol, tf) for i in self.universe if i.tradable}
            self._scan_cache[tf] = scan(sets, self.cfg, [])
        return self._scan_cache[tf]

    def mtf_context(self, symbol: str) -> Dict:
        """Section 4 hierarchy: Weekly macro -> Daily structure -> 4H setup -> 1H entry refinement."""
        if symbol in self._mtf_cache:
            return self._mtf_cache[symbol]
        from .indicators.utilities import volatility_profile
        roles = [("1M", "Long-term context"), ("1W", "Macro context"), ("1D", "Main swing structure"),
                 ("4H", "Setup"), ("1H", "Entry refinement")]
        rows = []
        for tf, role in roles:
            try:
                ds = self.dataset(symbol, tf)
            except DataUnavailable as exc:
                rows.append({"timeframe": tf, "role": role, "available": False, "reason": str(exc)})
                continue
            an = ds.analyzer
            lp, le = an.pivots.last(an.i), an.events.last_event(an.i)
            rows.append({
                "timeframe": tf, "role": role, "available": True, "trend": an.structure.trend,
                "close": an.bars[-1].close, "as_of": an.bars[-1].close_time.isoformat(),
                "last_pivot": None if lp is None else {"label": lp.label or lp.pivot_type, "price": round(lp.pivot_price, 2),
                                                       "confirmed": lp.confirmation_timestamp.isoformat()},
                "last_event": None if le is None else f"{le.direction.title()} {'CHoCH' if le.event_type == 'CHOCH' else 'BOS'}",
                "volatility": volatility_profile(an.atr_values, [b.close for b in an.bars], self.cfg.ATR_PERCENTILE_LOOKBACK),
                "bars": len(an.bars),
            })
        trends = [r["trend"] for r in rows if r.get("available") and r["timeframe"] in ("1W", "1D", "4H", "1H")]
        bull, bear = trends.count("BULLISH"), trends.count("BEARISH")
        verdict = ("ALIGNED BULLISH" if bull == len(trends) and trends else "ALIGNED BEARISH" if bear == len(trends) and trends
                   else "MOSTLY BULLISH" if bull > bear else "MOSTLY BEARISH" if bear > bull else "MIXED")
        out = {"symbol": symbol, "rows": rows, "verdict": verdict, "bullish": bull, "bearish": bear, "count": len(trends)}
        self._mtf_cache[symbol] = out
        return out

    def proposals(self) -> Dict:
        """Section 48: the system proposes, the user confirms (SEMI_AUTO) -- analysis only in MANUAL."""
        items = []
        for r in self.scan["rows"]:
            if r["status"] not in ("READY", "WAIT"):
                continue
            pid = f"{r['symbol']}-{r['direction']}-{self.as_of.date().isoformat()}"
            st = self.proposal_state.get(pid, {})
            ready = r["status"] == "READY"
            items.append({"id": pid, "symbol": r["symbol"], "direction": r["direction"], "scanner_status": r["status"],
                          "entry": r.get("entry"), "stop": r.get("stop"), "t1": r.get("t1"), "t2": r.get("t2"), "t3": r.get("t3"),
                          "score": r.get("confluence"), "reason": r.get("reason"),
                          "status": st.get("status") or ("PROPOSED" if ready else "WAITING FOR CONFIRMATION CANDLE"),
                          "order_id": st.get("order_id"), "confirmable": ready and self.execution_mode == "SEMI_AUTO"
                          and not st})
        history = [dict(v) for v in self.order_manager.proposals.values()][-40:][::-1]
        return {"mode": self.execution_mode, "items": items, "history": history,
                "help": {"MANUAL": "Analysis only: proposals are listed, nothing is sent.",
                         "SEMI_AUTO": "Confirm a READY proposal to send it to the paper broker.",
                         "PAPER": "READY setups are sent automatically at the next open.",
                         "BACKTEST": "Simulation only.", "AUTO": "Live broker execution (locked)."}[self.execution_mode]}

    def decide_proposal(self, pid: str, accept: bool) -> Dict:
        props = {p["id"]: p for p in self.proposals()["items"]}
        if pid not in props:
            raise KeyError(pid)
        p = props[pid]
        if not accept:
            self.proposal_state[pid] = {"status": "REJECTED BY USER"}
            log("order", f"{p['symbol']} proposal rejected by user")
            return self.proposals()
        if not p["confirmable"]:
            raise PermissionError("Only READY proposals can be confirmed, and only in SEMI_AUTO mode")
        from .execution.broker_interface import OrderRequest
        from .risk.position_size import position_size
        equity = self.paper.equity_curve[-1]["equity"] if self.paper.equity_curve else self.cfg.INITIAL_CAPITAL
        size = position_size(equity, self.cfg.RISK_PER_TRADE, p["entry"], p["stop"],
                             self.provider.instrument(p["symbol"]).lot_size, self.cfg.MAX_POSITION_PERCENT, equity)
        if not size.valid:
            raise PermissionError("Risk engine rejected the size: " + "; ".join(size.reasons))
        rec = self.order_manager.gateway.submit(OrderRequest(p["symbol"], "BUY" if p["direction"] == "LONG" else "SELL",
                                                             size.quantity, client_id=pid, tag="SM-SEMI"))
        self.proposal_state[pid] = {"status": "SENT", "order_id": rec.order_id}
        log("order", f"{p['symbol']} proposal confirmed -> {rec.order_id}", qty=size.quantity)
        return self.proposals()

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
                    # only COMPLETED periods: a forming week/month is never analysed as if it had closed
                    bars = [b for b in resample(self.provider.daily_bars(symbol), "1D", timeframe)
                            if b.close_time <= self.as_of]
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
