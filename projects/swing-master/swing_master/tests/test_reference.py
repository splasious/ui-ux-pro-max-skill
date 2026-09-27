"""Cross-validation: the standalone reference strategy and the production engine must agree."""
import importlib.util
import sys
import unittest
from pathlib import Path

from swing_master.indicators.atr import atr_series
from swing_master.risk.position_size import position_size
from swing_master.structure.market_structure import MarketStructure
from swing_master.structure.zigzag import ZigZagEngine
from swing_master.tests.helpers import random_walk_bars
from swing_master.volume_profile.profile import build_profile

REF_PATH = Path(__file__).resolve().parents[2] / "research" / "reference_strategy.py"
spec = importlib.util.spec_from_file_location("reference_strategy", REF_PATH)
ref = importlib.util.module_from_spec(spec)
sys.modules["reference_strategy"] = ref
spec.loader.exec_module(ref)


def to_candles(bars):
    return [ref.Candle(b.timestamp.isoformat(), b.open, b.high, b.low, b.close, b.volume) for b in bars]


class ReferenceAgreementTests(unittest.TestCase):
    def setUp(self):
        self.bars = random_walk_bars(600, seed=17)
        self.candles = to_candles(self.bars)

    def test_atr_agrees(self):
        a, b = atr_series(self.bars, 14), ref.wilder_atr(self.candles, 14)
        for x, y in zip(a, b):
            if x is None or y is None:
                self.assertEqual(x, y)
            else:
                self.assertAlmostEqual(x, y, places=9)

    def test_pivots_and_labels_agree(self):
        atr = atr_series(self.bars, 14)
        for method in ("ATR", "PERCENT", "HYBRID"):
            zz, ms = ZigZagEngine(method, 5.0, 2.0), MarketStructure(0.1)
            for i, b in enumerate(self.bars):
                p = zz.update(i, b, atr[i])
                if p:
                    ms.add_pivot(p, atr[i])
            rp = ref.confirmed_zigzag(self.candles, ref.wilder_atr(self.candles), 2.0, 5.0, method)
            ref.label_pivots(rp, ref.wilder_atr(self.candles), 0.1)
            prod = [(p.pivot_type[0], p.pivot_bar, round(p.pivot_price, 8), p.confirmation_bar, p.label) for p in zz.pivots]
            refs = [(p.kind, p.bar, round(p.price, 8), p.confirm_bar, p.label) for p in rp]
            self.assertEqual(prod, refs, method)

    def test_volume_profile_agrees(self):
        for end in (150, 400, 599):
            vp = build_profile(self.bars, end - 119, end, 50, 0.70)
            rv = ref.volume_profile(self.candles, end - 119, end, 50, 0.70)
            self.assertAlmostEqual(vp.poc, rv["poc"], places=6)
            self.assertAlmostEqual(vp.vah, rv["vah"], places=6)
            self.assertAlmostEqual(vp.val, rv["val"], places=6)

    def test_sizing_agrees(self):
        for entry, stop, lot in [(100, 95, 1), (2450.5, 2390.1, 1), (31800, 31150, 75), (50, 50, 1)]:
            p = position_size(1_000_000, 0.01, entry, stop, lot, 0.2)
            self.assertEqual(p.quantity, ref.size_position(1_000_000, 0.01, entry, stop, lot, 0.2))

    def test_reference_backtest_runs(self):
        res = ref.run(self.candles)
        self.assertGreater(res["pivots"], 20)
        self.assertGreaterEqual(res["trades"], 0)


if __name__ == "__main__":
    unittest.main()
