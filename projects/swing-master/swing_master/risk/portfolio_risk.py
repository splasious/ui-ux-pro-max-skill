"""Portfolio-level risk engine (Sections 23 & 39).

The risk engine can -- and does -- reject technically valid setups.  Every
decision returns the full list of checks so rejections are explainable.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..indicators.utilities import pearson, pct_returns
from ..schemas import UNCLASSIFIED_SECTOR
from .position_size import position_size


def open_risk(trade) -> float:
    """Money lost if the current stop is hit (0 once the stop has passed entry)."""
    per_share = (trade.entry - trade.current_stop) * (1 if trade.direction == "LONG" else -1)
    return max(0.0, per_share) * trade.remaining_qty


class PortfolioRiskManager:
    def __init__(self, cfg):
        self.cfg = cfg

    def evaluate(self, *, equity: float, cash: float, positions: List, pending: List, symbol: str, sector: str,
                 direction: str, entry: float, stop: float, lot_size: int, day_pnl: float = 0.0,
                 kill_switch: bool = False) -> Dict:
        cfg = self.cfg
        checks = []

        def add(rule: str, ok: bool, detail: str):
            checks.append({"rule": rule, "passed": ok, "detail": detail})

        committed = sum(p.position_value for p in pending)
        size = position_size(equity, cfg.RISK_PER_TRADE, entry, stop, lot_size, cfg.MAX_POSITION_PERCENT,
                             cash - committed)
        add("Position size", size.valid, "; ".join(size.reasons) or f"qty {size.quantity}")
        add("Kill switch", not kill_switch, "manual kill switch engaged" if kill_switch else "off")
        daily_ok = day_pnl > -cfg.MAX_DAILY_LOSS * equity
        add("Daily loss limit", daily_ok, f"day P&L {day_pnl:,.0f} vs limit {-cfg.MAX_DAILY_LOSS * equity:,.0f}")
        n_open = len(positions) + len(pending)
        add("Max positions", n_open < cfg.MAX_POSITIONS, f"{n_open}/{cfg.MAX_POSITIONS} slots used")
        dup = any(p.symbol == symbol for p in positions) or any(p.symbol == symbol for p in pending)
        add("One position per symbol", not dup, "symbol already held" if dup else "ok")

        current_risk = sum(open_risk(p) for p in positions) + sum(p.risk_amount for p in pending)
        new_risk = size.risk_amount if size.valid else 0.0
        max_risk = cfg.MAX_PORTFOLIO_RISK * equity
        add("Max portfolio risk", current_risk + new_risk <= max_risk + 1e-6,
            f"open {current_risk:,.0f} + new {new_risk:,.0f} vs cap {max_risk:,.0f}")

        # An unclassified symbol is its own group: lumping unknown sectors together would cap them as one.
        sector_pos = [p for p in positions + pending
                      if p.sector == sector and (sector != UNCLASSIFIED_SECTOR or p.symbol == symbol)]
        sector_value = sum(p.position_value for p in sector_pos) + (size.position_value if size.valid else 0.0)
        sector_ok = (len(sector_pos) < cfg.MAX_POSITIONS_PER_SECTOR and
                     sector_value <= cfg.MAX_SECTOR_EXPOSURE * equity + 1e-6)
        add("Sector concentration", sector_ok,
            f"{sector}: {len(sector_pos)} positions, {sector_value / equity:.0%} of equity" if equity else sector)

        approved = all(c["passed"] for c in checks)
        failed = [c for c in checks if not c["passed"]]
        return {
            "approved": approved,
            "quantity": size.quantity if approved else 0,
            "size": size,
            "checks": checks,
            "reason": None if approved else f"RISK: {failed[0]['rule']} -- {failed[0]['detail']}",
        }


def exposure_report(positions: List, equity: float, prices: Dict[str, float]) -> Dict:
    long_v = short_v = 0.0
    sectors: Dict[str, float] = {}
    symbols: Dict[str, float] = {}
    for p in positions:
        px = prices.get(p.symbol, p.entry)
        v = px * p.remaining_qty
        if p.direction == "LONG":
            long_v += v
        else:
            short_v += v
        sectors[p.sector] = sectors.get(p.sector, 0.0) + v
        symbols[p.symbol] = symbols.get(p.symbol, 0.0) + v
    pct = lambda v: round(v / equity, 4) if equity else None  # noqa: E731
    return {
        "long_exposure": round(long_v, 2), "short_exposure": round(short_v, 2),
        "gross_exposure": round(long_v + short_v, 2), "net_exposure": round(long_v - short_v, 2),
        "long_pct": pct(long_v), "short_pct": pct(short_v),
        "sectors": [{"sector": s, "value": round(v, 2), "pct": pct(v)} for s, v in sorted(sectors.items(), key=lambda x: -x[1])],
        "symbols": [{"symbol": s, "value": round(v, 2), "pct": pct(v)} for s, v in sorted(symbols.items(), key=lambda x: -x[1])],
    }


def correlation_warnings(closes_by_symbol: Dict[str, List[float]], threshold: float, lookback: int) -> List[Dict]:
    syms = sorted(closes_by_symbol)
    rets = {s: pct_returns(closes_by_symbol[s][-(lookback + 1):]) for s in syms}
    out = []
    for a_i, a in enumerate(syms):
        for b in syms[a_i + 1:]:
            rho: Optional[float] = pearson(rets[a], rets[b])
            if rho is not None and rho >= threshold:
                out.append({"pair": [a, b], "correlation": round(rho, 2),
                            "detail": f"{a} and {b} move together (rho {rho:.2f} over {lookback} bars)"})
    return out
