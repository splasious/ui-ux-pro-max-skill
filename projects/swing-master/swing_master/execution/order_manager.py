"""Order manager -- turns simulator/strategy order intents into broker orders per execution mode.

BACKTEST   intents are ignored (the simulator fills internally)
PAPER      orders go to the PaperBroker through the safety gateway
MANUAL     analysis only: intents are stored as proposals, nothing is sent
SEMI_AUTO  proposals wait for an explicit ``confirm(proposal_id)``
AUTO       orders go to the live gateway -- only when LIVE_TRADING_ENABLED is
           set AND research validation has been recorded.
"""
from __future__ import annotations

import itertools
from typing import Dict, List, Optional

from .broker_interface import BrokerError, OrderRequest, SafeBrokerGateway

MODES = ("BACKTEST", "PAPER", "MANUAL", "SEMI_AUTO", "AUTO")


class OrderManager:
    def __init__(self, mode: str, gateway: Optional[SafeBrokerGateway] = None, live_enabled: bool = False,
                 validated: bool = False):
        mode = mode.upper()
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if mode == "AUTO" and not (live_enabled and validated):
            raise BrokerError("AUTO mode requires SM_LIVE_TRADING_ENABLED=1 and a validated research record")
        self.mode = mode
        self.gateway = gateway
        self.proposals: Dict[str, Dict] = {}
        self.log: List[Dict] = []
        self._ids = itertools.count(1)
        self._eval_to_order: Dict[str, str] = {}

    # used as ``order_sink`` by the portfolio simulator
    def __call__(self, action: str, payload: Dict) -> None:
        self.log.append({"action": action, **{k: v for k, v in payload.items() if k != "targets"}})
        if self.mode == "BACKTEST":
            return
        if action == "PLACE":
            pid = f"P{next(self._ids):05d}"
            self.proposals[pid] = {"id": pid, "status": "PROPOSED", **payload}
            if self.mode in ("PAPER", "AUTO"):
                self._send(pid)
        elif action == "FILL" and self.mode == "PAPER":
            oid = self._eval_to_order.get(payload.get("eval_id"))
            if oid and self.gateway is not None:
                self.gateway.broker.fill(oid, payload["price"], payload["qty"])  # type: ignore[attr-defined]
        elif action in ("CANCEL", "EXPIRE"):
            oid = self._eval_to_order.get(payload.get("eval_id"))
            if oid and self.gateway is not None:
                self.gateway.broker.cancel_order(oid)

    def confirm(self, proposal_id: str) -> Dict:
        if self.mode != "SEMI_AUTO":
            raise BrokerError("confirm() is only used in SEMI_AUTO mode")
        return self._send(proposal_id)

    def _send(self, pid: str) -> Dict:
        prop = self.proposals[pid]
        if self.gateway is None:
            prop["status"] = "NO_GATEWAY"
            return prop
        req = OrderRequest(symbol=prop["symbol"], side="BUY" if prop["direction"] == "LONG" else "SELL",
                           quantity=int(prop["qty"]), order_type="MARKET", tag="SM", client_id=prop["eval_id"])
        try:
            rec = self.gateway.submit(req)
            prop["status"], prop["order_id"] = "SENT", rec.order_id
            self._eval_to_order[prop["eval_id"]] = rec.order_id
        except BrokerError as exc:
            prop["status"], prop["error"] = "BLOCKED", str(exc)
        return prop
