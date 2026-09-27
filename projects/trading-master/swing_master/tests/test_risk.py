"""Mandatory tests 3, 7, 8, 9, 11, 12, 13, 14: trailing, sizing, partials, targets, same-bar handling."""
import math
import unittest
from datetime import datetime

from swing_master.backtest.execution_model import ExecutionModel
from swing_master.config import StrategyConfig
from swing_master.risk.position_size import position_size, split_quantities
from swing_master.risk.targets import compute_targets, validate_order
from swing_master.risk.trailing_stop import tighten, trail_candidate
from swing_master.schemas import Pivot
from swing_master.strategy.long_setup import LONG_SPEC
from swing_master.strategy.short_setup import SHORT_SPEC
from swing_master.strategy.trade_manager import TradeManager
from swing_master.tests.helpers import bars_from_ohlc

T0 = datetime(2024, 1, 1)


def pivot(kind, price, bar, conf, label):
    return Pivot(kind, price, bar, T0, conf, T0, 1, 1, 1, label=label)


class FakeEval:
    """Minimal evaluation carrying what TradeManager.open_trade reads."""
    def __init__(self, entry=100.0, stop=95.0, t=(105.0, 110.0, 115.0), direction="LONG"):
        self.symbol, self.sector, self.direction, self.timeframe = "X", "S", direction, "1D"
        self.eval_id, self.bar, self.timestamp = "e", 0, T0
        self.stop, self.atr, self.lot_size, self.entry_ref = stop, 2.0, 1, entry
        self.targets = {"t1": t[0], "t2": t[1], "t3": t[2]}
        self.zone = {"distal": stop + 0.5 if direction == "LONG" else stop - 0.5, "invalidation_mode": "CLOSE"}


