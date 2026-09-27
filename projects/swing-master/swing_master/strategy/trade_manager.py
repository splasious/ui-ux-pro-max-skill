"""Trade lifecycle -- the ONE authoritative definition of stop / target / trail / exit rules.

Used identically by the backtester and the paper-trading session.

Per-bar processing order (conservative, Section 2 & 27):
1. Gap: if the bar OPENS beyond the stop, exit at the open (worse than stop).
2. Intrabar: if the stop and any target are both inside the bar's range we
   cannot know which printed first -> assume the STOP (SAME_BAR_POLICY).
3. Targets T1 -> T2 -> T3 book partial quantities at the target price.
4. Close-based exits: zone invalidation, confirmed structural failure,
   opposite structure event, maximum holding period.
5. Stop adjustments decided on this bar (breakeven after T1, structural
   trail from pivots CONFIRMED on this bar) take effect from the NEXT bar.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from ..risk.position_size import split_quantities
from ..risk.trailing_stop import tighten, trail_candidate
from ..schemas import Bar, ExitReason
from .short_setup import spec_for


@dataclass
class Trade:
    trade_id: str
    symbol: str
    sector: str
    direction: str
    timeframe: str
    eval_id: str
    signal_bar: int
    signal_time: datetime
    entry_bar: int
    entry_time: datetime
    entry: float
    quantity: int
    initial_stop: float
    current_stop: float
    targets: List[float]
    leg_qty: List[int]
    zone_distal: float
    zone_invalidation_mode: str
    atr_at_entry: float
    lot_size: int = 1
    remaining_qty: int = 0
    targets_hit: List[bool] = field(default_factory=lambda: [False, False, False])
    fills: List[Dict] = field(default_factory=list)
    trail_history: List[Dict] = field(default_factory=list)
    status: str = "OPEN"
    exit_bar: Optional[int] = None
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    gross_pnl: float = 0.0
    costs: float = 0.0
    entry_costs: float = 0.0
    mfe: float = 0.0
    mae: float = 0.0
    last_price: float = 0.0
    last_trail_pivot: Optional[Dict] = None
    stop_kind: str = ExitReason.INITIAL_SL
    snapshot: Dict = field(default_factory=dict)

    @property
    def risk_per_share(self) -> float:
        return abs(self.entry - self.initial_stop)

    @property
    def initial_risk(self) -> float:
        return self.risk_per_share * self.quantity

    @property
    def position_value(self) -> float:
        return self.entry * self.remaining_qty

    @property
    def risk_amount(self) -> float:
        return max(0.0, (self.entry - self.current_stop) * (1 if self.direction == "LONG" else -1)) * self.remaining_qty

    @property
    def booked_qty(self) -> int:
        return self.quantity - self.remaining_qty

    @property
    def net_pnl(self) -> float:
        return self.gross_pnl - self.costs

    def unrealized(self, price: float) -> float:
        sign = 1 if self.direction == "LONG" else -1
        return (price - self.entry) * sign * self.remaining_qty

    def r_multiple(self, price: Optional[float] = None) -> Optional[float]:
        if self.initial_risk <= 0:
            return None
        pnl = self.net_pnl + (self.unrealized(price) if price is not None and self.status == "OPEN" else 0.0)
        return pnl / self.initial_risk

    def to_dict(self) -> Dict:
        price = self.last_price or self.entry
        return {
            "trade_id": self.trade_id, "symbol": self.symbol, "sector": self.sector, "direction": self.direction,
            "timeframe": self.timeframe, "eval_id": self.eval_id,
            "signal_time": self.signal_time.isoformat(), "entry_time": self.entry_time.isoformat(),
            "entry": round(self.entry, 2), "quantity": self.quantity, "remaining_qty": self.remaining_qty,
            "booked_qty": self.booked_qty, "runner_qty": self.leg_qty[2] if not self.targets_hit[2] else 0,
            "initial_stop": round(self.initial_stop, 2), "current_stop": round(self.current_stop, 2),
            "targets": [round(t, 2) for t in self.targets], "targets_hit": self.targets_hit,
            "leg_qty": self.leg_qty, "status": self.status, "current_price": round(price, 2),
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "exit_price": None if self.exit_price is None else round(self.exit_price, 2),
            "exit_reason": self.exit_reason, "gross_pnl": round(self.gross_pnl, 2), "costs": round(self.costs, 2),
            "net_pnl": round(self.net_pnl, 2),
            "unrealized_pnl": round(self.unrealized(price), 2) if self.status == "OPEN" else 0.0,
            "r_multiple": None if self.r_multiple(price) is None else round(self.r_multiple(price), 2),
            "holding_bars": (self.exit_bar if self.exit_bar is not None else self.snapshot.get("_last_bar", self.entry_bar))
            - self.entry_bar,
            "risk_per_share": round(self.risk_per_share, 2), "initial_risk": round(self.initial_risk, 2),
            "open_risk": round(self.risk_amount, 2), "mfe_r": round(self.mfe, 2), "mae_r": round(self.mae, 2),
            "fills": self.fills, "trail_history": self.trail_history, "last_trail_pivot": self.last_trail_pivot,
            "snapshot": {k: v for k, v in self.snapshot.items() if not k.startswith("_")},
        }


class TradeManager:
    def __init__(self, cfg, execution):
        self.cfg = cfg
        self.execution = execution

    # ------------------------------------------------------------------ #
    def open_trade(self, trade_id: str, ev, fill_price: float, bar_index: int, bar: Bar, qty: int,
                   snapshot: Dict) -> Trade:
        legs = split_quantities(qty, self.cfg.TARGET_1_EXIT_PERCENT, self.cfg.TARGET_2_EXIT_PERCENT, ev.lot_size)
        t = Trade(
            trade_id=trade_id, symbol=ev.symbol, sector=ev.sector, direction=ev.direction, timeframe=ev.timeframe,
            eval_id=ev.eval_id, signal_bar=ev.bar, signal_time=ev.timestamp, entry_bar=bar_index,
            entry_time=bar.timestamp, entry=fill_price, quantity=qty, initial_stop=ev.stop, current_stop=ev.stop,
            targets=[ev.targets["t1"], ev.targets["t2"], ev.targets["t3"]], leg_qty=legs,
            zone_distal=ev.zone["distal"], zone_invalidation_mode=ev.zone.get("invalidation_mode", "CLOSE"),
            atr_at_entry=ev.atr, lot_size=ev.lot_size, remaining_qty=qty, snapshot=snapshot, last_price=fill_price,
        )
        side = "BUY" if ev.direction == "LONG" else "SELL"
        t.entry_costs = self.execution.costs(side, fill_price, qty)
        t.costs += t.entry_costs
        t.fills.append({"time": bar.timestamp.isoformat(), "bar": bar_index, "side": side, "qty": qty,
                        "price": round(fill_price, 2), "reason": "ENTRY"})
        t.trail_history.append({"time": bar.timestamp.isoformat(), "bar": bar_index, "old": None,
                                "new": round(ev.stop, 2), "reason": "Initial structural stop", "pivot": None})
        return t

    # ------------------------------------------------------------------ #
    def on_bar(self, t: Trade, i: int, bar: Bar, pivots_confirmed_now: List, events_now: List,
               atr: Optional[float]) -> List[Dict]:
        """Advance an open trade through closed bar ``i``.  Returns event dicts."""
        if t.status != "OPEN" or i < t.entry_bar:
            return []
        spec = spec_for(t.direction)
        sgn = spec.sign
        events: List[Dict] = []
        t.snapshot["_last_bar"] = i

        # 1. gap through stop at the open (not on the entry bar -- we filled at that open)
        if i > t.entry_bar and (bar.open - t.current_stop) * sgn <= 0:
            self._close(t, i, bar, bar.open, t.stop_kind, events, gap=True)
            return events

        # 2./3. intrabar stop vs targets
        stop_hit = (bar.low <= t.current_stop) if sgn > 0 else (bar.high >= t.current_stop)
        hits = []
        for k in range(3):
            if not t.targets_hit[k]:
                reached = (bar.high >= t.targets[k]) if sgn > 0 else (bar.low <= t.targets[k])
                if reached:
                    hits.append(k)
                else:
                    break
        if stop_hit:
            # SAME_BAR_POLICY = STOP_FIRST: a same-bar target is never credited ahead of the stop
            self._close(t, i, bar, t.current_stop, t.stop_kind, events)
            return events
        mfe_price = bar.high if sgn > 0 else bar.low
        mae_price = bar.low if sgn > 0 else bar.high
        if t.risk_per_share > 0:
            t.mfe = max(t.mfe, (mfe_price - t.entry) * sgn / t.risk_per_share)
            t.mae = min(t.mae, (mae_price - t.entry) * sgn / t.risk_per_share)

        for k in hits:
            t.targets_hit[k] = True
            qty = t.remaining_qty if k == 2 else min(t.leg_qty[k], t.remaining_qty)
            if qty > 0:
                self._exit_qty(t, i, bar, t.targets[k], qty, f"T{k + 1}", events)
            events.append({"type": f"T{k + 1}_HIT", "bar": i, "price": round(t.targets[k], 2)})
            if k == 2 or t.remaining_qty == 0:
                self._finalise(t, i, bar, t.targets[k], ExitReason.T3 if k == 2 else f"T{k + 1}")
                return events
        new_stop = t.current_stop
        if hits and 0 in hits:
            be = self._breakeven_level(t, atr)
            if be is not None and tighten(spec, new_stop, be) != new_stop:
                new_stop = tighten(spec, new_stop, be)
                t.stop_kind = ExitReason.BREAKEVEN_SL
                t.trail_history.append({"time": bar.close_time.isoformat(), "bar": i, "old": round(t.current_stop, 2),
                                        "new": round(new_stop, 2), "reason": f"Breakeven after T1 ({self.cfg.BREAKEVEN_MODE})",
                                        "pivot": None})
                events.append({"type": "SL_MODIFIED", "bar": i, "price": round(new_stop, 2), "reason": "BREAKEVEN"})

        # 4. close-based exits
        close = bar.close
        invalid = ((close < t.zone_distal) if sgn > 0 else (close > t.zone_distal)) \
            if t.zone_invalidation_mode == "CLOSE" else \
            ((bar.low < t.zone_distal) if sgn > 0 else (bar.high > t.zone_distal))
        if self.cfg.EXIT_ON_ZONE_INVALIDATION and invalid and i > t.entry_bar:
            self._close(t, i, bar, close, ExitReason.ZONE_INVALIDATION, events)
            return events
        if self.cfg.EXIT_ON_STRUCTURAL_FAILURE:
            for p in pivots_confirmed_now:
                if p.label == spec.failure_label and p.pivot_bar >= t.entry_bar:
                    self._close(t, i, bar, close, ExitReason.STRUCTURAL_FAILURE, events)
                    return events
        mode = self.cfg.EXIT_ON_OPPOSITE_EVENT
        if mode != "OFF":
            for ev in events_now:
                if ev.direction == spec.opposite_trend and (mode == "CHOCH" or ev.event_type == "BOS"):
                    self._close(t, i, bar, close, ExitReason.OPPOSITE_STRUCTURE, events)
                    return events
        if i - t.entry_bar >= self.cfg.MAX_HOLDING_BARS:
            self._close(t, i, bar, close, ExitReason.MAX_HOLDING, events)
            return events

        # 5. structural trail from pivots confirmed on this bar (effective next bar)
        active = {"IMMEDIATE": True, "AFTER_T1": t.targets_hit[0], "AFTER_T2": t.targets_hit[1]}[self.cfg.TRAIL_ACTIVATION]
        if active:
            for p in pivots_confirmed_now:
                cand = trail_candidate(spec, p, t.entry_bar, atr, self.cfg.TRAIL_ATR_BUFFER)
                tightened = tighten(spec, new_stop, cand)
                if cand is not None and tightened != new_stop:
                    t.trail_history.append({"time": bar.close_time.isoformat(), "bar": i, "old": round(new_stop, 2),
                                            "new": round(tightened, 2),
                                            "reason": f"Confirmed {p.label} {p.pivot_price:.2f} "
                                                      f"- {self.cfg.TRAIL_ATR_BUFFER:g} ATR",
                                            "pivot": {"price": round(p.pivot_price, 2), "time": p.pivot_timestamp.isoformat(),
                                                      "confirmed": p.confirmation_timestamp.isoformat(), "label": p.label}})
                    t.last_trail_pivot = {"label": p.label, "price": round(p.pivot_price, 2),
                                          "confirmed": p.confirmation_timestamp.isoformat()}
                    new_stop = tightened
                    t.stop_kind = ExitReason.TRAILING_SL
                    events.append({"type": "TRAIL_MOVED", "bar": i, "price": round(new_stop, 2)})
        t.current_stop = new_stop
        t.last_price = close
        return events

    # ------------------------------------------------------------------ #
    def _breakeven_level(self, t: Trade, atr: Optional[float]) -> Optional[float]:
        mode = self.cfg.BREAKEVEN_MODE
        sgn = 1 if t.direction == "LONG" else -1
        if mode == "KEEP":
            return None
        if mode == "ENTRY":
            return t.entry
        if mode == "ENTRY_PLUS_COSTS":
            per_share = (t.entry_costs * 2) / max(t.quantity, 1)
            return t.entry + sgn * per_share
        if mode == "ATR_ADJUSTED":
            return t.entry - sgn * (atr or t.atr_at_entry) * self.cfg.BREAKEVEN_ATR
        return None

    def _exit_qty(self, t: Trade, i: int, bar: Bar, price: float, qty: int, reason: str, events: List[Dict]) -> None:
        qty = min(qty, t.remaining_qty)
        if qty <= 0:
            return
        side = "SELL" if t.direction == "LONG" else "BUY"
        fill = self.execution.exit_fill(side, price, reason)
        sgn = 1 if t.direction == "LONG" else -1
        t.gross_pnl += (fill - t.entry) * sgn * qty
        t.costs += self.execution.costs(side, fill, qty)
        t.remaining_qty -= qty
        t.fills.append({"time": bar.timestamp.isoformat(), "bar": i, "side": side, "qty": qty, "price": round(fill, 2),
                        "reason": reason})
        events.append({"type": "PARTIAL_EXIT" if t.remaining_qty else "EXIT", "bar": i, "qty": qty,
                       "price": round(fill, 2), "reason": reason})

    def _close(self, t: Trade, i: int, bar: Bar, price: float, reason: str, events: List[Dict], gap: bool = False) -> None:
        self._exit_qty(t, i, bar, price, t.remaining_qty, reason + (" (gap)" if gap else ""), events)
        self._finalise(t, i, bar, price, reason)

    def _finalise(self, t: Trade, i: int, bar: Bar, price: float, reason: str) -> None:
        t.status = "CLOSED"
        t.exit_bar = i
        t.exit_time = bar.timestamp
        t.exit_price = t.fills[-1]["price"] if t.fills else price
        t.exit_reason = reason
        t.last_price = price

    def force_close(self, t: Trade, i: int, bar: Bar, reason: str) -> List[Dict]:
        events: List[Dict] = []
        if t.status == "OPEN":
            self._close(t, i, bar, bar.close, reason, events)
        return events
