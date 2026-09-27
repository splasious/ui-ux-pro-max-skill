"""Positioning statistics, derivatives classification / PCR safety, candlestick definitions, scoring."""
import unittest
from datetime import date, datetime, timedelta

from swing_master.derivatives.futures_oi import classify_oi
from swing_master.derivatives.pcr import compute_pcr
from swing_master.positioning import PositioningSuite, classify_percentile, divergence
from swing_master.price_action.candlesticks import detect_patterns
from swing_master.schemas import OptionChainSnapshot, OptionStrike, PositioningRecord
from swing_master.tests.helpers import bars_from_ohlc
from swing_master.zones.zone_quality import score_components

W = {"a": {"name": "A", "weight": 60, "component": "x"}, "b": {"name": "B", "weight": 40, "component": "y"}}


class AnalyticsTests(unittest.TestCase):
    def test_oi_states(self):
        self.assertEqual(classify_oi(1.0, 2.0), "LONG BUILD-UP")
        self.assertEqual(classify_oi(-1.0, 2.0), "SHORT BUILD-UP")
        self.assertEqual(classify_oi(1.0, -2.0), "SHORT COVERING")
        self.assertEqual(classify_oi(-1.0, -2.0), "LONG UNWINDING")
        self.assertEqual(classify_oi(0.01, 5.0), "NEUTRAL")

    def chain(self, strikes, rollover=False):
        return OptionChainSnapshot("NIFTY", date(2024, 1, 2), date(2024, 1, 4), 100.0, strikes,
                                   datetime(2024, 1, 2, 18, 30), rollover)

    def test_pcr_zero_and_negative_denominators(self):
        s = [OptionStrike(90 + 5 * k, 0.0, 100.0, -10.0, 5.0) for k in range(5)]
        info = compute_pcr(self.chain(s), 2)
        self.assertFalse(info["available"])  # call OI zero -> PCR undefined, never inf
        s2 = [OptionStrike(90 + 5 * k, 100.0, 150.0, -10.0, 5.0) for k in range(5)]
        info2 = compute_pcr(self.chain(s2), 2)
        self.assertAlmostEqual(info2["pcr"], 1.5)
        self.assertIsNone(info2["change_oi_pcr"])
        self.assertIn("<= 0", info2["change_oi_pcr_reason"])
        info3 = compute_pcr(self.chain(s2, rollover=True), 2)
        self.assertIsNone(info3["change_oi_pcr"])
        self.assertIn("rollover", info3["change_oi_pcr_reason"].lower())

    def test_illiquid_strikes_reported(self):
        s = [OptionStrike(90 + 5 * k, 5000.0 if k != 1 else 1.0, 5000.0 if k != 1 else 1.0, 1, 1) for k in range(5)]
        info = compute_pcr(self.chain(s), 2, min_oi=1000)
        self.assertEqual(info["skipped_illiquid"], [95])

    def test_percentile_classification_and_divergence(self):
        self.assertEqual(classify_percentile(5), "STRONG SHORT")
        self.assertEqual(classify_percentile(50), "NEUTRAL")
        self.assertEqual(classify_percentile(95), "STRONG LONG")
        t0 = datetime(2024, 1, 1, 20)
        recs = []
        for k in range(30):
            t = t0 + timedelta(days=k)
            recs.append(PositioningRecord("INSTITUTIONAL", t.date(), t, t, 100 + 3 * k, 100, "t", "DIRECT"))
            recs.append(PositioningRecord("RETAIL", t.date(), t, t, 100, 100 + 3 * k, "t", "DIRECT"))
        snaps = PositioningSuite(recs).snapshot(t0 + timedelta(days=40))
        self.assertEqual(snaps["INSTITUTIONAL"].classification, "STRONG LONG")
        self.assertEqual(snaps["RETAIL"].classification, "STRONG SHORT")
        self.assertEqual(snaps["INSTITUTIONAL"].observations, 30)
        dv = divergence(snaps["COMMERCIAL"], snaps["INSTITUTIONAL"], snaps["RETAIL"])
        self.assertEqual(dv["signal"], "BULLISH POSITIONING DIVERGENCE")

    def test_candlestick_definitions(self):
        base = [(100, 101, 99, 100)] * 20
        engulf = bars_from_ohlc(base + [(100, 100.3, 98, 98.2), (98.0, 101.2, 97.9, 101.0)])
        names = {p.pattern for p in detect_patterns(engulf, len(engulf) - 1, 2.0)}
        self.assertIn("BULLISH ENGULFING", names)
        hammer = bars_from_ohlc(base + [(100, 100.2, 96, 99.9)])
        self.assertIn("HAMMER", {p.pattern for p in detect_patterns(hammer, len(hammer) - 1, 2.0)})
        star = bars_from_ohlc(base + [(100, 104, 99.8, 100.1)])
        self.assertIn("SHOOTING STAR", {p.pattern for p in detect_patterns(star, len(star) - 1, 2.0)})
        tiny = bars_from_ohlc(base + [(100, 100.1, 99.9, 100.05)])
        self.assertEqual(detect_patterns(tiny, len(tiny) - 1, 2.0), [])

    def test_score_policies(self):
        fr = {"a": 1.0, "b": None}
        self.assertEqual(score_components(fr, W, "RENORMALIZE")["score"], 100.0)
        self.assertEqual(score_components(fr, W, "ZERO")["score"], 60.0)
        out = score_components(fr, W, "RENORMALIZE", disabled={"x"})
        self.assertEqual(out["total_points"], 40.0)
        self.assertEqual(out["coverage"], 0.0)


if __name__ == "__main__":
    unittest.main()
