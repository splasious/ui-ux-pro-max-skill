"""Mandatory tests 4, 5, 6, 15 plus whole-pipeline chronological integrity.

The strongest check is *truncation invariance*: everything the engine decided
at bar k must be identical whether the run stopped at bar k or continued.  A
look-ahead bug anywhere in the chain (pivots, zones, profile, HTF, derivatives,
positioning, scoring) breaks it.
"""
import json
import unittest
from datetime import date, datetime, timedelta

from swing_master.backtest.walk_forward import WalkForwardLab, make_folds
from swing_master.config import StrategyConfig
from swing_master.data.demo import DemoMarketData
from swing_master.data.resampler import HTFView, resample_weekly
from swing_master.positioning import PositioningSuite
from swing_master.schemas import Bar, PositioningRecord, to_jsonable
from swing_master.strategy.pipeline import analyze_symbol
from swing_master.tests.helpers import random_walk_bars

DEMO = DemoMarketData(start="2023-01-02", end="2024-12-31")


def fingerprint(ev):
    d = to_jsonable(ev.to_dict())
    return json.dumps(d, sort_keys=True)


class NoLookaheadTests(unittest.TestCase):
    def test_pipeline_truncation_invariance(self):
        cfg = StrategyConfig()
        pos = PositioningSuite([])
        for sym in ("NIFTY", "RELIANCE"):
            inst = DEMO.instrument(sym)
            bars = DEMO.daily_bars(sym)
            full = analyze_symbol(inst, bars, cfg, pos, DEMO)
            self.assertTrue(full.evaluations, "expected setup evaluations")
            for k in (220, 390):
                part = analyze_symbol(inst, bars[:k], cfg, pos, DEMO)
                a = [fingerprint(e) for e in full.evaluations if e.bar < k]
                b = [fingerprint(e) for e in part.evaluations]
                self.assertEqual(a, b, f"{sym}: evaluations before bar {k} changed when later data was added")

    # 4 -- no higher-timeframe leakage
    def test_no_htf_leakage(self):
        daily = random_walk_bars(120, start=date(2024, 1, 1))
        weekly = resample_weekly(daily)
        view = HTFView(weekly)
        for b in daily:
            for w in view.completed(b.close_time):
                self.assertLessEqual(w.close_time, b.close_time)
        # a Wednesday sees only weeks that ended on or before the previous Friday
        wed = next(b for b in daily if b.timestamp.weekday() == 2 and b.timestamp.date() > date(2024, 2, 1))
        done = view.completed(wed.close_time)
        self.assertTrue(done[-1].close_time.date() < wed.timestamp.date())
        # perturbing Thursday/Friday of the same week cannot change what Wednesday saw
        mutated = [Bar(b.timestamp, b.close_time, b.open, b.high * (2 if b.timestamp > wed.timestamp else 1), b.low,
                       b.close, b.volume) for b in daily]
        done2 = HTFView(resample_weekly(mutated)).completed(wed.close_time)
        self.assertEqual([(w.open, w.high, w.low, w.close) for w in done], [(w.open, w.high, w.low, w.close) for w in done2])

    # 6 -- positioning publication-time integrity
    def test_positioning_uses_only_published_records(self):
        recs = []
        start = datetime(2024, 1, 1, 20, 0)
        for k in range(40):
            pub = start + timedelta(days=k)
            recs.append(PositioningRecord("RETAIL", pub.date(), pub, pub + timedelta(hours=2), 100 + k, 100, "test", "DIRECT"))
        suite = PositioningSuite(recs, min_history=20)
        t = start + timedelta(days=30, hours=1)  # record 30 is published but not yet available
        snap = suite.snapshot(t)["RETAIL"]
        self.assertEqual(snap.observations, 30)
        self.assertEqual(snap.long, 129)
        self.assertEqual(suite.snapshot(start)["RETAIL"].status, "UNAVAILABLE")

    # 15 -- missing data never fabricates a signal
    def test_missing_positioning_is_unavailable_not_fabricated(self):
        snaps = PositioningSuite([]).snapshot(datetime(2025, 1, 1))
        for s in snaps.values():
            self.assertEqual(s.status, "UNAVAILABLE")
            self.assertIsNone(s.classification)
            self.assertIsNone(s.net)
        cfg = StrategyConfig()
        ds = analyze_symbol(DEMO.instrument("TCS"), DEMO.daily_bars("TCS"), cfg, PositioningSuite([]), DEMO)
        for ev in ds.evaluations:
            self.assertIsNone(ev.factor_fractions["smart_money"])
            self.assertIsNone(ev.factor_fractions["retail"])
            self.assertIsNone(ev.sub_fractions["pcr"], "TCS has no option chain in the demo")

    def test_derivatives_respect_publication_time(self):
        cfg = StrategyConfig().with_overrides(ENTRY_MODE="REVERSAL_CLOSE")  # decide at the bell
        ds = analyze_symbol(DEMO.instrument("NIFTY"), DEMO.daily_bars("NIFTY"), cfg, PositioningSuite([]), DEMO)
        for ev in ds.evaluations:
            if ev.oi:
                self.assertLess(date.fromisoformat(ev.oi["date"]), ev.timestamp.date(),
                                "EOD OI of the decision day is published after the close")
            self.assertIsNone(ev.pcr, "today's chain is not published at 15:30")

    def test_walk_forward_never_optimises_on_test(self):
        cfg = StrategyConfig()
        datasets = {s: analyze_symbol(DEMO.instrument(s), DEMO.daily_bars(s), cfg, PositioningSuite([]), DEMO)
                    for s in ("RELIANCE", "INFY", "HDFCBANK")}
        seen = []

        def runner(c, window):
            seen.append(window)
            from swing_master.backtest.engine import PortfolioBacktester
            from swing_master.backtest.metrics import compute_metrics
            res = PortfolioBacktester(datasets, c, (), window.start, window.end, force_close_at_end=True,
                                      record_rejections=False).run()
            return res, compute_metrics(res.trades, res.equity_curve, c.INITIAL_CAPITAL)

        lab = WalkForwardLab(datasets, cfg, grid={"MIN_CONFLUENCE_SCORE": [60, 70]}, runner=runner)
        # make folds short enough for two years of data
        import swing_master.backtest.walk_forward as wf
        orig = wf.make_folds
        wf.make_folds = lambda a, b: orig(a, b, 9, 3, 3, 3)
        try:
            out = lab.run()
        finally:
            wf.make_folds = orig
        self.assertTrue(out["folds"])
        tests = [w for kind, w in lab.requested_windows if kind == "test"]
        # per fold: every train/validate window requested before that fold's test run ends before the test starts
        idx = 0
        for kind, w in lab.requested_windows:
            if kind == "test":
                idx += 1
                continue
            fold_test = tests[idx]
            self.assertLess(w.end, fold_test.start, "selection must never see the test window")
        folds = make_folds(datetime(2022, 1, 1), datetime(2025, 1, 1))
        for tr, va, te in folds:
            self.assertLess(tr.end, va.start)
            self.assertLess(va.end, te.start)


if __name__ == "__main__":
    unittest.main()
