"""Deterministic DEMO market data -- fictional, for demonstration only.

Everything produced here is synthetic and is labelled ``DEMO`` wherever it
surfaces in the platform.  The generator exists so the complete pipeline
(analysis -> scanner -> backtest -> UI) can run offline without any vendor
account.  It is not market data and must never be treated as such.

What is and is not simulated
* OHLCV       regime-switching random walk with a common market factor.
* Futures OI  simulated for F&O instruments (DEMO, used as a PROXY feed).
* Options     simulated chains for the three index products only.
* Positioning NOT simulated.  Commercial / institutional / retail engines
              report UNAVAILABLE, exactly as they would without a real feed.
* Intraday    5-minute paths are Brownian bridges pinned to each daily bar's
              open/high/low/close, so every timeframe is mutually consistent.
"""
from __future__ import annotations

import math
import random
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from ..schemas import Availability, Bar, FuturesOIRecord, Instrument, OptionChainSnapshot, OptionStrike
from .market_data import DataUnavailable, MarketDataProvider
from .resampler import TF_MINUTES, resample_intraday, session_close, session_open

# symbol, name, sector, base price, lot size, beta
_INDICES = [
    ("NIFTY", "NIFTY 50", "Index", 17400.0, 75, 1.0, 50.0),
    ("BANKNIFTY", "NIFTY BANK", "Index", 37000.0, 35, 1.15, 100.0),
    ("FINNIFTY", "NIFTY FIN SERVICE", "Index", 17600.0, 65, 1.1, 50.0),
]
_STOCKS = [
    ("RELIANCE", "Reliance Industries", "Energy", 2400.0, 1.0),
    ("HDFCBANK", "HDFC Bank", "Banking", 1500.0, 0.9),
    ("ICICIBANK", "ICICI Bank", "Banking", 760.0, 1.1),
    ("INFY", "Infosys", "IT", 1850.0, 0.8),
    ("TCS", "Tata Consultancy Services", "IT", 3800.0, 0.7),
    ("SBIN", "State Bank of India", "Banking", 480.0, 1.25),
    ("BHARTIARTL", "Bharti Airtel", "Telecom", 700.0, 0.8),
    ("ITC", "ITC", "FMCG", 225.0, 0.6),
    ("LT", "Larsen & Toubro", "Capital Goods", 1900.0, 1.1),
    ("KOTAKBANK", "Kotak Mahindra Bank", "Banking", 1900.0, 0.9),
    ("AXISBANK", "Axis Bank", "Banking", 720.0, 1.2),
    ("HINDUNILVR", "Hindustan Unilever", "FMCG", 2350.0, 0.55),
    ("BAJFINANCE", "Bajaj Finance", "Financials", 7200.0, 1.3),
    ("MARUTI", "Maruti Suzuki", "Auto", 7600.0, 0.9),
    ("TATAMOTORS", "Tata Motors", "Auto", 480.0, 1.3),
    ("SUNPHARMA", "Sun Pharmaceutical", "Pharma", 830.0, 0.6),
    ("TITAN", "Titan Company", "Consumer", 2500.0, 1.0),
    ("ASIANPAINT", "Asian Paints", "Consumer", 3300.0, 0.7),
    ("WIPRO", "Wipro", "IT", 700.0, 0.85),
    ("HCLTECH", "HCL Technologies", "IT", 1300.0, 0.8),
    ("ULTRACEMCO", "UltraTech Cement", "Cement", 7800.0, 0.95),
    ("NTPC", "NTPC", "Power", 130.0, 0.8),
    ("POWERGRID", "Power Grid Corporation", "Power", 200.0, 0.7),
    ("M&M", "Mahindra & Mahindra", "Auto", 850.0, 1.15),
    ("ADANIENT", "Adani Enterprises", "Metals & Mining", 1700.0, 1.4),
    ("ADANIPORTS", "Adani Ports & SEZ", "Infrastructure", 720.0, 1.2),
    ("APOLLOHOSP", "Apollo Hospitals", "Healthcare", 4800.0, 0.8),
    ("BAJAJ-AUTO", "Bajaj Auto", "Auto", 3500.0, 0.8),
    ("BAJAJFINSV", "Bajaj Finserv", "Financials", 1600.0, 1.2),
    ("BPCL", "Bharat Petroleum", "Energy", 380.0, 0.9),
    ("BRITANNIA", "Britannia Industries", "FMCG", 3500.0, 0.55),
    ("CIPLA", "Cipla", "Pharma", 900.0, 0.55),
    ("COALINDIA", "Coal India", "Energy", 160.0, 0.8),
    ("DIVISLAB", "Divi's Laboratories", "Pharma", 4500.0, 0.7),
    ("DRREDDY", "Dr. Reddy's Laboratories", "Pharma", 4400.0, 0.6),
    ("EICHERMOT", "Eicher Motors", "Auto", 2600.0, 1.0),
    ("GRASIM", "Grasim Industries", "Cement", 1600.0, 1.0),
    ("HDFCLIFE", "HDFC Life Insurance", "Insurance", 650.0, 0.8),
    ("HEROMOTOCO", "Hero MotoCorp", "Auto", 2400.0, 0.85),
    ("HINDALCO", "Hindalco Industries", "Metals & Mining", 450.0, 1.35),
    ("INDUSINDBK", "IndusInd Bank", "Banking", 900.0, 1.35),
    ("JSWSTEEL", "JSW Steel", "Metals & Mining", 650.0, 1.25),
    ("NESTLEIND", "Nestle India", "FMCG", 19000.0, 0.5),
    ("ONGC", "Oil & Natural Gas Corp", "Energy", 150.0, 0.9),
    ("SBILIFE", "SBI Life Insurance", "Insurance", 1150.0, 0.8),
    ("TATACONSUM", "Tata Consumer Products", "FMCG", 750.0, 0.7),
    ("TATASTEEL", "Tata Steel", "Metals & Mining", 110.0, 1.4),
    ("TECHM", "Tech Mahindra", "IT", 1500.0, 0.95),
]
_HOLIDAYS_MD = {(1, 26), (5, 1), (8, 15), (10, 2), (12, 25)}  # demo calendar approximation
OI_PUBLICATION_TIME = (18, 30)


