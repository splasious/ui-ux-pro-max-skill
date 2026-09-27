"""Platform-level features: portfolio-risk exits, scanner timeframes, MTF context, proposals, persistence."""
import tempfile
import time
import unittest
from pathlib import Path

from swing_master.app import Platform
from swing_master.backtest.engine import PortfolioBacktester
from swing_master.config import AppSettings, StrategyConfig
from swing_master.data.demo import DemoMarketData
from swing_master.dashboard import api

SYMBOLS = ["NIFTY", "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "LT"]


class PlatformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        settings = AppSettings()
        settings.STATE_DIR = Path(cls.tmp.name)
        provider = DemoMarketData(start="2023-01-02", end="2025-06-30")
        cls.p = Platform(settings, provider=provider, symbols=SYMBOLS)

    @classmethod
    def tearDownClass(cls):
        for _ in range(100):  # let the background persistence finish before the temp dir goes away
            if cls.p.persist_state != "running":
                break
            time.sleep(0.1)
        cls.tmp.cleanup()

    def test_drawdown_halt_flattens_and_stops_entries(self):
        cfg = StrategyConfig().with_overrides(MAX_DRAWDOWN_HALT=0.001)
        res = PortfolioBacktester(self.p.datasets, cfg).run()
        halts = [e for e in res.events if e["type"] == "RISK_LIMIT_REACHED" and "halt" in e.get("reason", "")]
        self.assertEqual(len(halts), 1, "halt fires once")
        halt_time = halts[0]["time"]
        later = [t for t in res.trades + res.open_trades if t.entry_time.isoformat() > halt_time]
        self.assertEqual(later, [], "no new entries after the drawdown halt")
        self.assertFalse(res.open_trades)
        self.assertTrue(any(t.exit_reason == "PORTFOLIO_RISK" for t in res.trades) or not res.trades)

    def test_daily_loss_flatten(self):
        cfg = StrategyConfig().with_overrides(MAX_DAILY_LOSS=0.0001)
        res = PortfolioBacktester(self.p.datasets, cfg).run()
        flat = [t for t in res.trades if t.exit_reason == "PORTFOLIO_RISK"]
        self.assertTrue(flat, "a tiny daily-loss limit must flatten positions at least once")

    def test_scanner_other_timeframe(self):
        out = api.scanner(self.p, tf="1W")
        self.assertEqual(out["timeframe"], "1W")
        self.assertEqual(out["funnel"]["universe"], len(SYMBOLS))

    def test_mtf_context(self):
        m = api.mtf_payload(self.p, "RELIANCE")
        tfs = [r["timeframe"] for r in m["rows"]]
        self.assertEqual(tfs, ["1M", "1W", "1D", "4H", "1H"])
        self.assertIn(m["verdict"], ("ALIGNED BULLISH", "ALIGNED BEARISH", "MOSTLY BULLISH", "MOSTLY BEARISH", "MIXED"))
        for r in m["rows"]:
            self.assertTrue(r["available"])
            self.assertLessEqual(r["as_of"], self.p.as_of.isoformat())

    def test_proposals_require_semi_auto(self):
        props = self.p.proposals()
        self.assertEqual(props["mode"], "PAPER")
        for item in props["items"]:
            self.assertFalse(item["confirmable"], "nothing is user-confirmable outside SEMI_AUTO")
        ready = [i for i in props["items"] if i["scanner_status"] == "READY"]
        self.p.execution_mode = "SEMI_AUTO"
        try:
            for item in self.p.proposals()["items"]:
                if item["scanner_status"] != "READY":
                    with self.assertRaises(PermissionError):
                        self.p.decide_proposal(item["id"], True)
            if ready:
                out = self.p.decide_proposal(ready[0]["id"], True)
                sent = [i for i in out["items"] if i["id"] == ready[0]["id"]][0]
                self.assertEqual(sent["status"], "SENT")
        finally:
            self.p.execution_mode = "PAPER"

    def test_persistence_writes_raw_and_derived(self):
        for _ in range(300):
            if self.p.persist_state != "running":
                break
            time.sleep(0.1)
        self.assertEqual(self.p.persist_state, "done")
        repo = self.p.repo
        self.assertGreater(repo.count("ohlcv"), 1000)
        self.assertGreater(repo.count("futures_oi"), 1000)
        self.assertGreater(repo.count("derived_bars"), 100)
        self.assertEqual(repo.count("volume_profiles"), len(SYMBOLS))
        self.assertGreater(repo.count("pivots"), 50)
        self.assertGreater(repo.count("system_logs"), 10)
        self.assertEqual(repo.count("options_snapshots"), 1)  # NIFTY is the only option underlying here

    def test_split_static_export(self):
        import json
        import re
        from swing_master.dashboard.export_static import export_split
        with tempfile.TemporaryDirectory() as tmp:
            page, n, total = export_split(self.p, tmp)
            html = (Path(tmp) / "index.html").read_text()
            snap = json.loads(re.search(r"window.__SM_SNAPSHOT__ = (.*?);</script>", html, re.S).group(1))
            self.assertEqual(set(snap["data"]), {"/api/meta", "/api/overview"})
            self.assertEqual(len(snap["files"]), n)
            self.assertGreater(total, page, "view data lives in the lazy files, not the page")
            key = "/api/chart?profile=FIXED&symbol=RELIANCE&tf=1D"
            chart = json.loads((Path(tmp) / snap["files"][key]).read_text())
            self.assertEqual(chart["symbol"], "RELIANCE")
            self.assertEqual(len(list((Path(tmp) / "d").iterdir())), n)
            self.assertIn('localStorage.getItem("sm.skin"', html)

    def test_audit_log_categories(self):
        cats = set(api.health_payload(self.p)["log_counts"])
        for c in ("pivot", "structure", "zone", "signal"):
            self.assertIn(c, cats)


if __name__ == "__main__":
    unittest.main()