class RiskTests(unittest.TestCase):
    def setUp(self):
        self.cfg = StrategyConfig()
        self.tm = TradeManager(self.cfg, ExecutionModel(self.cfg))

    # 8 -- sizing obeys risk
    def test_position_size_obeys_risk(self):
        for entry, stop in [(100, 95), (2500, 2437.5), (51.2, 50.9), (31817.9, 31169.65)]:
            r = position_size(1_000_000, 0.01, entry, stop)
            if r.valid:
                self.assertLessEqual(r.quantity * abs(entry - stop), 10_000 + 1e-6)
                self.assertLessEqual(r.quantity * entry, 1_000_000)

    def test_lot_rounding_rejects_sub_lot(self):
        r = position_size(1_000_000, 0.01, 31817.9, 31169.65, lot_size=75)
        self.assertFalse(r.valid)
        self.assertEqual(r.quantity, 0)

    # 12 / 13 -- zero-risk and non-finite rejected
    def test_zero_risk_rejected(self):
        self.assertFalse(position_size(1_000_000, 0.01, 100, 100).valid)

    def test_nan_inf_rejected(self):
        for bad in (float("nan"), float("inf"), -float("inf")):
            self.assertFalse(position_size(1_000_000, 0.01, bad, 95).valid)
            self.assertFalse(position_size(1_000_000, 0.01, 100, bad).valid)
            self.assertFalse(position_size(bad, 0.01, 100, 95).valid)

    # 9 -- partial exits never exceed quantity
    def test_partials_never_exceed_quantity(self):
        for q in range(0, 200):
            legs = split_quantities(q, 0.3, 0.3)
            self.assertEqual(sum(legs), q)
            self.assertTrue(all(x >= 0 for x in legs))
        legs = split_quantities(150, 0.3, 0.3, lot_size=25)
        self.assertEqual(sum(legs), 150)
        self.assertTrue(all(x % 25 == 0 for x in legs))

    # 11 -- targets ordered
    def test_target_ordering(self):
        pivots = [pivot("HIGH", 101.0, 1, 3, "HH"), pivot("HIGH", 99.0, 5, 7, "LH")]
        out = compute_targets(LONG_SPEC, 100.0, 95.0, pivots, [], None, [], self.cfg)
        self.assertTrue(out["valid"])
        self.assertTrue(validate_order(LONG_SPEC, 100.0, [out["t1"], out["t2"], out["t3"]]))
        out_s = compute_targets(SHORT_SPEC, 100.0, 105.0, [], [], None, [], self.cfg)
        self.assertTrue(validate_order(SHORT_SPEC, 100.0, [out_s["t1"], out_s["t2"], out_s["t3"]]))
        self.assertFalse(validate_order(LONG_SPEC, 100.0, [105, 104, 110]))

    # 7 -- stop never loosens
    def test_stop_never_loosens(self):
        self.assertEqual(tighten(LONG_SPEC, 95.0, 90.0), 95.0)
        self.assertEqual(tighten(LONG_SPEC, 95.0, 97.0), 97.0)
        self.assertEqual(tighten(SHORT_SPEC, 105.0, 108.0), 105.0)
        self.assertEqual(tighten(SHORT_SPEC, 105.0, 103.0), 103.0)
        self.assertEqual(tighten(LONG_SPEC, 95.0, None), 95.0)

    # 3 -- trail only from confirmed HL formed after entry
    def test_trail_requires_confirmed_hl_after_entry(self):
        self.assertIsNone(trail_candidate(LONG_SPEC, pivot("LOW", 98, 4, 6, "HL"), entry_bar=5, atr=1, buffer_atr=0.5))
        self.assertIsNone(trail_candidate(LONG_SPEC, pivot("LOW", 98, 8, 10, "LL"), entry_bar=5, atr=1, buffer_atr=0.5))
        self.assertAlmostEqual(trail_candidate(LONG_SPEC, pivot("LOW", 98, 8, 10, "HL"), 5, 1, 0.5), 97.5)

    def test_trade_manager_trails_only_on_confirmation_bar(self):
        bars = bars_from_ohlc([(100, 101, 99, 100.5)] * 12)
        t = self.tm.open_trade("T1", FakeEval(stop=95.0, t=(150, 160, 170)), 100.0, 0, bars[0], 100, {})
        hl = pivot("LOW", 99.0, 3, 8, "HL")
        for i in range(1, 12):
            conf_now = [hl] if i == hl.confirmation_bar else []
            self.tm.on_bar(t, i, bars[i], conf_now, [], 1.0)
            if i < hl.confirmation_bar:
                self.assertEqual(t.current_stop, 95.0, "stop moved before the HL was confirmed")
        self.assertAlmostEqual(t.current_stop, 98.5)

    # 14 -- same-bar stop and target -> stop first
    def test_same_bar_stop_and_target_is_conservative(self):
        bars = bars_from_ohlc([(100, 100.5, 99.5, 100), (100, 106, 94, 101)])
        t = self.tm.open_trade("T1", FakeEval(), 100.0, 0, bars[0], 100, {})
        self.tm.on_bar(t, 0, bars[0], [], [], 1.0)
        self.tm.on_bar(t, 1, bars[1], [], [], 1.0)
        self.assertEqual(t.status, "CLOSED")
        self.assertEqual(t.exit_reason, "INITIAL_SL")
        self.assertFalse(any(t.targets_hit))
        self.assertLess(t.net_pnl, 0)

    def test_gap_through_stop_fills_at_open(self):
        bars = bars_from_ohlc([(100, 100.5, 99.5, 100), (90, 91, 89, 90.5)])
        t = self.tm.open_trade("T1", FakeEval(), 100.0, 0, bars[0], 10, {})
        self.tm.on_bar(t, 0, bars[0], [], [], 1.0)
        self.tm.on_bar(t, 1, bars[1], [], [], 1.0)
        self.assertLess(t.exit_price, 95.0)

    def test_partial_exit_quantities(self):
        bars = bars_from_ohlc([(100, 100.5, 99.5, 100), (100, 106, 99.8, 105.5), (105.5, 111, 105, 110.5), (110.5, 116, 110, 115.5)])
        t = self.tm.open_trade("T1", FakeEval(), 100.0, 0, bars[0], 101, {})
        for i, b in enumerate(bars):
            self.tm.on_bar(t, i, b, [], [], 1.0)
        exits = [f for f in t.fills if f["reason"] != "ENTRY"]
        self.assertEqual(sum(f["qty"] for f in exits), 101)
        self.assertEqual(t.exit_reason, "T3")
        self.assertEqual(t.remaining_qty, 0)

    def test_short_mirror(self):
        bars = bars_from_ohlc([(100, 100.5, 99.5, 100), (100, 100.2, 94, 94.5)])
        t = self.tm.open_trade("S1", FakeEval(100, 105, (95, 90, 85), "SHORT"), 100.0, 0, bars[0], 50, {})
        for i, b in enumerate(bars):
            self.tm.on_bar(t, i, b, [], [], 1.0)
        self.assertTrue(t.targets_hit[0])
        self.assertGreater(t.gross_pnl, 0)
        self.assertTrue(math.isfinite(t.net_pnl))


if __name__ == "__main__":
    unittest.main()