def trading_days(start: date, end: date) -> List[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5 and (d.month, d.day) not in _HOLIDAYS_MD:
            out.append(d)
        d += timedelta(days=1)
    return out


def _tick(x: float) -> float:
    return round(round(x / 0.05) * 0.05, 2)


def _regimes(rng: random.Random, n: int, drifts: Tuple[float, ...], dur: Tuple[int, int],
             vols: Tuple[float, float]) -> List[Tuple[float, float]]:
    out: List[Tuple[float, float]] = []
    while len(out) < n:
        d = rng.choice(drifts)
        v = rng.uniform(*vols)
        out.extend([(d, v)] * rng.randint(*dur))
    return out[:n]


class DemoMarketData(MarketDataProvider):
    source_label = "DEMO (synthetic, fictional)"
    is_demo = True

    def __init__(self, seed: int = 123, start: str = "2022-01-03", end: str = "2026-09-25"):
        self.seed = seed
        self.days = trading_days(date.fromisoformat(start), date.fromisoformat(end))
        self._universe = [
            Instrument(s, n, sec, "INDEX", lot, True, True, True, step) for s, n, sec, _, lot, _, step in _INDICES
        ] + [Instrument(s, n, sec, "EQ", 1, False, True, False, 0.0) for s, n, sec, _, _ in _STOCKS]
        self._bars: Dict[str, List[Bar]] = {}
        self._oi: Dict[str, List[FuturesOIRecord]] = {}
        self._vix: List[Bar] = []
        self._generate()

    # ------------------------------------------------------------------ #
    def universe(self) -> List[Instrument]:
        return list(self._universe)

    def daily_bars(self, symbol: str) -> List[Bar]:
        if symbol not in self._bars:
            raise KeyError(symbol)
        return self._bars[symbol]

    def futures_oi(self, symbol: str) -> List[FuturesOIRecord]:
        return self._oi.get(symbol, [])

    def volatility_index(self) -> List[Bar]:
        return self._vix

    def positioning(self):
        return []  # never simulated -- engines report UNAVAILABLE

    def as_of(self) -> datetime:
        return session_close(self.days[-1])

    # ------------------------------------------------------------------ #
    def _generate(self) -> None:
        n = len(self.days)
        rng = random.Random(f"market-{self.seed}")
        regimes = _regimes(rng, n, (0.0008, 0.0005, -0.0008, 0.0001), (25, 80), (0.0075, 0.0125))
        market = []
        for d, v in regimes:
            shock = rng.gauss(0, 1)
            if rng.random() < 0.02:
                shock *= 2.5  # occasional event day
            market.append((d + v * shock, v))

        for sym, _name, _sec, base, _lot, beta, _step in _INDICES:
            r2 = random.Random(f"{sym}-{self.seed}")
            rets = []
            for r_m, v in market:
                rets.append((beta * r_m + r2.gauss(0, 0.25 * v) if sym != "NIFTY" else r_m, v * max(beta, 1.0)))
            self._bars[sym] = self._ohlcv(sym, base, rets, 2.5e8 if sym == "NIFTY" else 1.5e8)

        for sym, _name, _sec, base, beta in _STOCKS:
            r2 = random.Random(f"{sym}-{self.seed}")
            idio = _regimes(r2, n, (0.0009, -0.0009, 0.0, 0.0002), (20, 70), (0.009, 0.0145))
            rets = []
            for (r_m, v_m), (d_i, v_i) in zip(market, idio):
                rets.append((beta * r_m + d_i + v_i * r2.gauss(0, 1), math.hypot(beta * v_m, v_i)))
            self._bars[sym] = self._ohlcv(sym, base, rets, r2.uniform(3e6, 1.2e7))

        for inst in self._universe:
            if inst.has_futures:
                self._oi[inst.symbol] = self._make_oi(inst.symbol)
        self._vix = self._make_vix(market)

    def _ohlcv(self, sym: str, base: float, rets, base_vol: float) -> List[Bar]:
        rng = random.Random(f"ohlc-{sym}-{self.seed}")
        bars: List[Bar] = []
        prev = base
        for d, (r, sigma) in zip(self.days, rets):
            o = prev * math.exp(rng.gauss(0, 0.28 * sigma))
            c = prev * math.exp(r)
            hi = max(o, c) * math.exp(abs(rng.gauss(0, 0.5 * sigma)))
            lo = min(o, c) * math.exp(-abs(rng.gauss(0, 0.5 * sigma)))
            vol = base_vol * math.exp(rng.gauss(0, 0.25)) * (1.0 + 1.4 * abs(r) / max(sigma, 1e-6))
            o, hi, lo, c = _tick(o), _tick(hi), _tick(lo), _tick(c)
            hi, lo = max(hi, o, c), min(lo, o, c)
            bars.append(Bar(session_open(d), session_close(d), o, hi, lo, c, round(vol)))
            prev = c
        return bars

    def _make_oi(self, sym: str) -> List[FuturesOIRecord]:
        rng = random.Random(f"oi-{sym}-{self.seed}")
        bars = self._bars[sym]
        oi = rng.uniform(4e6, 1.5e7) if not sym.endswith("NIFTY") and sym != "NIFTY" else rng.uniform(1.0e7, 1.6e7)
        sign = 1.0
        out: List[FuturesOIRecord] = []
        prev_close = bars[0].close
        for b in bars:
            if rng.random() < 0.06:
                sign = -sign
            r = b.close / prev_close - 1.0
            chg = 0.9 * sign * abs(r) + 0.35 * r + rng.gauss(0, 0.012)
            new_oi = max(1e5, oi * (1.0 + chg))
            d = b.timestamp.date()
            out.append(FuturesOIRecord(d, b.close, round(new_oi), round(new_oi - oi),
                                       datetime(d.year, d.month, d.day, *OI_PUBLICATION_TIME), Availability.PROXY))
            oi, prev_close = new_oi, b.close
        return out

    def _make_vix(self, market) -> List[Bar]:
        rng = random.Random(f"vix-{self.seed}")
        v = 16.0
        out = []
        for d, (r_m, _) in zip(self.days, market):
            o = v
            v = min(38.0, max(9.0, v + 0.07 * (14.0 - v) - 220.0 * r_m * v / 14.0 + rng.gauss(0, 0.35)))
            hi = max(o, v) + abs(rng.gauss(0, 0.3))
            lo = min(o, v) - abs(rng.gauss(0, 0.3))
            out.append(Bar(session_open(d), session_close(d), round(o, 2), round(hi, 2), round(lo, 2), round(v, 2), 0))
        return out

    # ------------------------------------------------------------------ #
    # intraday -- Brownian bridge pinned to the daily OHLC
    # ------------------------------------------------------------------ #
    @lru_cache(maxsize=4096)
    def _five_minute_day(self, symbol: str, k: int) -> Tuple[Bar, ...]:
        day_bar = self._bars[symbol][k]
        d = day_bar.timestamp.date()
        rng = random.Random(f"5m-{symbol}-{d.isoformat()}-{self.seed}")
        n = 75
        o, h, l, c = day_bar.open, day_bar.high, day_bar.low, day_bar.close
        a_h, a_l = rng.sample(range(1, n), 2)
        anchors = sorted([(0, o), (a_h, h), (a_l, l), (n, c)])
        pts = [0.0] * (n + 1)
        noise = (h - l) * 0.06
        for (t0, p0), (t1, p1) in zip(anchors, anchors[1:]):
            walk, acc = [0.0], 0.0
            for _ in range(t1 - t0):
                acc += rng.gauss(0, noise)
                walk.append(acc)
            span = t1 - t0
            for j in range(span + 1):
                bridge = walk[j] - (j / span) * walk[-1] if span else 0.0
                pts[t0 + j] = p0 + (p1 - p0) * (j / span if span else 0) + bridge
        pts = [min(h, max(l, p)) for p in pts]
        pts[a_h], pts[a_l], pts[0], pts[n] = h, l, o, c
        weights = [(1 + 1.3 * ((j - n / 2) / (n / 2)) ** 2) * math.exp(rng.gauss(0, 0.3)) for j in range(n)]
        wsum = sum(weights)
        start = session_open(d)
        bars = []
        for j in range(n):
            p0, p1 = pts[j], pts[j + 1]
            wick = abs(rng.gauss(0, noise * 0.4))
            bh = min(h, max(p0, p1) + wick)
            bl = max(l, min(p0, p1) - wick)
            ts = start + timedelta(minutes=5 * j)
            bars.append(Bar(ts, min(ts + timedelta(minutes=5), session_close(d)), _tick(p0), _tick(bh), _tick(bl),
                            _tick(p1), round(day_bar.volume * weights[j] / wsum)))
        return tuple(bars)

    def intraday_bars(self, symbol: str, timeframe: str, sessions: int) -> List[Bar]:
        if timeframe not in TF_MINUTES:
            raise DataUnavailable(timeframe)
        daily = self._bars[symbol]
        five: List[Bar] = []
        for k in range(max(0, len(daily) - sessions), len(daily)):
            five.extend(self._five_minute_day(symbol, k))
        return five if timeframe == "5m" else resample_intraday(five, timeframe)

    # ------------------------------------------------------------------ #
    # options -- index chains only
    # ------------------------------------------------------------------ #
    @staticmethod
    def _expiry_for(d: date) -> date:
        # demo convention: weekly expiry on Thursday
        return d + timedelta(days=(3 - d.weekday()) % 7)

    @lru_cache(maxsize=8192)
    def _raw_chain(self, symbol: str, k: int) -> Tuple[date, float, Dict[float, Tuple[float, float]]]:
        inst = self.instrument(symbol)
        bars = self._bars[symbol]
        b = bars[k]
        d = b.timestamp.date()
        rng = random.Random(f"chain-{inst.symbol}-{d.isoformat()}-{self.seed}")
        spot = b.close
        ret10 = spot / bars[max(0, k - 10)].close - 1.0
        pcr_target = min(1.8, max(0.5, 1.0 + 4.0 * ret10 + rng.gauss(0, 0.08)))
        step = inst.strike_step
        atm = round(spot / step) * step
        width = step * 6
        calls, puts = {}, {}
        for j in range(-18, 19):
            s = atm + j * step
            round_bonus = 1.6 if (s % (step * 10)) == 0 else (1.2 if (s % (step * 2)) == 0 else 1.0)
            calls[s] = 2e5 * round_bonus * math.exp(-((s - (spot + 2 * step)) / width) ** 2) * math.exp(rng.gauss(0, 0.2))
            puts[s] = 2e5 * round_bonus * math.exp(-((s - (spot - 2 * step)) / width) ** 2) * math.exp(rng.gauss(0, 0.2))
        scale = pcr_target * sum(calls.values()) / sum(puts.values())
        chain = {s: (round(calls[s]), round(puts[s] * scale)) for s in calls}
        return self._expiry_for(d), spot, chain

    @lru_cache(maxsize=64)
    def _date_index(self, symbol: str) -> Dict[date, int]:
        return {b.timestamp.date(): i for i, b in enumerate(self._bars[symbol])}

    def option_chain(self, symbol: str, trade_date: date) -> Optional[OptionChainSnapshot]:
        inst = self.instrument(symbol)
        if not inst.has_options:
            return None
        k = self._date_index(symbol).get(trade_date)
        if k is None:
            return None
        expiry, spot, chain = self._raw_chain(symbol, k)
        rollover = True
        prev_chain: Dict[float, Tuple[float, float]] = {}
        if k > 0:
            p_exp, _, prev_chain = self._raw_chain(symbol, k - 1)
            rollover = p_exp != expiry
        strikes = []
        for s, (c_oi, p_oi) in sorted(chain.items()):
            pc, pp = prev_chain.get(s, (0.0, 0.0)) if not rollover else (0.0, 0.0)
            strikes.append(OptionStrike(s, c_oi, p_oi, c_oi - pc, p_oi - pp))
        d = trade_date
        return OptionChainSnapshot(symbol, d, expiry, spot, strikes,
                                   datetime(d.year, d.month, d.day, *OI_PUBLICATION_TIME), rollover, Availability.PROXY)

    # ------------------------------------------------------------------ #
    def health(self) -> Dict[str, Dict]:
        last = self.days[-1]
        return {
            "market_feed": {"status": "DEMO", "detail": "Synthetic daily OHLCV (fictional)"},
            "websocket": {"status": "NOT CONFIGURED", "detail": "Live tick feed requires a broker/vendor connection"},
            "historical_sync": {"status": "DEMO", "detail": f"{len(self.days)} sessions to {last.isoformat()}"},
            "futures_oi": {"status": "DEMO", "detail": "Simulated EOD OI for F&O instruments (PROXY feed)"},
            "options_feed": {"status": "DEMO", "detail": "Simulated index option chains (NIFTY, BANKNIFTY, FINNIFTY)"},
            "positioning_feed": {"status": "UNAVAILABLE", "detail": "No participant-wise OI loaded; never simulated"},
            "last_candle": {"status": "OK", "detail": session_close(last).isoformat()},
            "latency": {"status": "N/A", "detail": "Offline demo data"},
            "data_gaps": {"status": "OK", "detail": "Demo calendar has no gaps"},
        }
