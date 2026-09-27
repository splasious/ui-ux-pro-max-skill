"""Mandatory test 2: HH/HL/LH/LL come only from confirmed pivots; BOS/CHoCH semantics."""
import unittest
from datetime import datetime

from swing_master.config import StrategyConfig
from swing_master.schemas import Pivot, Trend
from swing_master.strategy.analyzer import SymbolAnalyzer
from swing_master.structure.market_structure import MarketStructure
from swing_master.tests.helpers import random_walk_bars


def pv(kind, price, bar):
    t = datetime(2024, 1, 1)
    return Pivot(kind, price, bar, t, bar + 2, t, 1.0, 1.0, 1.0)


class StructureTests(unittest.TestCase):
    def test_labels_and_trend(self):
        ms = MarketStructure(0.0)
        for kind, price, bar in [("LOW", 100, 0), ("HIGH", 110, 5), ("LOW", 104, 9), ("HIGH", 115, 14)]:
            ms.add_pivot(pv(kind, price, bar), atr=1.0)
        self.assertEqual([p.label for p in ms.lows], [None, "HL"])
        self.assertEqual([p.label for p in ms.highs], [None, "HH"])
        self.assertEqual(ms.trend, Trend.BULLISH)

    def test_single_violation_is_not_a_reversal(self):
        ms = MarketStructure(0.0)
        for kind, price, bar in [("LOW", 100, 0), ("HIGH", 110, 5), ("LOW", 104, 9), ("HIGH", 115, 14), ("LOW", 102, 20)]:
            ms.add_pivot(pv(kind, price, bar), atr=1.0)
        self.assertEqual(ms.lows[-1].label, "LL")
        self.assertEqual(ms.trend, Trend.TRANSITION, "one LL inside an uptrend must not flip the trend to BEARISH")
        ms.add_pivot(pv("HIGH", 108, 25), atr=1.0)
        self.assertEqual(ms.trend, Trend.BEARISH)

    def test_labels_only_from_confirmed_pivots(self):
        cfg = StrategyConfig()
        an = SymbolAnalyzer("X", "1D", cfg)
        for i, b in enumerate(random_walk_bars(300, seed=9)):
            an.update(b)
            for p in an.structure.highs + an.structure.lows:
                self.assertLessEqual(p.confirmation_bar, i)
            # trend recorded at bar i derives only from pivots confirmed <= i
            self.assertEqual(an.structure.trend_as_of(i), an.trend_by_bar[i])

    def test_choch_does_not_change_trend(self):
        cfg = StrategyConfig()
        an = SymbolAnalyzer("X", "1D", cfg)
        for b in random_walk_bars(500, seed=21):
            before = an.structure.trend
            n_events = len(an.events.events)
            n_pivots = len(an.pivots.pivots)
            an.update(b)
            new_events = an.events.events[n_events:]
            if new_events and len(an.pivots.pivots) == n_pivots:
                # an event on a bar that confirmed no pivot can never alter the HH/HL trend
                self.assertEqual(an.structure.trend, before)
        types = {e.event_type for e in an.events.events}
        self.assertTrue(types <= {"BOS", "CHOCH"})
        self.assertTrue(an.events.events, "expected some structure events on a 500-bar walk")


if __name__ == "__main__":
    unittest.main()
