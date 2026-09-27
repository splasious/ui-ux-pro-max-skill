"""TradingMaster provider against a local fake of its REST API (same routes and response shapes)."""
import json
import random
import tempfile
import threading
import unittest
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from swing_master.app import Platform
from swing_master.config import AppSettings
from swing_master.dashboard import api
from swing_master.data.tradingmaster import TradingMasterClient, TradingMasterData, TradingMasterError
from swing_master.derivatives.pcr import compute_pcr

NOW = datetime(2026, 9, 28, 10, 0)  # Monday 10:00 IST: today's daily bar is still forming
LAST = date(2026, 9, 25)
IDS = {"NIFTY 50": "u-nifty", "RELIANCE": "u-rel", "TCS": "u-tcs", "NEWCO": "u-new", "INDIA VIX": "u-vix"}
FUTS = [("RELIANCE26SEPFUT", "f-rel-sep", "u-rel", "2026-09-29", 500),
        ("RELIANCE26OCTFUT", "f-rel-oct", "u-rel", "2026-10-27", 500),
        ("NIFTY26SEPFUT", "f-nif-sep", "u-nifty", "2026-09-29", 75)]


def _days(n, end=LAST):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def _utc_daily(d):  # Kite stamps a daily candle 00:00 IST, i.e. 18:30 UTC the previous day
    return (datetime(d.year, d.month, d.day) - timedelta(hours=5, minutes=30)).isoformat() + "+00:00"


def _daily_series(seed, n, base, oi=None):
    rng = random.Random(seed)
    rows, px = [], base
    for k, d in enumerate(_days(n)):
        o = px
        c = max(1.0, o * (1 + rng.gauss(0.0004, 0.012)))
        h, lo = max(o, c) * (1 + abs(rng.gauss(0, 0.004))), min(o, c) * (1 - abs(rng.gauss(0, 0.004)))
        row = {"ts": _utc_daily(d), "open": round(o, 2), "high": round(h, 2), "low": round(lo, 2),
               "close": round(c, 2), "volume": 1e6 + k}
        if oi is not None:
            row["open_interest"] = oi + 1000 * k
        rows.append(row)
        px = c
    return rows


def _build_candles():
    candles = {
        ("u-nifty", "1d"): _daily_series("n", 300, 24000.0),
        ("u-rel", "1d"): _daily_series("r", 300, 1400.0),
        ("u-tcs", "1d"): _daily_series("t", 300, 3100.0),
        ("u-new", "1d"): _daily_series("x", 40, 500.0),
        ("u-vix", "1d"): _daily_series("v", 300, 13.0),
        ("f-rel-sep", "1d"): _daily_series("rs", 60, 1405.0, oi=2_000_000),
        ("f-rel-oct", "1d"): _daily_series("ro", 20, 1410.0, oi=300_000),
        ("f-nif-sep", "1d"): _daily_series("ns", 60, 24050.0, oi=9_000_000),
    }
    # a forming bar for today and one inconsistent row (high below close) -- both must be dropped
    candles[("u-rel", "1d")].append({"ts": _utc_daily(NOW.date()), "open": 1, "high": 2, "low": 1, "close": 2, "volume": 1})
    bad = dict(candles[("u-tcs", "1d")][150])
    bad["high"] = bad["close"] - 5
    candles[("u-tcs", "1d")][150] = bad
    # 60-minute bars for RELIANCE: 5 sessions + today's first (completed) and second (forming) bar
    intraday = []
    for d in _days(5) + [NOW.date()]:
        for k in range(7):
            ts = datetime(d.year, d.month, d.day, 9, 15) + timedelta(hours=k)
            if d == NOW.date() and k > 0:
                break
            utc = (ts - timedelta(hours=5, minutes=30)).isoformat() + "Z"
            intraday.append({"ts": utc, "open": 1400 + k, "high": 1405 + k, "low": 1398 + k, "close": 1402 + k, "volume": 100})
    candles[("u-rel", "60m")] = intraday
    return candles


CANDLES = _build_candles()


def _leg(strike, kind, oi):
    return {"instrument_id": f"{kind}{strike}", "symbol": f"RELIANCE26SEP{int(strike)}{kind}", "ltp": 10.0,
            "ltp_change": 1.0, "open_interest": oi, "open_interest_change": 999.0, "as_of": "2026-09-25T10:00:00+00:00"}


