"""Mandatory test 1: a pivot is unavailable before its confirmation (plus ZigZag correctness)."""
import unittest

from swing_master.indicators.atr import ATR, atr_series
from swing_master.structure.pivots import PivotStore
from swing_master.structure.zigzag import ZigZagEngine
from swing_master.tests.helpers import bars_from_closes, random_walk_bars


def run_zigzag(bars, method="PERCENT", pct=5.0, mult=2.0):
    zz, atr = ZigZagEngine(method, pct, mult), ATR(14)
    for i, b in enumerate(bars):
        zz.update(i, b, atr.update(b.high, b.low, b.close))
    return zz


class ZigZagTests(unittest.TestCase):
    def test_simple_swing_percent(self):
        closes = [100, 102, 104, 106, 108, 110, 107, 104, 101, 99, 100, 103, 106, 109, 112]
        zz = run_zigzag(bars_from_closes(closes, spread=0.0), "PERCENT", 5.0)
        high = zz.pivots[1] if zz.pivots[0].pivot_type == "LOW" else zz.pivots[0]
        self.assertEqual(high.pivot_type, "HIGH")
        self.assertAlmostEqual(high.pivot_price, 110.0)
        self.assertEqual(high.pivot_bar, 5)
        # 110 -> 104 is a 5.45% reversal: confirmed on bar 7, not on bar 5 or 6
        self.assertEqual(high.confirmation_bar, 7)

    def test_pivot_unavailable_before_confirmation(self):
        bars = random_walk_bars(300)
        zz = run_zigzag(bars, "ATR")
        self.assertGreater(len(zz.pivots), 10)
        for p in zz.pivots:
            self.assertGreater(p.confirmation_bar, p.pivot_bar)
            before = bars[p.confirmation_bar - 1].close_time
            self.assertFalse(p.available_at(before), "pivot must not be usable before confirmation")
            self.assertTrue(p.available_at(bars[p.confirmation_bar].close_time))
        store = PivotStore(zz.pivots)
        for i in range(len(bars)):
            for p in store.confirmed_as_of(i):
                self.assertLessEqual(p.confirmation_bar, i)

    def test_truncation_invariance(self):
        """Pivots confirmed by bar k are identical whether or not later bars exist (no repainting)."""
        bars = random_walk_bars(400, seed=11)
        full = run_zigzag(bars, "HYBRID").pivots
        for k in (120, 200, 333):
            part = run_zigzag(bars[:k], "HYBRID").pivots
            expect = [(p.pivot_type, p.pivot_bar, p.pivot_price, p.confirmation_bar) for p in full if p.confirmation_bar < k]
            got = [(p.pivot_type, p.pivot_bar, p.pivot_price, p.confirmation_bar) for p in part]
            self.assertEqual(expect, got)

    def test_alternation(self):
        pivots = run_zigzag(random_walk_bars(500, seed=5), "ATR").pivots
        for a, b in zip(pivots, pivots[1:]):
            self.assertNotEqual(a.pivot_type, b.pivot_type)
            self.assertLessEqual(a.confirmation_bar, b.confirmation_bar)

    def test_atr_series_matches_incremental(self):
        bars = random_walk_bars(60)
        s = atr_series(bars, 14)
        self.assertIsNone(s[12])
        self.assertIsNotNone(s[13])


if __name__ == "__main__":
    unittest.main()
