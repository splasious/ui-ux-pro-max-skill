"""Real NSE data from a TradingMaster backend (``SM_DATA_SOURCE=TRADINGMASTER``).

TradingMaster (github.com/splasious/TradingMaster, served from
api.tradingmaster.online) backfills NSE cash and NFO contracts from Zerodha
Kite into its own database.  This provider reads that store through
TradingMaster's REST API.  It only logs in and issues GET requests; it never
writes to TradingMaster:

  POST /auth/login                        bearer token (credentials from env vars)
  GET  /options/underlyings               every underlying with backfilled NFO contracts
  GET  /instruments?exchange=NSE          names and types of those underlyings, INDIA VIX
  GET  /instruments?exchange=NFO&q=FUT    futures contracts: expiry, lot size, underlying
  GET  /market-data/candles               OHLCV (+ open interest on futures), any timeframe
  GET  /options/{id}/expiries, /chain     the current option-chain snapshot

The universe is therefore F&O by construction: only symbols TradingMaster
holds NFO contracts for are returned.

* TradingMaster stores UTC; everything here is converted to naive IST.
  Daily bars are keyed by their IST date.
* Only completed bars are used: today's daily bar before 15:30 IST and an
  intraday bar whose period has not ended are dropped.
* Rows with inconsistent OHLC are dropped and counted in Data Health, never
  repaired.
* Futures OI is the nearest unexpired contract on each date; ΔOI compares
  the same contract day over day.
* TradingMaster keeps the current option-chain snapshot only, so a chain
  exists for the latest session.  Its per-strike "change" is measured from
  the day's open, not the previous session, so ΔOI PCR reports itself
  unavailable rather than mixing the two definitions.
"""
from __future__ import annotations

import csv
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from ..logging_utils import log
from ..schemas import (UNCLASSIFIED_SECTOR, Availability, Bar, FuturesOIRecord, Instrument, OptionChainSnapshot,
                       OptionStrike)
from .demo import _STOCKS as _KNOWN_STOCKS
from .market_data import DataUnavailable, MarketDataProvider
from .resampler import TF_MINUTES, resample_intraday, session_close, session_open

IST = timezone(timedelta(hours=5, minutes=30))
DEFAULT_API_URL = "https://api.tradingmaster.online/api/v1"

# TradingMaster's index rows carry NSE's index names; Swing Master uses the NFO underlying names.
INDEX_ALIASES = {"NIFTY 50": "NIFTY", "NIFTY BANK": "BANKNIFTY", "NIFTY FIN SERVICE": "FINNIFTY",
                 "NIFTY MID SELECT": "MIDCPNIFTY", "NIFTY NEXT 50": "NIFTYNXT50"}
VIX_SYMBOL = "INDIA VIX"
# Stored timeframes to try, finest last, for each Swing Master intraday timeframe.
INTRADAY_SOURCES = {"5m": ("5m",), "15m": ("15m", "5m"), "1H": ("60m", "15m", "5m"), "4H": ("60m", "15m", "5m")}
MIN_DAILY_BARS = 120
OI_AVAILABLE_AT = (18, 30)
KNOWN_SECTORS = {sym: sector for sym, _name, sector, *_ in _KNOWN_STOCKS}


class TradingMasterError(RuntimeError):
    pass


