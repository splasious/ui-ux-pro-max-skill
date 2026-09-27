"""Backtest KPIs and chart series (Section 41)."""
from __future__ import annotations

import math
from collections import OrderedDict
from datetime import datetime
from typing import Dict, List

from ..indicators.utilities import mean_std, median


def compute_metrics(trades: List, equity_curve: List[Dict], initial_capital: float, open_trades: List = ()) -> Dict:
    rs = [t.r_multiple() or 0.0 for t in trades]
    pnls = [t.net_pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win, gross_loss = sum(wins), -sum(losses)
    n = len(trades)
    final_equity = equity_curve[-1]["equity"] if equity_curve else initial_capital
    net = final_equity - initial_capital

    years = 0.0
    if len(equity_curve) >= 2:
        t0 = datetime.fromisoformat(equity_curve[0]["time"])
        t1 = datetime.fromisoformat(equity_curve[-1]["time"])
        years = max((t1 - t0).days / 365.25, 1e-9)
    cagr = (final_equity / initial_capital) ** (1 / years) - 1 if years > 0.2 and final_equity > 0 else None

    eq = [p["equity"] for p in equity_curve]
    dd_pct, max_dd_amt, peak = 0.0, 0.0, initial_capital
    for e in eq:
        peak = max(peak, e)
        dd_pct = min(dd_pct, e / peak - 1.0)
        max_dd_amt = max(max_dd_amt, peak - e)
    daily = [eq[k] / eq[k - 1] - 1.0 for k in range(1, len(eq)) if eq[k - 1] > 0]
    m, s = mean_std(daily)
    downside = [d for d in daily if d < 0]
    ds = math.sqrt(sum(d * d for d in downside) / len(daily)) if daily and downside else None
    sharpe = (m / s * math.sqrt(252)) if m is not None and s else None
    sortino = (m / ds * math.sqrt(252)) if m is not None and ds else None
    holding = [(t.exit_bar - t.entry_bar) for t in trades if t.exit_bar is not None]

    return {
        "net_pnl": round(net, 2),
        "net_pnl_pct": round(net / initial_capital, 4),
        "final_equity": round(final_equity, 2),
        "cagr": None if cagr is None else round(cagr, 4),
        "max_drawdown": round(dd_pct, 4),
        "max_drawdown_amount": round(max_dd_amt, 2),
        "win_rate": round(len(wins) / n, 4) if n else None,
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
        "expectancy": round(sum(pnls) / n, 2) if n else None,
        "expectancy_r": round(sum(rs) / n, 3) if n else None,
        "average_r": round(sum(rs) / n, 3) if n else None,
        "median_r": None if not rs else round(median(rs), 3),
        "total_trades": n,
        "open_trades": len(open_trades),
        "avg_holding_bars": round(sum(holding) / len(holding), 1) if holding else None,
        "sharpe": None if sharpe is None else round(sharpe, 2),
        "sortino": None if sortino is None else round(sortino, 2),
        "recovery_factor": round(net / max_dd_amt, 2) if max_dd_amt > 0 else None,
        "gross_profit": round(gross_win, 2),
        "gross_loss": round(gross_loss, 2),
        "total_costs": round(sum(t.costs for t in trades), 2),
        "exit_reasons": _count(t.exit_reason for t in trades),
    }


def _count(items) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for x in items:
        out[x] = out.get(x, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def chart_series(trades: List, equity_curve: List[Dict]) -> Dict:
    # equity & drawdown (downsample to <= 600 points)
    step = max(1, len(equity_curve) // 600)
    eq = [{"t": p["time"][:10], "equity": p["equity"], "dd": p["drawdown"]} for p in equity_curve[::step]]
    if equity_curve and (not eq or eq[-1]["t"] != equity_curve[-1]["time"][:10]):
        p = equity_curve[-1]
        eq.append({"t": p["time"][:10], "equity": p["equity"], "dd": p["drawdown"]})

    monthly: "OrderedDict[str, float]" = OrderedDict()
    prev = None
    month_start = {}
    for p in equity_curve:
        key = p["time"][:7]
        if key not in month_start:
            month_start[key] = prev if prev is not None else p["equity"]
        monthly[key] = p["equity"] / month_start[key] - 1.0 if month_start[key] else 0.0
        prev = p["equity"]
    monthly_rows = [{"month": k, "return": round(v, 4)} for k, v in monthly.items()]

    rs = [t.r_multiple() or 0.0 for t in trades]
    edges = [-3, -2, -1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2, 3, 4, 6]
    r_hist = []
    for a, b in zip([-99] + edges, edges + [99]):
        label = f"<{b}" if a == -99 else (f">{a}" if b == 99 else f"{a}..{b}")
        r_hist.append({"bucket": label, "count": sum(1 for r in rs if a <= r < b)})

    holding = [(t.exit_bar - t.entry_bar) for t in trades if t.exit_bar is not None]
    h_edges = [0, 3, 6, 10, 15, 20, 30, 40, 60]
    h_hist = []
    for a, b in zip(h_edges, h_edges[1:] + [9999]):
        h_hist.append({"bucket": f"{a}-{b}" if b != 9999 else f"{a}+", "count": sum(1 for h in holding if a <= h < b)})

    rolling = []
    window = 20
    ordered = sorted(trades, key=lambda t: t.exit_time or t.entry_time)
    for k in range(window, len(ordered) + 1):
        chunk = ordered[k - window:k]
        r = [t.r_multiple() or 0.0 for t in chunk]
        rolling.append({"t": (chunk[-1].exit_time or chunk[-1].entry_time).date().isoformat(),
                        "expectancy_r": round(sum(r) / window, 3),
                        "win_rate": round(sum(1 for x in r if x > 0) / window, 3)})
    return {"equity": eq, "monthly": monthly_rows, "r_distribution": r_hist, "holding": h_hist,
            "rolling": rolling, "rolling_window": window}
