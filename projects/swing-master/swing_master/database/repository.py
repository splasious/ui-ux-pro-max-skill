"""Persistence repository (sqlite3, standard library only)."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List

from ..schemas import to_jsonable
from .models import ANALYTICS_SCHEMA, RAW_SCHEMA


class Repository:
    def __init__(self, raw_path: Path, analytics_path: Path):
        Path(raw_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.raw = sqlite3.connect(str(raw_path), check_same_thread=False)
        self.analytics = sqlite3.connect(str(analytics_path), check_same_thread=False)
        self.raw.executescript(RAW_SCHEMA)
        self.analytics.executescript(ANALYTICS_SCHEMA)

    @classmethod
    def in_memory(cls) -> "Repository":
        return cls(Path(":memory:"), Path(":memory:"))

    def close(self):
        self.raw.close()
        self.analytics.close()

    # ---- raw ---------------------------------------------------------------
    def save_bars(self, symbol: str, timeframe: str, bars: Iterable, source: str) -> int:
        rows = [(symbol, timeframe, b.timestamp.isoformat(), b.close_time.isoformat(), b.open, b.high, b.low, b.close,
                 b.volume, source) for b in bars]
        with self._lock, self.raw:
            self.raw.executemany("INSERT OR REPLACE INTO ohlcv VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        return len(rows)

    def save_futures_oi(self, symbol: str, records: Iterable) -> None:
        rows = [(symbol, r.trade_date.isoformat(), r.close, r.open_interest, r.change_in_oi, r.available_at.isoformat(),
                 r.source_type) for r in records]
        with self._lock, self.raw:
            self.raw.executemany("INSERT OR REPLACE INTO futures_oi VALUES (?,?,?,?,?,?,?)", rows)

    # ---- analytics ---------------------------------------------------------
    def save_analysis(self, dataset) -> None:
        an = dataset.analyzer
        sym, tf = dataset.symbol, dataset.timeframe
        with self._lock, self.analytics:
            self.analytics.executemany(
                "INSERT OR REPLACE INTO pivots VALUES (?,?,?,?,?,?,?,?,?)",
                [(sym, tf, p.seq, p.pivot_type, p.pivot_price, p.pivot_timestamp.isoformat(),
                  p.confirmation_timestamp.isoformat(), p.label, p.reversal_atr) for p in an.pivots.pivots])
            self.analytics.execute("DELETE FROM structure_events WHERE symbol=? AND timeframe=?", (sym, tf))
            self.analytics.executemany(
                "INSERT INTO structure_events VALUES (?,?,?,?,?,?,?,?)",
                [(sym, tf, e.event_timestamp.isoformat(), e.event_type, e.direction, e.level, e.previous_structure,
                  e.current_structure) for e in an.events.events])
            self.analytics.executemany(
                "INSERT OR REPLACE INTO zones VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(z.zone_id, sym, tf, z.zone_type, z.pattern, z.proximal, z.distal, z.creation_timestamp.isoformat(),
                  z.status_as_of(an.i), json.dumps(to_jsonable(z.to_dict(an.i)))) for z in an.zones.zones])

    def save_run(self, run_id: str, result, metrics: Dict) -> None:
        with self._lock, self.analytics:
            self.analytics.execute("INSERT OR REPLACE INTO performance VALUES (?,?,?,?,?)",
                                   (run_id, result.label, datetime.now().isoformat(),
                                    json.dumps(to_jsonable(result.config)), json.dumps(to_jsonable(metrics))))
            self.analytics.execute("DELETE FROM trades WHERE run_id=?", (run_id,))
            self.analytics.executemany(
                "INSERT OR REPLACE INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(t.trade_id, run_id, t.symbol, t.direction, t.entry_time.isoformat(),
                  t.exit_time.isoformat() if t.exit_time else None, t.entry, t.exit_price, t.quantity, t.net_pnl,
                  t.r_multiple(), t.exit_reason, json.dumps(to_jsonable(t.to_dict())))
                 for t in list(result.trades) + list(result.open_trades)])
            self.analytics.execute("DELETE FROM signals WHERE run_id=?", (run_id,))
            self.analytics.executemany("INSERT INTO signals VALUES (?,?,?,?,?,?,?,?)",
                                       [(s["eval_id"], run_id, s["time"], s["symbol"], s["direction"], s["status"],
                                         s["score"], json.dumps(s)) for s in result.signals])
            self.analytics.execute("DELETE FROM rejected_signals WHERE run_id=?", (run_id,))
            self.analytics.executemany("INSERT INTO rejected_signals VALUES (?,?,?,?,?,?,?,?,?)",
                                       [(r["eval_id"], run_id, r["time"], r["symbol"], r["direction"], r["reason"],
                                         r["score"], r["min_score"], json.dumps(to_jsonable(r))) for r in result.rejected])
            self.analytics.execute("DELETE FROM risk_states WHERE run_id=?", (run_id,))
            self.analytics.executemany("INSERT INTO risk_states VALUES (?,?,?,?,?)",
                                       [(run_id, p["time"], p["equity"], p["open_risk"], p["positions"])
                                        for p in result.equity_curve])

    def save_orders(self, run_id: str, orders: Iterable) -> None:
        with self._lock, self.analytics:
            self.analytics.executemany("INSERT OR REPLACE INTO orders VALUES (?,?,?,?,?,?,?)",
                                       [(o.order_id, run_id, o.request.symbol, o.request.side, o.request.quantity,
                                         o.status, json.dumps(to_jsonable(o.to_dict()))) for o in orders])

    def save_positioning(self, records: Iterable) -> None:
        rows = [(r.category, r.position_period.isoformat(), r.publication_timestamp.isoformat(),
                 r.available_to_strategy_timestamp.isoformat(), r.long, r.short, r.source, r.source_type) for r in records]
        with self._lock, self.raw:
            self.raw.executemany("INSERT OR REPLACE INTO positioning VALUES (?,?,?,?,?,?,?,?)", rows)

    def save_option_snapshot(self, chain) -> None:
        payload = json.dumps(to_jsonable([{"strike": s.strike, "call_oi": s.call_oi, "put_oi": s.put_oi,
                                           "call_change_oi": s.call_change_oi, "put_change_oi": s.put_change_oi}
                                          for s in chain.strikes]))
        with self._lock, self.raw:
            self.raw.execute("INSERT OR REPLACE INTO options_snapshots VALUES (?,?,?,?,?)",
                             (chain.symbol, chain.trade_date.isoformat(), chain.expiry.isoformat(), payload,
                              chain.available_at.isoformat()))

    def save_derived_bars(self, symbol: str, timeframe: str, bars: Iterable) -> None:
        rows = [(symbol, timeframe, b.timestamp.isoformat(), b.close_time.isoformat(), b.open, b.high, b.low, b.close,
                 b.volume) for b in bars]
        with self._lock, self.analytics:
            self.analytics.executemany("INSERT OR REPLACE INTO derived_bars VALUES (?,?,?,?,?,?,?,?,?)", rows)

    def save_volume_profile(self, symbol: str, timeframe: str, end_ts: str, vp) -> None:
        with self._lock, self.analytics:
            self.analytics.execute("DELETE FROM volume_profiles WHERE symbol=? AND timeframe=? AND profile_type=? AND end_ts=?",
                                   (symbol, timeframe, vp.profile_type, end_ts))
            self.analytics.execute("INSERT INTO volume_profiles VALUES (?,?,?,?,?,?,?,?)",
                                   (symbol, timeframe, vp.profile_type, end_ts, vp.poc, vp.vah, vp.val,
                                    json.dumps(to_jsonable(vp.to_dict()))))

    def save_chart_snapshot(self, run_id: str, trade_id: str, kind: str, payload: Dict) -> None:
        with self._lock, self.analytics:
            self.analytics.execute("INSERT OR REPLACE INTO chart_snapshots VALUES (?,?,?,?)",
                                   (trade_id, run_id, kind, json.dumps(to_jsonable(payload))))

    def save_logs(self, entries: Iterable[Dict]) -> None:
        rows = [(e["ts"], e["level"], e["category"], e["message"], json.dumps(to_jsonable(e.get("data") or {})))
                for e in entries]
        with self._lock, self.analytics:
            self.analytics.executemany("INSERT INTO system_logs VALUES (?,?,?,?,?)", rows)

    def log(self, level: str, category: str, message: str, payload: Dict = None) -> None:
        with self._lock, self.analytics:
            self.analytics.execute("INSERT INTO system_logs VALUES (?,?,?,?,?)",
                                   (datetime.now().isoformat(), level, category, message,
                                    json.dumps(to_jsonable(payload or {}))))

    def count(self, table: str) -> int:
        db = self.raw if table in ("ohlcv", "futures_oi", "options_snapshots", "positioning") else self.analytics
        if not table.isidentifier():
            raise ValueError("bad table name")
        return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def trades(self, run_id: str) -> List[Dict]:
        cur = self.analytics.execute("SELECT payload FROM trades WHERE run_id=? ORDER BY entry_ts", (run_id,))
        return [json.loads(r[0]) for r in cur.fetchall()]