class TradingMasterClient:
    """Minimal JSON client: bearer auth, one re-login on 401, retries with backoff on 429/5xx/network errors."""

    def __init__(self, base_url: str, email: str = "", password: str = "", token: str = "",
                 timeout: float = 60.0, retries: int = 3):
        self.base_url = base_url.rstrip("/")
        self.email, self.password = email, password
        self.timeout, self.retries = timeout, retries
        self._token = token
        self._lock = threading.Lock()
        self.requests = 0
        if not token and not (email and password):
            raise TradingMasterError("TradingMaster credentials missing: set SM_TM_EMAIL and SM_TM_PASSWORD "
                                     "(or SM_TM_TOKEN) in the environment")

    def _login(self) -> None:
        if not (self.email and self.password):
            raise TradingMasterError("TradingMaster rejected the token and no email/password is configured")
        body = json.dumps({"email": self.email, "password": self.password}).encode()
        data = self._send("POST", "/auth/login", body=body, auth=False)
        self._token = data["access_token"]

    def _send(self, method: str, path: str, params: Optional[Dict] = None, body: Optional[bytes] = None,
              auth: bool = True):
        url = self.base_url + path + ("?" + urllib.parse.urlencode(params) if params else "")
        headers = {"Accept": "application/json", "User-Agent": "SwingMaster/1.0"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if auth:
            headers["Authorization"] = f"Bearer {self._token}"
        delay = 1.0
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(url, data=body, method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    self.requests += 1
                    return json.loads(resp.read() or b"null")
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 502, 503, 504) and attempt < self.retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                detail = exc.read()[:300].decode("utf-8", "replace")
                raise TradingMasterError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt < self.retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise TradingMasterError(f"{method} {path} -> {exc}") from exc
        raise TradingMasterError(f"{method} {path} failed")  # pragma: no cover

    def get(self, path: str, params: Optional[Dict] = None):
        with self._lock:
            if not self._token:
                self._login()
            token = self._token
        try:
            return self._send("GET", path, params)
        except TradingMasterError as exc:
            if "HTTP 401" not in str(exc):
                raise
            with self._lock:
                if self._token == token:  # nobody refreshed it meanwhile
                    self._login()
            return self._send("GET", path, params)


def parse_ts(value: str) -> datetime:
    """TradingMaster timestamp (ISO, UTC or offset-aware) -> naive IST."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).replace(tzinfo=None)


def load_sector_map(path: str) -> Dict[str, str]:
    out = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            if row.get("symbol") and row.get("sector"):
                out[row["symbol"].upper()] = row["sector"]
    return out


def _valid(o: float, h: float, lo: float, c: float) -> bool:
    return lo <= min(o, c) and h >= max(o, c) and lo > 0


class TradingMasterData(MarketDataProvider):
    is_demo = False

    def __init__(self, client: TradingMasterClient, history_days: int = 1825, workers: int = 6,
                 sector_map: Optional[Dict[str, str]] = None, now: Optional[Callable[[], datetime]] = None):
        self.client = client
        self.history_days = history_days
        self.workers = max(1, workers)
        self.sectors = {**KNOWN_SECTORS, **(sector_map or {})}
        self._now = now or (lambda: datetime.now(IST).replace(tzinfo=None))
        host = urllib.parse.urlparse(client.base_url).netloc
        self.source_label = f"TradingMaster ({host})"
        self._universe: List[Instrument] = []
        self._ids: Dict[str, str] = {}
        self._bars: Dict[str, List[Bar]] = {}
        self._oi: Dict[str, List[FuturesOIRecord]] = {}
        self._chains: Dict[str, OptionChainSnapshot] = {}
        self._intraday: Dict[Tuple[str, str], List[Bar]] = {}
        self._vix: List[Bar] = []
        self.dropped: Dict[str, int] = defaultdict(int)
        self.errors: List[str] = []
        self.skipped: Dict[str, str] = {}
        self.loaded_at: Optional[datetime] = None
        self._server_start_filter = True
        self._load()

    # ------------------------------------------------------------------ #
    # bulk load
    # ------------------------------------------------------------------ #
    def _load(self) -> None:
        t0 = time.time()
        underlyings = self.client.get("/options/underlyings")
        if not underlyings:
            raise TradingMasterError("TradingMaster returned no F&O underlyings: backfill NFO contracts first")
        nse = {r["id"]: r for r in self.client.get("/instruments", {"exchange": "NSE", "limit": 5000})}
        futures: Dict[str, List[Dict]] = defaultdict(list)
        for r in self.client.get("/instruments", {"exchange": "NFO", "q": "FUT", "limit": 5000}):
            if r.get("instrument_type") == "future" and r.get("underlying_instrument_id") and r.get("expiry"):
                futures[r["underlying_instrument_id"]].append(r)
        start = (self._now() - timedelta(days=self.history_days)).date().isoformat()

        def fetch(u: Dict) -> Tuple[Dict, Optional[Dict]]:
            uid, tm_sym = u["instrument_id"], u["symbol"]
            try:
                bars = self._daily(uid, tm_sym, start)
                contracts = sorted(futures.get(uid, []), key=lambda r: r["expiry"])
                oi = self._futures_oi(contracts, start, tm_sym)
                expiries = self.client.get(f"/options/{uid}/expiries")
                chain_expiry = next((date.fromisoformat(e["expiry"]) for e in expiries
                                     if e.get("option_count") and date.fromisoformat(e["expiry"]) >= self._now().date()),
                                    None)
                chain = self.client.get(f"/options/{uid}/chain", {"expiry": chain_expiry.isoformat()}) \
                    if chain_expiry else []
                return u, {"bars": bars, "oi": oi, "contracts": contracts, "chain": chain,
                           "chain_expiry": chain_expiry, "has_options": any(e.get("option_count") for e in expiries)}
            except TradingMasterError as exc:
                self.errors.append(f"{tm_sym}: {exc}")
                return u, None

        with ThreadPoolExecutor(self.workers) as pool:
            results = list(pool.map(fetch, underlyings))

        for u, res in results:
            tm_sym = u["symbol"]
            sym = INDEX_ALIASES.get(tm_sym, tm_sym)
            if res is None:
                self.skipped[sym] = "download failed"
                continue
            if len(res["bars"]) < MIN_DAILY_BARS:
                self.skipped[sym] = f"only {len(res['bars'])} daily bars (needs {MIN_DAILY_BARS})"
                continue
            row = nse.get(u["instrument_id"], {})
            is_index = tm_sym in INDEX_ALIASES or row.get("instrument_type") == "index"
            lots = [c["lot_size"] for c in res["contracts"] if c.get("lot_size")]
            chain = self._chain(sym, res["chain"], res["chain_expiry"], res["bars"])
            if chain:
                self._chains[sym] = chain
            step = _strike_step([s.strike for s in chain.strikes]) if chain else 0.0
            self._universe.append(Instrument(
                symbol=sym, name=row.get("name") or tm_sym,
                sector="Index" if is_index else self.sectors.get(sym, UNCLASSIFIED_SECTOR),
                segment="INDEX" if is_index else "EQ", lot_size=lots[0] if lots else 1, is_index=is_index,
                has_futures=True, has_options=res["has_options"], strike_step=step))  # an NFO underlying by definition
            self._ids[sym] = u["instrument_id"]
            self._bars[sym] = res["bars"]
            self._oi[sym] = res["oi"]
        if not self._universe:
            raise TradingMasterError("No TradingMaster underlying has enough daily history: " +
                                     "; ".join(f"{k}: {v}" for k, v in list(self.skipped.items())[:5]))
        self._universe.sort(key=lambda i: (not i.is_index, i.symbol != "NIFTY", i.symbol))

        vix = next((r for r in nse.values() if r.get("symbol") == VIX_SYMBOL), None)
        if vix:
            try:
                self._vix = self._daily(vix["id"], VIX_SYMBOL, start, volume=False)
            except TradingMasterError as exc:
                self.errors.append(f"{VIX_SYMBOL}: {exc}")
        self.loaded_at = self._now()
        log("market_data", f"TradingMaster: {len(self._universe)} F&O underlyings loaded",
            seconds=round(time.time() - t0, 1), requests=self.client.requests, skipped=len(self.skipped),
            errors=len(self.errors), dropped_rows=sum(self.dropped.values()))

    def _candles(self, instrument_id: str, timeframe: str, start: str) -> List[Dict]:
        # TradingMaster compares `start` with stored timestamps in Python: Postgres returns them tz-aware (so an
        # aware start works), SQLite returns them naive (so it fails with a 500).  Fall back to filtering here.
        params = {"instrument_id": instrument_id, "timeframe": timeframe}
        if self._server_start_filter:
            try:
                return self.client.get("/market-data/candles", {**params, "start": f"{start}T00:00:00+00:00"}) or []
            except TradingMasterError as exc:
                if "HTTP 500" not in str(exc):
                    raise
                self._server_start_filter = False
        first = datetime.fromisoformat(start)
        return [c for c in self.client.get("/market-data/candles", params) or [] if parse_ts(c["ts"]) >= first]

    def _daily(self, instrument_id: str, label: str, start: str, volume: bool = True) -> List[Bar]:
        now = self._now()
        by_day: Dict[date, Bar] = {}
        for c in self._candles(instrument_id, "1d", start):
            d = parse_ts(c["ts"]).date()
            if session_close(d) > now:
                continue  # today's bar is still forming
            o, h, lo, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
            if not _valid(o, h, lo, cl):
                self.dropped[label] += 1
                continue
            by_day[d] = Bar(session_open(d), session_close(d), o, h, lo, cl, float(c.get("volume") or 0) if volume else 0)
        return [by_day[d] for d in sorted(by_day)]

    def _futures_oi(self, contracts: List[Dict], start: str, label: str) -> List[FuturesOIRecord]:
        best: Dict[date, Tuple[date, float, float, float]] = {}
        now = self._now()
        for c in contracts:
            expiry = date.fromisoformat(c["expiry"])
            prev = None
            for row in self._candles(c["id"], "1d", start):
                d = parse_ts(row["ts"]).date()
                oi = row.get("open_interest")
                if oi is None or session_close(d) > now:
                    prev = None
                    continue
                change = float(oi) - prev if prev is not None else 0.0
                prev = float(oi)
                if d <= expiry and (d not in best or expiry < best[d][0]):
                    best[d] = (expiry, float(row["close"]), float(oi), change)
        return [FuturesOIRecord(d, close, oi, chg, datetime(d.year, d.month, d.day, *OI_AVAILABLE_AT), Availability.DIRECT)
                for d, (_e, close, oi, chg) in sorted(best.items())]

    def _chain(self, sym: str, rows: List[Dict], expiry: Optional[date], bars: List[Bar]) -> Optional[OptionChainSnapshot]:
        if not rows or expiry is None or not bars:
            return None
        strikes, stamps = [], []
        for r in rows:
            call, put = r.get("call") or {}, r.get("put") or {}
            stamps += [parse_ts(leg["as_of"]) for leg in (call, put) if leg.get("as_of")]
            strikes.append(OptionStrike(float(r["strike"]), float(call.get("open_interest") or 0),
                                        float(put.get("open_interest") or 0), 0.0, 0.0))
        if not stamps:
            return None
        as_of = max(stamps)
        trade_date = min(as_of.date(), bars[-1].timestamp.date())
        return OptionChainSnapshot(sym, trade_date, expiry, bars[-1].close, sorted(strikes, key=lambda s: s.strike),
                                   max(as_of, session_close(trade_date)), False, Availability.DIRECT,
                                   change_oi_available=False)

    # ------------------------------------------------------------------ #
    # provider interface
    # ------------------------------------------------------------------ #
    def universe(self) -> List[Instrument]:
        return list(self._universe)

    def daily_bars(self, symbol: str) -> List[Bar]:
        if symbol not in self._bars:
            raise DataUnavailable(f"{symbol} is not in the TradingMaster F&O universe")
        return self._bars[symbol]

    def intraday_bars(self, symbol: str, timeframe: str, sessions: int) -> List[Bar]:
        if timeframe not in INTRADAY_SOURCES or symbol not in self._ids:
            raise DataUnavailable(f"No {timeframe} data for {symbol}")
        key = (symbol, timeframe)
        if key not in self._intraday:
            self._intraday[key] = self._load_intraday(symbol, timeframe)
        bars = self._intraday[key]
        keep = set(sorted({b.timestamp.date() for b in bars})[-sessions:])
        return [b for b in bars if b.timestamp.date() in keep]

    def _load_intraday(self, symbol: str, timeframe: str) -> List[Bar]:
        now = self._now()
        start = (now - timedelta(days=max(30, self.history_days // 5))).date().isoformat()
        for stored in INTRADAY_SOURCES[timeframe]:
            minutes = int(stored[:-1])
            raw = self._candles(self._ids[symbol], stored, start)
            bars = []
            for c in raw:
                ts = parse_ts(c["ts"])
                close_time = min(ts + timedelta(minutes=minutes), session_close(ts.date()))
                o, h, lo, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
                if close_time > now or ts < session_open(ts.date()) or not _valid(o, h, lo, cl):
                    continue
                bars.append(Bar(ts, close_time, o, h, lo, cl, float(c.get("volume") or 0)))
            if bars:
                bars.sort(key=lambda b: b.timestamp)
                if minutes == TF_MINUTES.get(timeframe):
                    return bars
                return resample_intraday(bars, timeframe)
        raise DataUnavailable(f"TradingMaster has no intraday candles stored for {symbol}")

    def futures_oi(self, symbol: str) -> List[FuturesOIRecord]:
        return self._oi.get(symbol, [])

    def option_chain(self, symbol: str, trade_date: date) -> Optional[OptionChainSnapshot]:
        chain = self._chains.get(symbol)
        return chain if chain is not None and chain.trade_date == trade_date else None

    def volatility_index(self) -> List[Bar]:
        return self._vix

    def health(self) -> Dict[str, Dict]:
        last = max((b[-1].close_time for b in self._bars.values() if b), default=None)
        n = len(self._universe)
        with_oi = sum(1 for v in self._oi.values() if v)
        dropped = sum(self.dropped.values())
        return {
            "market_feed": {"status": "OK" if not self.errors else "WARN",
                            "detail": f"{self.source_label}: {n} F&O underlyings, {self.client.requests} requests"
                                      + (f", {len(self.errors)} failed" if self.errors else "")},
            "websocket": {"status": "NOT CONFIGURED", "detail": "Daily and intraday candles are read from TradingMaster's store"},
            "historical_sync": {"status": "OK", "detail": f"Loaded {self.loaded_at:%Y-%m-%d %H:%M} IST"
                                + (f"; skipped {len(self.skipped)} ({', '.join(list(self.skipped)[:4])})" if self.skipped else "")},
            "futures_oi": {"status": "OK" if with_oi else "UNAVAILABLE",
                           "detail": f"{with_oi}/{n} underlyings have futures OI (nearest unexpired contract)"},
            "options_feed": {"status": "OK" if self._chains else "UNAVAILABLE",
                             "detail": f"{len(self._chains)} current chain snapshots; history not stored by the source"},
            "positioning_feed": {"status": "UNAVAILABLE", "detail": "Load NSE participant-wise OI via SM_POSITIONING_CSV"},
            "last_candle": {"status": "OK" if last else "UNAVAILABLE", "detail": last.isoformat() if last else "none"},
            "latency": {"status": "N/A", "detail": "Snapshot at load time"},
            "data_gaps": {"status": "WARN" if dropped else "OK", "detail": f"{dropped} invalid rows dropped"},
        }


def _strike_step(strikes: List[float]) -> float:
    diffs = sorted(round(b - a, 4) for a, b in zip(sorted(set(strikes)), sorted(set(strikes))[1:]) if b > a)
    if not diffs:
        return 0.0
    counts: Dict[float, int] = defaultdict(int)
    for d in diffs:
        counts[d] += 1
    return max(counts, key=lambda d: (counts[d], -d))


def from_settings(settings) -> TradingMasterData:
    import os
    client = TradingMasterClient(settings.TM_API_URL, os.environ.get(settings.TM_EMAIL_ENV, ""),
                                 os.environ.get(settings.TM_PASSWORD_ENV, ""), os.environ.get(settings.TM_TOKEN_ENV, ""))
    sector_map = load_sector_map(settings.SECTOR_MAP) if settings.SECTOR_MAP and Path(settings.SECTOR_MAP).exists() else None
    return TradingMasterData(client, settings.TM_HISTORY_DAYS, settings.TM_WORKERS, sector_map)
