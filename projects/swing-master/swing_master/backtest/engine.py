"""Event-driven portfolio backtester (Section 11 of the workflow).

Timeline loop, for every bar timestamp across the universe:

    1. fill pending entry orders at this bar's open (gap policy applied)
    2. advance open trades through the bar (TradeManager -- conservative)
    3. at the close, run ``decide()`` on setup evaluations from this bar,
       pass survivors through the portfolio risk engine, queue orders
    4. mark the portfolio to market

Decisions on bar ``t`` can only produce fills on bar ``t+1`` (or at ``t``'s
close in REVERSAL_CLOSE mode), so no trade is ever entered retrospectively.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, Iterable, List, Optional

from ..risk.portfolio_risk import PortfolioRiskManager, open_risk
from ..risk.position_size import position_size
from ..strategy.pipeline import SymbolDataset
from ..strategy.signal_engine import SetupEvaluation, decide, trigger_applicable
from ..strategy.trade_manager import Trade, TradeManager
from .execution_model import ExecutionModel


@dataclass
class PendingOrder:
    ev: SetupEvaluation
    symbol: str
    sector: str
    direction: str
    created_ts: datetime
    bars_left: int
    planned_qty: int
    position_value: float
    risk_amount: float
    decision: Dict


@dataclass
class BacktestResult:
    label: str
    config: Dict
    disabled: List[str]
    start: Optional[datetime]
    end: Optional[datetime]
    trades: List[Trade]
    open_trades: List[Trade]
    equity_curve: List[Dict]
    signals: List[Dict]
    rejected: List[Dict]
    events: List[Dict]
    initial_capital: float
    metrics: Dict = field(default_factory=dict)


class PortfolioBacktester:
    def __init__(self, datasets: Dict[str, SymbolDataset], cfg, disabled: Iterable[str] = (), start=None, end=None,
                 label: str = "Backtest", force_close_at_end: bool = False,
                 on_event: Optional[Callable[[str, Dict], None]] = None,
                 order_sink: Optional[Callable[[str, Dict], None]] = None, record_rejections: bool = True):
        self.datasets = datasets
        self.cfg = cfg
        self.disabled = sorted(set(disabled))
        self.start, self.end = start, end
        self.label = label
        self.force_close_at_end = force_close_at_end
        self.on_event = on_event or (lambda kind, payload: None)
        self.order_sink = order_sink or (lambda action, payload: None)
        self.record_rejections = record_rejections
        self.execution = ExecutionModel(cfg)
        self.manager = TradeManager(cfg, self.execution)
        self.risk = PortfolioRiskManager(cfg)

    # ------------------------------------------------------------------ #
    def run(self) -> BacktestResult:
        cfg = self.cfg
        timeline = sorted({b.timestamp for ds in self.datasets.values() for b in ds.bars
                           if (self.start is None or b.timestamp >= self.start)
                           and (self.end is None or b.timestamp <= self.end)})
        evals_by_ts: Dict[datetime, List[SetupEvaluation]] = {}
        for ds in self.datasets.values():
            for ev in ds.evaluations:
                evals_by_ts.setdefault(ev.timestamp, []).append(ev)

        realized = 0.0
        positions: List[Trade] = []
        closed: List[Trade] = []
        pending: List[PendingOrder] = []
        equity_curve: List[Dict] = []
        signals: List[Dict] = []
        rejected: List[Dict] = []
        events: List[Dict] = []
        peak = cfg.INITIAL_CAPITAL
        prev_equity = cfg.INITIAL_CAPITAL
        seq = 0
        halted = False
        last_price: Dict[str, float] = {}

        def equity_now() -> float:
            unreal = sum(t.gross_pnl - t.costs + t.unrealized(last_price.get(t.symbol, t.entry)) for t in positions)
            return cfg.INITIAL_CAPITAL + realized + unreal

        def log_event(kind: str, payload: Dict):
            events.append({"type": kind, **payload})
            self.on_event(kind, payload)

        for ts in timeline:
            # ---------------- 1. pending entries at the open ---------------
            still: List[PendingOrder] = []
            for po in pending:
                ds = self.datasets[po.symbol]
                i = ds.ts_index.get(ts)
                if i is None:
                    still.append(po)
                    continue
                bar = ds.bars[i]
                fill = self._entry_price(po, bar)
                if fill is None:
                    po.bars_left -= 1
                    if po.bars_left > 0:
                        still.append(po)
                    else:
                        self._reject(rejected, po.ev, po.decision, "ORDER EXPIRED: entry trigger not reached", ts)
                        self.order_sink("EXPIRE", {"eval_id": po.ev.eval_id, "symbol": po.symbol})
                    continue
                t = self._try_fill(po, fill, i, bar, ts, equity_now(), positions, rejected, seq)
                if t is not None:
                    seq += 1
                    positions.append(t)
                    last_price[t.symbol] = fill
                    log_event("TRADE_TRIGGERED", {"time": ts.isoformat(), "symbol": t.symbol, "trade_id": t.trade_id,
                                                  "direction": t.direction, "price": round(fill, 2), "qty": t.quantity})
            pending = still

            # ---------------- 2. manage open trades ----------------------
            for t in list(positions):
                ds = self.datasets[t.symbol]
                i = ds.ts_index.get(ts)
                if i is None:
                    continue
                if cfg.ENTRY_MODE == "REVERSAL_CLOSE" and i == t.entry_bar:
                    continue
                bar = ds.bars[i]
                evs = self.manager.on_bar(t, i, bar, ds.pivots_confirmed_at(i), ds.events_at(i), ds.analyzer.atr_values[i])
                last_price[t.symbol] = bar.close if t.status == "OPEN" else t.exit_price
                for e in evs:
                    kind = {"SL_MODIFIED": "SL_MODIFIED", "TRAIL_MOVED": "TRAILING_SL_CHANGED"}.get(e["type"], e["type"])
                    if kind in ("T1_HIT", "T2_HIT", "T3_HIT", "SL_MODIFIED", "TRAILING_SL_CHANGED"):
                        log_event(kind, {"time": ts.isoformat(), "symbol": t.symbol, "trade_id": t.trade_id, **e})
                    self.order_sink("TRADE_EVENT", {"trade_id": t.trade_id, "symbol": t.symbol, **e})
                if t.status == "CLOSED":
                    positions.remove(t)
                    closed.append(t)
                    realized += t.net_pnl
                    log_event("POSITION_CLOSED", {"time": ts.isoformat(), "symbol": t.symbol, "trade_id": t.trade_id,
                                                  "reason": t.exit_reason, "net_pnl": round(t.net_pnl, 2),
                                                  "r": round(t.r_multiple() or 0.0, 2)})

            # ---------------- 3. decisions at the close -------------------
            equity = equity_now()
            day_pnl = equity - prev_equity
            todays = evals_by_ts.get(ts, [])
            scored = []
            for ev in todays:
                if not trigger_applicable(ev, self.disabled):
                    continue
                d = decide(ev, cfg, self.disabled)
                if d["status"] == "NOT_APPLICABLE":
                    continue
                scored.append((d["confluence"]["score"], ev, d))
            scored.sort(key=lambda x: -x[0])
            for score, ev, d in (scored if not halted else []):
                sig = {"eval_id": ev.eval_id, "time": ev.timestamp.isoformat(), "symbol": ev.symbol,
                       "direction": ev.direction, "trigger": ev.trigger, "score": round(score, 1),
                       "zone_score": d["zone_score"]["score"], "status": d["status"], "reason": d["reason"]}
                if not d["accepted"]:
                    signals.append(sig)
                    self._reject(rejected, ev, d, d["reason"], ts)
                    continue
                cash = equity - sum(p.position_value for p in positions)
                risk = self.risk.evaluate(equity=equity, cash=cash, positions=positions, pending=pending,
                                          symbol=ev.symbol, sector=ev.sector, direction=ev.direction,
                                          entry=ev.entry_ref, stop=ev.stop, lot_size=ev.lot_size, day_pnl=day_pnl)
                if not risk["approved"]:
                    sig["status"], sig["reason"] = "REJECTED", risk["reason"]
                    signals.append(sig)
                    self._reject(rejected, ev, d, risk["reason"], ts, risk["checks"])
                    if "portfolio risk" in risk["reason"].lower() or "daily loss" in risk["reason"].lower():
                        log_event("RISK_LIMIT_REACHED", {"time": ts.isoformat(), "symbol": ev.symbol,
                                                         "reason": risk["reason"]})
                    continue
                sig["status"] = "ACCEPTED"
                signals.append(sig)
                log_event("NEW_READY_SETUP", {"time": ts.isoformat(), "symbol": ev.symbol, "direction": ev.direction,
                                              "score": round(score, 1)})
                size = risk["size"]
                po = PendingOrder(ev, ev.symbol, ev.sector, ev.direction, ts, max(1, cfg.ENTRY_ORDER_VALIDITY_BARS),
                                  size.quantity, size.position_value, size.risk_amount, d)
                self.order_sink("PLACE", {"eval_id": ev.eval_id, "symbol": ev.symbol, "direction": ev.direction,
                                          "qty": size.quantity, "entry_mode": cfg.ENTRY_MODE,
                                          "trigger": ev.entry_trigger, "stop": ev.stop, "targets": ev.targets})
                if cfg.ENTRY_MODE == "REVERSAL_CLOSE":
                    ds = self.datasets[ev.symbol]
                    fill = self.execution.entry_fill("BUY" if ev.direction == "LONG" else "SELL", ev.price)
                    t = self._try_fill(po, fill, ev.bar, ds.bars[ev.bar], ts, equity, positions, rejected, seq)
                    if t is not None:
                        seq += 1
                        positions.append(t)
                        last_price[t.symbol] = fill
                else:
                    pending.append(po)

            # ---------------- 4. portfolio risk events (Section 27) --------
            equity = equity_now()
            breach = None
            if positions and cfg.PORTFOLIO_EXIT_ON_DAILY_LOSS and equity - prev_equity < -cfg.MAX_DAILY_LOSS * prev_equity:
                breach = f"daily loss {equity - prev_equity:,.0f} breached {cfg.MAX_DAILY_LOSS:.1%} limit"
            if not halted and equity / peak - 1.0 < -cfg.MAX_DRAWDOWN_HALT:
                halted = True
                breach = f"drawdown {equity / peak - 1.0:.1%} breached {cfg.MAX_DRAWDOWN_HALT:.0%} halt -- new entries stopped"
            if breach:
                for t in list(positions):
                    ds = self.datasets[t.symbol]
                    i = ds.ts_index.get(ts)
                    if i is None:
                        continue
                    self.manager.force_close(t, i, ds.bars[i], "PORTFOLIO_RISK")
                    positions.remove(t)
                    closed.append(t)
                    realized += t.net_pnl
                    log_event("POSITION_CLOSED", {"time": ts.isoformat(), "symbol": t.symbol, "trade_id": t.trade_id,
                                                  "reason": "PORTFOLIO_RISK", "net_pnl": round(t.net_pnl, 2)})
                pending = []
                log_event("RISK_LIMIT_REACHED", {"time": ts.isoformat(), "reason": breach})

            # ---------------- 5. mark to market ---------------------------
            equity = equity_now()
            peak = max(peak, equity)
            invested = sum(t.entry * t.remaining_qty for t in positions)
            equity_curve.append({"time": ts.isoformat(), "equity": round(equity, 2), "cash": round(equity - invested, 2),
                                 "invested": round(invested, 2), "drawdown": round(equity / peak - 1.0, 5),
                                 "open_risk": round(sum(open_risk(t) for t in positions), 2),
                                 "positions": len(positions)})
            prev_equity = equity

        if self.force_close_at_end and timeline:
            for t in list(positions):
                ds = self.datasets[t.symbol]
                i = ds.ts_index.get(timeline[-1])
                if i is None:
                    i = max(k for k, b in enumerate(ds.bars) if b.timestamp <= timeline[-1])
                self.manager.force_close(t, i, ds.bars[i], "END_OF_DATA")
                positions.remove(t)
                closed.append(t)
                realized += t.net_pnl

        return BacktestResult(self.label, self.cfg.to_dict(), self.disabled,
                              timeline[0] if timeline else None, timeline[-1] if timeline else None,
                              closed, positions, equity_curve, signals, rejected, events, cfg.INITIAL_CAPITAL)

    # ------------------------------------------------------------------ #
    def _entry_price(self, po: PendingOrder, bar) -> Optional[float]:
        mode = self.cfg.ENTRY_MODE
        side = "BUY" if po.direction == "LONG" else "SELL"
        long = po.direction == "LONG"
        if mode == "NEXT_OPEN":
            return self.execution.entry_fill(side, bar.open)
        trig = po.ev.entry_trigger
        if mode == "BREAK_OF_REVERSAL":
            if (bar.high >= trig) if long else (bar.low <= trig):
                ref = max(bar.open, trig) if long else min(bar.open, trig)
                return self.execution.entry_fill(side, ref)
            return None
        if mode == "LIMIT_IN_ZONE":
            if (bar.low <= trig) if long else (bar.high >= trig):
                return min(bar.open, trig) if long else max(bar.open, trig)
            return None
        return self.execution.entry_fill(side, bar.open)

    def _try_fill(self, po: PendingOrder, fill: float, i: int, bar, ts, equity: float, positions: List[Trade],
                  rejected: List[Dict], seq: int) -> Optional[Trade]:
        ev = po.ev
        sgn = 1 if ev.direction == "LONG" else -1
        if (fill - ev.stop) * sgn <= 0 or (fill - ev.targets["t1"]) * sgn >= 0:
            self._reject(rejected, ev, po.decision, "GAP: fill price beyond stop or T1 -- order cancelled", ts)
            self.order_sink("CANCEL", {"eval_id": ev.eval_id, "symbol": ev.symbol, "reason": "gap"})
            return None
        cash = equity - sum(p.position_value for p in positions)
        size = position_size(equity, self.cfg.RISK_PER_TRADE, fill, ev.stop, ev.lot_size,
                             self.cfg.MAX_POSITION_PERCENT, cash)
        if not size.valid:
            self._reject(rejected, ev, po.decision, "RISK at fill: " + "; ".join(size.reasons), ts)
            return None
        snapshot = journal_snapshot(ev, po.decision)
        t = self.manager.open_trade(f"T{seq + 1:04d}-{ev.symbol}", ev, fill, i, bar, size.quantity, snapshot)
        self.order_sink("FILL", {"trade_id": t.trade_id, "eval_id": ev.eval_id, "symbol": ev.symbol,
                                 "direction": ev.direction, "qty": size.quantity, "price": round(fill, 2)})
        return t

    def _reject(self, rejected: List[Dict], ev: SetupEvaluation, decision: Dict, reason: str, ts, risk_checks=None):
        if not self.record_rejections:
            return
        rejected.append({
            "eval_id": ev.eval_id, "time": ev.timestamp.isoformat(), "decided_at": ts.isoformat(),
            "symbol": ev.symbol, "sector": ev.sector, "timeframe": ev.timeframe, "direction": ev.direction,
            "trigger": ev.trigger, "price": round(ev.price, 2),
            "score": decision["confluence"]["score"], "min_score": decision["min_confluence"],
            "zone_score": decision["zone_score"]["score"], "min_zone_score": decision["min_zone_score"],
            "coverage": decision["confluence"]["coverage"], "reason": reason, "rules": decision["rules"],
            "factors": decision["confluence"]["rows"], "risk_checks": risk_checks or [],
            "pattern": ev.pattern["pattern"] if ev.pattern else None, "trend": ev.trend, "htf_trend": ev.htf_trend,
            "zone": {k: ev.zone.get(k) for k in ("type", "pattern", "proximal", "distal", "status", "prior_tests")},
            "rr": None if ev.rr is None else round(ev.rr, 2),
        })


def journal_snapshot(ev: SetupEvaluation, decision: Dict) -> Dict:
    """Decision context frozen at entry for the trade journal (Section 44)."""
    pos = ev.positioning
    return {
        "pivot_time": ev.last_pivot["time"] if ev.last_pivot else None,
        "pivot_confirmation_time": ev.last_pivot["confirmation_time"] if ev.last_pivot else None,
        "pivot_label": ev.last_pivot["label"] if ev.last_pivot else None,
        "structure": ev.trend, "htf_structure": ev.htf_trend,
        "structure_event": (f"{ev.last_event['direction']} {ev.last_event['type']}" if ev.last_event else None),
        "zone_id": ev.zone.get("id"), "zone_type": ev.zone.get("type"), "zone_pattern": ev.zone.get("pattern"),
        "zone_status": ev.zone.get("status"), "zone_prior_tests": ev.prior_tests,
        "zone_score": decision["zone_score"]["score"], "zone_proximal": ev.zone.get("proximal"),
        "zone_distal": ev.zone.get("distal"),
        "poc": ev.vp["poc"] if ev.vp else None, "vah": ev.vp["vah"] if ev.vp else None,
        "val": ev.vp["val"] if ev.vp else None,
        "poc_relation": ev.vp["confluence"]["levels"]["POC"]["relation"] if ev.vp and ev.vp["confluence"]["available"] else None,
        "commercial": pos["COMMERCIAL"]["classification"] or pos["COMMERCIAL"]["status"],
        "institutional": pos["INSTITUTIONAL"]["classification"] or pos["INSTITUTIONAL"]["status"],
        "retail": pos["RETAIL"]["classification"] or pos["RETAIL"]["status"],
        "oi_state": ev.oi["state"] if ev.oi else "UNAVAILABLE",
        "pcr": ev.pcr.get("pcr") if ev.pcr else None,
        "change_oi_pcr": ev.pcr.get("change_oi_pcr") if ev.pcr else None,
        "candlestick": ev.pattern["pattern"] if ev.pattern else None,
        "pattern_confidence": ev.pattern["confidence"] if ev.pattern else None,
        "confluence": decision["confluence"]["score"], "coverage": decision["confluence"]["coverage"],
        "planned_entry": round(ev.entry_ref, 2), "stop": round(ev.stop, 2),
        "t1": round(ev.targets["t1"], 2), "t2": round(ev.targets["t2"], 2), "t3": round(ev.targets["t3"], 2),
        "target_methods": ev.targets.get("methods"), "rr": round(ev.rr, 2) if ev.rr else None,
        "trigger": ev.trigger, "entry_mode": ev.entry_mode, "stop_note": ev.stop_note,
        "why": [{"ok": r["passed"], "text": f"{r['rule']}: {r['detail']}"} for r in decision["rules"]],
    }