class FakeTradingMaster(BaseHTTPRequestHandler):
    tokens = {"tok-1"}
    logins = 0
    expire_after = None  # when set, tok-1 stops working after this many GETs
    naive_store = False  # when set, behave like TradingMaster on SQLite (aware `start` -> HTTP 500)
    gets = 0

    def log_message(self, *args):
        pass

    def _json(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path != "/api/v1/auth/login" or body != {"email": "sm@example.com", "password": "pw"}:
            return self._json(401, {"detail": "Invalid email or password"})
        cls = type(self)
        cls.logins += 1
        token = f"tok-{cls.logins}"
        cls.tokens.add(token)
        return self._json(200, {"access_token": token, "token_type": "bearer", "expires_in": 1800})

    def do_GET(self):
        cls = type(self)
        cls.gets += 1
        token = (self.headers.get("Authorization") or "").removeprefix("Bearer ")
        if cls.expire_after is not None and cls.gets > cls.expire_after:
            cls.tokens.discard("tok-1")
        if token not in cls.tokens:
            return self._json(401, {"detail": "Could not validate credentials"})
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        path = url.path.removeprefix("/api/v1")
        if path == "/options/underlyings":
            return self._json(200, [{"instrument_id": IDS[s], "symbol": s} for s in ("NEWCO", "NIFTY 50", "RELIANCE", "TCS")])
        if path == "/instruments" and q.get("exchange") == "NSE":
            rows = [{"id": i, "exchange": "NSE", "symbol": s, "name": s.title(), "instrument_type": "equity",
                     "data_source": "zerodha_kite", "is_active": True} for s, i in IDS.items()]
            return self._json(200, rows)
        if path == "/instruments" and q.get("exchange") == "NFO":
            return self._json(200, [{"id": i, "exchange": "NFO", "symbol": s, "name": s, "instrument_type": "future",
                                     "data_source": "zerodha_kite", "is_active": True, "expiry": e, "lot_size": lot,
                                     "underlying_instrument_id": u} for s, i, u, e, lot in FUTS if q.get("q", "") in s])
        if path == "/market-data/candles":
            rows = CANDLES.get((q["instrument_id"], q["timeframe"]), [])
            if "start" not in q:
                return self._json(200, rows)
            start = datetime.fromisoformat(q["start"])
            if cls.naive_store and start.tzinfo is not None:  # SQLite-backed TradingMaster: naive vs aware -> 500
                return self._json(500, {"detail": "Internal Server Error"})
            return self._json(200, [r for r in rows if datetime.fromisoformat(r["ts"].replace("Z", "+00:00")) >= start])
        if path.endswith("/expiries"):
            uid = path.split("/")[2]
            if uid == "u-rel":
                return self._json(200, [{"expiry": "2026-09-29", "future_count": 1, "option_count": 40},
                                        {"expiry": "2026-10-27", "future_count": 1, "option_count": 40}])
            return self._json(200, [{"expiry": "2026-09-29", "future_count": 1, "option_count": 0}] if uid == "u-nifty" else [])
        if path.endswith("/chain"):
            strikes = [1360.0 + 20 * k for k in range(5)]
            return self._json(200, [{"strike": s, "call": _leg(s, "CE", 1000 * (k + 1)), "put": _leg(s, "PE", 1500 * (5 - k))}
                                    for k, s in enumerate(strikes)])
        return self._json(404, {"detail": "Not Found"})


class TradingMasterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeTradingMaster)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}/api/v1"
        cls.p = TradingMasterData(TradingMasterClient(cls.base, "sm@example.com", "pw"), history_days=1825, workers=3,
                                  now=lambda: NOW)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_universe_is_fno_underlyings_with_enough_history(self):
        syms = [i.symbol for i in self.p.universe()]
        self.assertEqual(syms, ["NIFTY", "RELIANCE", "TCS"])
        self.assertIn("NEWCO", self.p.skipped)
        rel = self.p.instrument("RELIANCE")
        self.assertEqual((rel.lot_size, rel.sector, rel.has_futures, rel.has_options, rel.strike_step), (500, "Energy", True, True, 20.0))
        nifty = self.p.instrument("NIFTY")
        self.assertTrue(nifty.is_index)
        self.assertEqual(nifty.lot_size, 75)
        self.assertTrue(self.p.instrument("TCS").has_futures, "every TradingMaster underlying is an F&O stock")

    def test_daily_bars_are_ist_dated_complete_and_valid(self):
        bars = self.p.daily_bars("RELIANCE")
        self.assertEqual(bars[-1].timestamp.date(), LAST, "today's forming bar is dropped")
        self.assertEqual(bars[-1].close_time, datetime(2026, 9, 25, 15, 30))
        self.assertEqual(len(bars), 300)
        self.assertEqual(len(self.p.daily_bars("TCS")), 299)
        self.assertEqual(self.p.dropped["TCS"], 1)
        self.assertEqual(len(self.p.volatility_index()), 300)

    def test_futures_oi_uses_nearest_contract(self):
        oi = self.p.futures_oi("RELIANCE")
        self.assertEqual(len(oi), 60)
        last = oi[-1]
        self.assertEqual(last.trade_date, LAST)
        self.assertEqual(last.open_interest, 2_000_000 + 1000 * 59, "September contract, not October")
        self.assertEqual(last.change_in_oi, 1000)
        self.assertEqual(last.available_at, datetime(2026, 9, 25, 18, 30))
        self.assertEqual(self.p.futures_oi("TCS"), [])

    def test_option_chain_latest_session_only(self):
        chain = self.p.option_chain("RELIANCE", LAST)
        self.assertIsNotNone(chain)
        self.assertEqual(chain.expiry, date(2026, 9, 29))
        self.assertEqual([s.call_oi for s in chain.strikes], [1000, 2000, 3000, 4000, 5000])
        self.assertIsNone(self.p.option_chain("RELIANCE", date(2026, 9, 24)))
        pcr = compute_pcr(chain, n_each_side=5)
        self.assertTrue(pcr["available"])
        self.assertIsNone(pcr["change_oi_pcr"])
        self.assertIn("previous session", pcr["change_oi_pcr_reason"])

    def test_intraday_completed_bars_only(self):
        h1 = self.p.intraday_bars("RELIANCE", "1H", 10)
        self.assertEqual(h1[-1].timestamp, datetime(2026, 9, 25, 15, 15), "today's 09:15 bar ends at 10:15, after NOW")
        self.assertEqual(h1[-1].close_time, datetime(2026, 9, 25, 15, 30))
        self.assertEqual(len(h1), 5 * 7)
        h4 = self.p.intraday_bars("RELIANCE", "4H", 2)
        self.assertEqual([b.timestamp.hour for b in h4[:2]], [9, 13])
        with self.assertRaises(Exception):
            self.p.intraday_bars("TCS", "1H", 5)

    def test_relogin_after_token_expiry(self):
        FakeTradingMaster.expire_after = FakeTradingMaster.gets  # tok-1 is rejected from the next request on
        try:
            client = TradingMasterClient(self.base, "sm@example.com", "pw", token="tok-1")
            self.assertEqual(len(client.get("/options/underlyings")), 4)
            self.assertNotEqual(client._token, "tok-1")
        finally:
            FakeTradingMaster.expire_after = None

    def test_start_filter_fallback_for_sqlite_backend(self):
        FakeTradingMaster.naive_store = True
        try:
            p = TradingMasterData(TradingMasterClient(self.base, "sm@example.com", "pw"), workers=2, now=lambda: NOW)
        finally:
            FakeTradingMaster.naive_store = False
        self.assertFalse(p._server_start_filter)
        self.assertEqual([b.close for b in p.daily_bars("RELIANCE")], [b.close for b in self.p.daily_bars("RELIANCE")])

    def test_credentials_required(self):
        with self.assertRaises(TradingMasterError):
            TradingMasterClient(self.base)
        with self.assertRaises(TradingMasterError):
            TradingMasterClient(self.base, "sm@example.com", "wrong").get("/options/underlyings")

    def test_platform_runs_on_tradingmaster_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = AppSettings()
            settings.STATE_DIR = Path(tmp)
            p = Platform(settings, provider=self.p, persist=False)
            meta = api.meta(p)
            self.assertFalse(meta["demo"])
            self.assertTrue(meta["source"].startswith("TradingMaster (127.0.0.1"))
            self.assertEqual(meta["universe_info"]["stocks"], 2)
            self.assertEqual(p.as_of, datetime(2026, 9, 25, 15, 30))
            self.assertEqual(api.scanner(p)["funnel"]["universe"], 3)
            health = json.dumps(api.health_payload(p))
            self.assertIn("3 F&O underlyings", health)


if __name__ == "__main__":
    unittest.main()
