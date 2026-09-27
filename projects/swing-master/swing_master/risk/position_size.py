"""Risk-based position sizing (Section 23).

    risk_capital   = account_equity * risk_per_trade
    risk_per_share = |entry - stop|
    quantity       = floor(risk_capital / risk_per_share)   (rounded down to lots)

then capped by the maximum position size and available cash.  Zero-risk,
NaN/inf and sub-lot quantities are rejected -- never rounded up.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List


@dataclass
class SizeResult:
    valid: bool
    quantity: int
    risk_capital: float
    risk_per_share: float
    risk_amount: float
    position_value: float
    reasons: List[str] = field(default_factory=list)

    def to_dict(self):
        return {"valid": self.valid, "quantity": self.quantity, "risk_capital": round(self.risk_capital, 2),
                "risk_per_share": round(self.risk_per_share, 4), "risk_amount": round(self.risk_amount, 2),
                "position_value": round(self.position_value, 2), "reasons": self.reasons}


def position_size(equity: float, risk_per_trade: float, entry: float, stop: float, lot_size: int = 1,
                  max_position_pct: float = 1.0, available_cash: float = float("inf")) -> SizeResult:
    reasons: List[str] = []
    vals = (equity, risk_per_trade, entry, stop)
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in vals):
        return SizeResult(False, 0, 0.0, 0.0, 0.0, 0.0, ["non-finite sizing input"])
    if equity <= 0 or entry <= 0:
        return SizeResult(False, 0, 0.0, 0.0, 0.0, 0.0, ["equity and entry must be positive"])
    rps = abs(entry - stop)
    risk_capital = equity * risk_per_trade
    if rps <= 0:
        return SizeResult(False, 0, risk_capital, 0.0, 0.0, 0.0, ["zero risk per share (entry == stop)"])
    raw = risk_capital / rps
    if not math.isfinite(raw):
        return SizeResult(False, 0, risk_capital, rps, 0.0, 0.0, ["non-finite quantity"])
    lot = max(1, int(lot_size))
    qty = int(math.floor(raw / lot)) * lot
    cap_value = equity * max_position_pct
    if qty * entry > cap_value:
        qty = int(math.floor(cap_value / entry / lot)) * lot
        reasons.append(f"capped by max position {max_position_pct:.0%}")
    if qty * entry > available_cash:
        qty = int(math.floor(max(available_cash, 0.0) / entry / lot)) * lot
        reasons.append("capped by available cash")
    if qty < lot:
        reasons.append(f"quantity below one lot ({lot})" if lot > 1 else "quantity below 1")
        return SizeResult(False, 0, risk_capital, rps, 0.0, 0.0, reasons)
    return SizeResult(True, qty, risk_capital, rps, qty * rps, qty * entry, reasons)


def split_quantities(qty: int, t1_pct: float, t2_pct: float, lot_size: int = 1) -> List[int]:
    """[T1, T2, runner] quantities; floor-rounded so the legs never exceed ``qty``."""
    lot = max(1, int(lot_size))
    q1 = int(math.floor(qty * t1_pct / lot)) * lot
    q2 = int(math.floor(qty * t2_pct / lot)) * lot
    runner = qty - q1 - q2
    return [q1, q2, runner]
