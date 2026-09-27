"""SQLite schemas (Section 50).  Raw market data and derived analytics live in
separate database files so derived tables can be rebuilt without touching
source data."""

RAW_SCHEMA = """
CREATE TABLE IF NOT EXISTS ohlcv (
    symbol TEXT NOT NULL, timeframe TEXT NOT NULL, ts TEXT NOT NULL, close_time TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL, source TEXT,
    PRIMARY KEY (symbol, timeframe, ts));
CREATE TABLE IF NOT EXISTS futures_oi (
    symbol TEXT NOT NULL, trade_date TEXT NOT NULL, close REAL, open_interest REAL, change_in_oi REAL,
    available_at TEXT, source TEXT, PRIMARY KEY (symbol, trade_date));
CREATE TABLE IF NOT EXISTS options_snapshots (
    symbol TEXT NOT NULL, trade_date TEXT NOT NULL, expiry TEXT, payload TEXT, available_at TEXT,
    PRIMARY KEY (symbol, trade_date));
CREATE TABLE IF NOT EXISTS positioning (
    category TEXT NOT NULL, position_period TEXT NOT NULL, publication_ts TEXT, available_ts TEXT,
    long REAL, short REAL, source TEXT, source_type TEXT, PRIMARY KEY (category, position_period));
"""

ANALYTICS_SCHEMA = """
CREATE TABLE IF NOT EXISTS derived_bars (
    symbol TEXT, timeframe TEXT, ts TEXT, close_time TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (symbol, timeframe, ts));
CREATE TABLE IF NOT EXISTS pivots (
    symbol TEXT, timeframe TEXT, seq INTEGER, pivot_type TEXT, price REAL, pivot_ts TEXT, confirmation_ts TEXT,
    label TEXT, reversal_atr REAL, PRIMARY KEY (symbol, timeframe, seq));
CREATE TABLE IF NOT EXISTS structure_events (
    symbol TEXT, timeframe TEXT, event_ts TEXT, event_type TEXT, direction TEXT, level REAL,
    previous_structure TEXT, current_structure TEXT);
CREATE TABLE IF NOT EXISTS zones (
    zone_id TEXT PRIMARY KEY, symbol TEXT, timeframe TEXT, zone_type TEXT, pattern TEXT, proximal REAL,
    distal REAL, creation_ts TEXT, status TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS volume_profiles (
    symbol TEXT, timeframe TEXT, profile_type TEXT, end_ts TEXT, poc REAL, vah REAL, val REAL, payload TEXT);
CREATE TABLE IF NOT EXISTS signals (
    eval_id TEXT, run_id TEXT, ts TEXT, symbol TEXT, direction TEXT, status TEXT, score REAL, payload TEXT);
CREATE TABLE IF NOT EXISTS rejected_signals (
    eval_id TEXT, run_id TEXT, ts TEXT, symbol TEXT, direction TEXT, reason TEXT, score REAL, min_score REAL,
    payload TEXT);
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY, run_id TEXT, symbol TEXT, side TEXT, qty INTEGER, status TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS trades (
    trade_id TEXT, run_id TEXT, symbol TEXT, direction TEXT, entry_ts TEXT, exit_ts TEXT, entry REAL,
    exit REAL, qty INTEGER, net_pnl REAL, r_multiple REAL, exit_reason TEXT, payload TEXT,
    PRIMARY KEY (trade_id, run_id));
CREATE TABLE IF NOT EXISTS risk_states (run_id TEXT, ts TEXT, equity REAL, open_risk REAL, positions INTEGER);
CREATE TABLE IF NOT EXISTS performance (run_id TEXT PRIMARY KEY, label TEXT, created_ts TEXT, config TEXT,
    metrics TEXT);
CREATE TABLE IF NOT EXISTS system_logs (ts TEXT, level TEXT, category TEXT, message TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS chart_snapshots (trade_id TEXT, run_id TEXT, kind TEXT, payload TEXT,
    PRIMARY KEY (trade_id, run_id, kind));
"""
