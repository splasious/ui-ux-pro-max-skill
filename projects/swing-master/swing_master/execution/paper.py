"""Paper broker: an in-memory ``BrokerInterface`` that records orders and fills.

Fill prices come from the same ``ExecutionModel`` the backtester uses, applied
by the portfolio simulator, so paper and backtest results are directly
comparable.
"""
from __future__ import annotations

import itertools
from typing import Dict, List

from .broker_interface import BrokerInterface, OrderRecord, OrderRequest


class PaperBroker(BrokerInterface):
    name = "paper"

    def __init__(self):
        self._orders: Dict[str, OrderRecord] = {}
        self._ids = itertools.count(1)
        self._positions: Dict[str, Dict] = {}

    def place_order(self, req: OrderRequest) -> OrderRecord:
        oid = f"PAPER-{next(self._ids):05d}"
        rec = OrderRecord(oid, req, "OPEN", history=[{"status": "OPEN"}])
        self._orders[oid] = rec
        return rec

    def fill(self, order_id: str, price: float, qty: int) -> OrderRecord:
        rec = self._orders[order_id]
        rec.filled_qty += qty
        rec.average_price = price
        rec.status = "COMPLETE" if rec.filled_qty >= rec.request.quantity else "OPEN"
        rec.history.append({"status": rec.status, "price": price, "qty": qty})
        sign = 1 if rec.request.side == "BUY" else -1
        pos = self._positions.setdefault(rec.request.symbol, {"symbol": rec.request.symbol, "quantity": 0})
        pos["quantity"] += sign * qty
        return rec

    def modify_order(self, order_id: str, **changes) -> OrderRecord:
        rec = self._orders[order_id]
        for k, v in changes.items():
            if hasattr(rec.request, k):
                setattr(rec.request, k, v)
        rec.history.append({"status": "MODIFIED", **changes})
        return rec

    def cancel_order(self, order_id: str) -> OrderRecord:
        rec = self._orders[order_id]
        if rec.status == "OPEN":
            rec.status = "CANCELLED"
            rec.history.append({"status": "CANCELLED"})
        return rec

    def orders(self) -> List[OrderRecord]:
        return list(self._orders.values())

    def positions(self) -> List[Dict]:
        return [p for p in self._positions.values() if p["quantity"]]

    def status(self) -> Dict:
        return {"broker": self.name, "connected": True, "orders": len(self._orders)}
