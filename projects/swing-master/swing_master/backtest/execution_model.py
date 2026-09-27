"""Fill and cost model (NSE equity-delivery approximation, all configurable).

Slippage is always applied against the trader.  Costs per order:
brokerage (flat) + STT + exchange + SEBI + GST on (brokerage + exchange)
+ stamp duty on buys.
"""
from __future__ import annotations


class ExecutionModel:
    def __init__(self, cfg):
        self.cfg = cfg

    def _slip(self, side: str, price: float) -> float:
        s = self.cfg.SLIPPAGE_BPS / 10_000.0
        return price * (1 + s) if side == "BUY" else price * (1 - s)

    def entry_fill(self, side: str, ref_price: float) -> float:
        return self._slip(side, ref_price)

    def exit_fill(self, side: str, ref_price: float, reason: str = "") -> float:
        # Target (limit) exits fill at the target; stops / market exits slip.
        if reason.startswith("T") and reason[1:2].isdigit():
            return ref_price
        return self._slip(side, ref_price)

    def costs(self, side: str, price: float, qty: int) -> float:
        c = self.cfg
        turnover = price * qty
        brokerage = c.BROKERAGE_PER_ORDER if qty > 0 else 0.0
        exchange = turnover * c.EXCHANGE_PCT
        stt = turnover * c.STT_PCT
        sebi = turnover * c.SEBI_PCT
        gst = (brokerage + exchange) * c.GST_PCT
        stamp = turnover * c.STAMP_PCT_BUY if side == "BUY" else 0.0
        return brokerage + exchange + stt + sebi + gst + stamp
