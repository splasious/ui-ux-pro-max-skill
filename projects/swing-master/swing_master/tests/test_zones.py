"""Zone creation, lifecycle and mandatory test 10: invalidated zones cannot trigger entries."""
import unittest

from swing_master.config import StrategyConfig
from swing_master.schemas import ZoneStatus
from swing_master.strategy.analyzer import SymbolAnalyzer
from swing_master.strategy.long_setup import LONG_SPEC
from swing_master.strategy.signal_engine import find_triggers
from swing_master.tests.helpers import bars_from_ohlc, random_walk_bars
from swing_master.zones.zone_lifecycle import update_zone


def feed(rows, cfg=None):
    cfg = cfg or StrategyConfig()
    an = SymbolAnalyzer("X", "1D", cfg)
    for b in bars_from_ohlc(rows):
        an.update(b)
    return an


# 20 quiet bars (ATR ~2), then a drop-base-rally pattern
QUIET = [(100, 101, 99, 100)] * 20
DBR = QUIET + [(100, 100.5, 97, 97.5), (97.5, 98.2, 97.2, 97.8), (97.8, 101.5, 97.6, 101.4)]


class ZoneTests(unittest.TestCase):
    def test_zone_created_on_leg_out_bar_not_before(self):
        an = feed(DBR)
        demand = [z for z in an.zones.zones if z.zone_type == "DEMAND"]
        self.assertEqual(len(demand), 1)
        z = demand[0]
        self.assertEqual(z.pattern, "DBR")
        self.assertEqual(z.creation_bar, len(DBR) - 1)
        self.assertEqual(z.origin_bar, len(DBR) - 2)
        self.assertAlmostEqual(z.proximal, 97.8)
        self.assertAlmostEqual(z.distal, 97.2)
        # before the leg-out bar the zone did not exist
        an2 = feed(DBR[:-1])
        self.assertFalse([z for z in an2.zones.zones if z.zone_type == "DEMAND"])

    def test_touch_and_close_invalidation(self):
        rows = DBR + [(101.4, 102, 100, 101.8), (101.8, 102, 97.7, 99.0), (99, 100.5, 98.5, 100.2), (100.2, 100.4, 97.0, 97.1)]
        an = feed(rows)
        z = [z for z in an.zones.zones if z.zone_type == "DEMAND"][0]
        self.assertEqual(z.status_as_of(len(DBR)), ZoneStatus.FRESH)
        self.assertEqual(z.status_as_of(len(DBR) + 1), ZoneStatus.TESTED_ONCE)
        self.assertEqual(z.status_as_of(len(rows) - 1), ZoneStatus.INVALIDATED)
        self.assertEqual(z.invalidation_bar, len(rows) - 1)

    def test_wick_vs_close_invalidation(self):
        cfg = StrategyConfig()
        base = DBR + [(101.4, 102, 97.0, 98.0)]  # wick below distal (97.2), close above
        close_mode = feed(base, cfg)
        z = [z for z in close_mode.zones.zones if z.zone_type == "DEMAND"][0]
        self.assertIsNone(z.invalidation_bar)
        wick_mode = feed(base, cfg.with_overrides(ZONE_INVALIDATION_MODE="WICK"))
        z2 = [z for z in wick_mode.zones.zones if z.zone_type == "DEMAND"][0]
        self.assertEqual(z2.invalidation_bar, len(base) - 1)

    def test_invalidated_zone_cannot_trigger(self):
        cfg = StrategyConfig()
        an = SymbolAnalyzer("X", "1D", cfg)
        for b in random_walk_bars(500, seed=4):
            an.update(b)
            atr = an.atr
            if not atr:
                continue
            for trig, zone in find_triggers(an, LONG_SPEC, an.bars[-1], atr, cfg):
                if trig == "ZONE":
                    self.assertFalse(zone.is_invalidated_as_of(an.i))
                    self.assertLess(zone.creation_bar, an.i)

    def test_lifecycle_ignores_creation_bar(self):
        an = feed(DBR)
        z = [z for z in an.zones.zones if z.zone_type == "DEMAND"][0]
        update_zone(z, z.creation_bar, an.bars[-1])
        self.assertEqual(z.touches, [])


if __name__ == "__main__":
    unittest.main()
