"""Walk-forward lab (Section 43):  TRAIN -> VALIDATE -> OUT-OF-SAMPLE TEST -> ROLL FORWARD.

Selection protocol per fold
1. Run every parameter combination on the TRAIN window.
2. Keep the top ``shortlist`` combinations by the train objective.
3. Pick the one with the best objective on the VALIDATE window.
4. Run ONLY that combination once on the TEST window and report it.

The optimiser only ever receives train/validate windows -- the test window is
touched exactly once, after selection, so it can never influence the choice.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .engine import PortfolioBacktester
from .metrics import compute_metrics

DEFAULT_GRID = {"MIN_CONFLUENCE_SCORE": [60, 65, 70], "MIN_ZONE_SCORE": [55, 60, 65]}


@dataclass
class Window:
    start: datetime
    end: datetime

    def to_dict(self):
        return {"start": self.start.date().isoformat(), "end": self.end.date().isoformat()}


def _add_months(d: datetime, months: int) -> datetime:
    y, m = divmod(d.month - 1 + months, 12)
    return d.replace(year=d.year + y, month=m + 1, day=1)


def make_folds(first: datetime, last: datetime, train_m: int = 18, validate_m: int = 6, test_m: int = 6,
               step_m: int = 6) -> List[Tuple[Window, Window, Window]]:
    folds = []
    anchor = first.replace(day=1)
    while True:
        tr_end = _add_months(anchor, train_m)
        va_end = _add_months(tr_end, validate_m)
        te_end = _add_months(va_end, test_m)
        if va_end >= last:
            break
        eps = timedelta(seconds=1)
        folds.append((Window(anchor, tr_end - eps), Window(tr_end, va_end - eps),
                      Window(va_end, min(te_end - eps, last))))
        if te_end > last:
            break
        anchor = _add_months(anchor, step_m)
    return folds


def objective(m: Dict, min_trades: int = 4) -> float:
    """t-stat-like: mean R x sqrt(n).  Too few trades -> -inf (not selectable)."""
    n = m.get("total_trades") or 0
    if n < min_trades or m.get("average_r") is None:
        return float("-inf")
    return m["average_r"] * math.sqrt(n)


class WalkForwardLab:
    def __init__(self, datasets, cfg, grid: Optional[Dict[str, Sequence]] = None, shortlist: int = 3,
                 disabled: Sequence[str] = (), runner: Optional[Callable] = None):
        self.datasets = datasets
        self.cfg = cfg
        self.grid = grid or DEFAULT_GRID
        self.shortlist = shortlist
        self.disabled = list(disabled)
        self.runner = runner or self._run
        self.requested_windows: List[Tuple[str, Window]] = []  # audit trail (used by tests)

    def _run(self, cfg, window: Window):
        res = PortfolioBacktester(self.datasets, cfg, self.disabled, window.start, window.end,
                                  force_close_at_end=True, record_rejections=False).run()
        return res, compute_metrics(res.trades, res.equity_curve, cfg.INITIAL_CAPITAL)

    def combos(self) -> List[Dict]:
        keys = list(self.grid)
        return [dict(zip(keys, vals)) for vals in itertools.product(*(self.grid[k] for k in keys))]

    def select(self, train: Window, validate: Window) -> Dict:
        scored = []
        for params in self.combos():
            cfg = self.cfg.with_overrides(**params)
            self.requested_windows.append(("train", train))
            _, m = self.runner(cfg, train)
            scored.append((objective(m), params, m))
        scored.sort(key=lambda x: -x[0])
        short = [s for s in scored[: self.shortlist] if s[0] != float("-inf")] or scored[:1]
        best = None
        for obj_train, params, m_train in short:
            cfg = self.cfg.with_overrides(**params)
            self.requested_windows.append(("validate", validate))
            _, m_val = self.runner(cfg, validate)
            cand = (objective(m_val, 2), obj_train, params, m_train, m_val)
            if best is None or cand[:2] > best[:2]:
                best = cand
        _, _, params, m_train, m_val = best
        return {"params": params, "train": m_train, "validate": m_val,
                "grid": [{"params": p, "objective": None if o == float("-inf") else round(o, 3),
                          "trades": m["total_trades"], "avg_r": m["average_r"]} for o, p, m in scored]}

    def run(self) -> Dict:
        bars = [b.timestamp for ds in self.datasets.values() for b in ds.bars[self.cfg.WARMUP_BARS:]]
        first, last = min(bars), max(bars)
        folds_out, oos_trades, oos_curve = [], [], []
        equity = self.cfg.INITIAL_CAPITAL
        for k, (train, validate, test) in enumerate(make_folds(first, last)):
            sel = self.select(train, validate)
            cfg = self.cfg.with_overrides(**sel["params"])
            self.requested_windows.append(("test", test))
            res, m_test = self.runner(cfg, test)
            base = res.equity_curve[0]["equity"] if res.equity_curve else self.cfg.INITIAL_CAPITAL
            for p in res.equity_curve:
                oos_curve.append({"time": p["time"], "equity": round(equity * p["equity"] / base, 2), "fold": k + 1})
            if res.equity_curve:
                equity = equity * res.equity_curve[-1]["equity"] / base
            oos_trades.extend(res.trades)
            folds_out.append({"fold": k + 1, "train": train.to_dict(), "validate": validate.to_dict(),
                              "test": test.to_dict(), "params": sel["params"], "train_metrics": sel["train"],
                              "validate_metrics": sel["validate"], "test_metrics": m_test, "grid": sel["grid"]})
        is_r = [f["train_metrics"]["average_r"] for f in folds_out if f["train_metrics"]["average_r"] is not None]
        oos_r = [f["test_metrics"]["average_r"] for f in folds_out if f["test_metrics"]["average_r"] is not None]
        peak, dd = self.cfg.INITIAL_CAPITAL, 0.0
        for p in oos_curve:
            peak = max(peak, p["equity"])
            dd = min(dd, p["equity"] / peak - 1)
        oos_rs = [t.r_multiple() or 0.0 for t in oos_trades]
        return {
            "folds": folds_out,
            "grid_keys": list(self.grid),
            "summary": {
                "folds": len(folds_out),
                "in_sample_avg_r": round(sum(is_r) / len(is_r), 3) if is_r else None,
                "out_of_sample_avg_r": round(sum(oos_r) / len(oos_r), 3) if oos_r else None,
                "oos_trades": len(oos_trades),
                "oos_win_rate": round(sum(1 for r in oos_rs if r > 0) / len(oos_rs), 3) if oos_rs else None,
                "oos_trade_avg_r": round(sum(oos_rs) / len(oos_rs), 3) if oos_rs else None,
                "oos_return": round(equity / self.cfg.INITIAL_CAPITAL - 1, 4),
                "oos_max_drawdown": round(dd, 4),
                "degradation": (round(sum(oos_r) / len(oos_r) - sum(is_r) / len(is_r), 3)
                                if is_r and oos_r else None),
            },
            "oos_equity": oos_curve[:: max(1, len(oos_curve) // 500)],
            "protocol": "Grid on TRAIN, shortlist top 3, choose on VALIDATE, single run on TEST.",
        }
