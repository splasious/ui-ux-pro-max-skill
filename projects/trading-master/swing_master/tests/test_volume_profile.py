"""Volume profile correctness and mandatory test 5: no future leakage."""
import unittest

from swing_master.schemas import Bar
from swing_master.tests.helpers import bars_from_ohlc, random_walk_bars
from swing_master.volume_profile.profile import build_profile, profile_window
from swing_master.volume_profile.value_area import value_area


class VolumeProfileTests(unittest.TestCase):
    def test_poc_and_value_area(self):
        rows = [(100, 101, 99, 100)] * 10 + [(105, 106, 104, 105)] * 2
        bars = bars_from_ohlc(rows)
        vp = build_profile(bars, 0, len(bars) - 1, bins=14)
        self.assertTrue(99 <= vp.poc <= 101)
        self.assertLessEqual(vp.val, vp.poc)
        self.assertGreaterEqual(vp.vah, vp.poc)
        lo = int((vp.val - vp.price_low) / vp.bin_size + 1e-9)
        hi = int(round((vp.vah - vp.price_low) / vp.bin_size)) - 1
        self.assertGreaterEqual(sum(vp.volumes[lo:hi + 1]), 0.70 * sum(vp.volumes) - 1e-6)
        self.assertAlmostEqual(sum(vp.volumes), vp.total_volume, places=6)

    def test_value_area_expands_to_percent(self):
        vols = [1, 2, 3, 10, 3, 2, 1]
        lo, hi = value_area(vols, 3, 0.7)
        self.assertGreaterEqual(sum(vols[lo:hi + 1]), 0.7 * sum(vols))

    def test_no_future_leakage(self):
        bars = random_walk_bars(300)
        end = 200
        before = build_profile(bars, end - 119, end, 50)
        mutated = list(bars[:end + 1]) + [Bar(b.timestamp, b.close_time, b.open * 3, b.high * 3, b.low * 3, b.close * 3,
                                              b.volume * 50) for b in bars[end + 1:]]
        after = build_profile(mutated, end - 119, end, 50)
        self.assertEqual(before.volumes, after.volumes)
        self.assertEqual((before.poc, before.vah, before.val), (after.poc, after.vah, after.val))

    def test_windows_end_at_evaluation_bar(self):
        bars = random_walk_bars(200)
        for kind in ("FIXED", "SWING", "STRUCTURAL_LEG", "DAILY", "WEEKLY", "HIGHER_TF"):
            s, e = profile_window(kind, bars, 150, [], 120)
            self.assertLessEqual(e, 150)
            self.assertLessEqual(s, e)


if __name__ == "__main__":
    unittest.main()
