# Swing Master

A swing-trading research platform for NSE equities and index derivatives. It covers market structure, demand and supply, volume profile, positioning, derivatives context, candlestick confirmation and risk. It includes a setup scanner, backtest and walk-forward labs, a trade journal, and paper execution behind a broker abstraction. The dashboard ships with **five interchangeable themes** and adapts automatically to **phones, tablets, laptops and large desktops**.

> **Demo data is fictional.** Without your own data files the platform runs on a deterministic synthetic market (random walk with regime drift). Everything built on it is labelled `DEMO · ILLUSTRATIVE DATA`. Synthetic data holds no exploitable edge by construction, so the demo backtest shows how the machinery works, not what the strategy is worth. Participant positioning is **never simulated**: it reads `UNAVAILABLE` until a genuine source is loaded.

## Quick start

Python 3.10+ and nothing else: the engine, server and UI use only the standard library and hand-written SVG.

```bash
python3 -m swing_master.main serve --open        # http://127.0.0.1:8765
```

The first start analyses 51 instruments × 1,200 sessions in about 5–8 seconds, using all CPU cores where the OS supports `fork`. Raw and derived data are then written to SQLite in the background.

| Command | What it does |
|---|---|
| `python3 -m swing_master.main serve [--host H] [--port N] [--open]` | Dashboard + JSON API. Use `--host 0.0.0.0` to open it from a phone or tablet on the same network |
| `python3 -m swing_master.main scan` | Print the scanner table and funnel |
| `python3 -m swing_master.main backtest` | Full-history KPIs |
| `python3 -m swing_master.main walkforward` | Walk-forward folds, in-sample vs out-of-sample |
| `python3 -m swing_master.main export-static dist/swing-master.html` | Self-contained, read-only HTML snapshot of the whole UI |
| `python3 research/reference_strategy.py [--csv FILE]` | Phase-A standalone reference strategy |
| `python3 -m unittest discover -s swing_master/tests -t .` | Test suite (70 tests, about 3 s) |

## Works on every screen

The layout re-arranges itself at each size; nothing needs configuring.

| Device | Width | Layout |
|---|---|---|
| Phone | ≤ 760 px | Two-row sticky header (menu, brand, DEMO badge, symbol search, timeframe). Navigation opens as a drawer. The market ribbon appears on Overview only. Tables turn into stacked cards showing the key columns. Charts use fewer, wider candles and a shorter height. |
| Tablet | 761–1100 px | Collapsible icon rail with tooltips, full context bar, two-column card grids |
| Laptop | 1101–1500 px | Full sidebar and top bar; lower-priority header items fold away |
| Desktop / XL | > 1500 px | Everything visible; wider side panels from 1680 px |

On touch devices every control is at least 44 px tall. Charts pan with a drag and zoom with the + / − buttons, and still accept keyboard control (arrows, + / −, 0). Checked with Chromium at 375, 768, 1024, 1280 and 1920 px: no horizontal scrolling on any of the 18 screens.

## Five interchangeable themes

Pick a skin from the palette button in the top bar (on small phones: the Theme entry in the menu) or in **Settings → Theme**. The choice persists per browser; **Auto** follows the system light/dark setting (Daylight / Midnight).

| Skin | Look | Brand treatment |
|---|---|---|
| **Midnight Teal** | deep navy, blue controls, teal mark | IBM Plex Sans, mountain mark |
| **Imperial Gold** | black lacquer, brushed-gold accents, gold-bordered navigation | Cinzel serif, crown mark |
| **Ultraviolet** | indigo night, violet primary, cyan signal | Sora + Plus Jakarta Sans |
| **Daylight** | bright workspace, cobalt accents | Plus Jakarta Sans |
| **Cyan Terminal** | deep-sea navy, instrument cyan, red demo plate | Rajdhani + JetBrains Mono numerals |

All colour lives in `swing_master/dashboard/application_ui/css/themes.css` as tokens. Up candles are drawn hollow and down candles filled, so direction never depends on colour alone.

## Screens

Overview (top long setups, top short setups) · Scanner (1W / 1D / 4H / 1H) · Chart & Structure (with timeframe-alignment and volatility panels) · Demand / Supply · Volume Profile (fixed range 60/120/250, swing, structural leg, daily, weekly, higher-TF) · Positioning · Derivatives (ATM ± 5/10/15, per-strike OI and ΔOI) · Candlesticks · Trade Setup ("why trade / why no trade", timeframe alignment) · Active Trades (with semi-auto order proposals) · Risk · Backtest (ablation + factor attribution) · Walk-Forward · Journal · Rejected Signals · Reports · Data Health (audit log with category filters) · Settings (themes, parameters, notifications, rule definitions).

## Decision chain

```text
Higher-TF context → confirmed ZigZag pivots → HH/HL/LH/LL → BOS/CHoCH → demand/supply
→ volume profile (POC/VAH/VAL/HVN/LVN) → commercial / institutional / retail positioning
→ futures OI state → PCR / ΔOI PCR → candlestick reversal → confluence score
→ entry → structural stop → position size → T1 (30%) → T2 (30%) → runner (40%)
→ confirmed HL/LH trailing stop → T3 / structural exit
```

Every rule lives once in `swing_master/strategy/signal_engine.py` (entries) and `swing_master/strategy/trade_manager.py` (trade lifecycle). Portfolio events (daily-loss breach, maximum-drawdown halt) flatten positions from the backtest engine. The backtester, walk-forward lab, scanner and paper session all call the same functions.

## Chronological integrity (no look-ahead)

* Bars carry `timestamp` (open) and `close_time`. Nothing in a bar is usable before its close.
* A pivot is usable only when `current_time >= confirmation_timestamp`. The chart marks every confirmation bar with ◇.
* Zones are created at the close of the leg-out candle.
* Higher-timeframe candles are used only once their period has closed. This includes the weekly and monthly charts and the weekly scanner, which exclude the forming candle.
* Futures OI and option chains are read as of their publication time. Positioning is read as of `available_to_strategy_timestamp`.
* Stops and targets hit inside the same bar count as the stop. Stops only ever tighten.

The test suite proves these properties rather than asserting them in prose. The key check is **truncation invariance**: every decision at bar *k* is identical whether or not later bars exist. `research/reference_strategy.py`, an independent implementation, must agree with production on ATR, pivots, labels, volume profile and sizing.

## Using real data

Set `SM_DATA_SOURCE=CSV` and `SM_DATA_DIR=/path/to/data`; the file formats are in [`sample_data/README.md`](sample_data/README.md). Participant positioning can be loaded from NSE's participant-wise OI file via `SM_POSITIONING_CSV`. Mapping: Client → Retail, FII + DII → Institutional, Pro → Commercial.

## F&O-only universe

By default Swing Master scans and trades **NSE F&O underlyings only** (`SM_UNIVERSE=FNO`). A stock qualifies when it has exchange-traded stock futures. Index underlyings with futures (NIFTY, BANKNIFTY, FINNIFTY, ...) stay in as market-context anchors. The scanner, backtest, walk-forward, proposals and paper trading all use the same filtered list.

| Variable | Effect |
|---|---|
| `SM_UNIVERSE=FNO` (default) | Keep stocks with futures (`has_futures=1` in `universe.csv`) plus index anchors |
| `SM_FNO_LIST=/path/fo_mktlots.csv` | Use the exchange's current F&O list instead. NSE's `fo_mktlots.csv` works unchanged, and its lot sizes replace the ones in `universe.csv`. A CSV with a `SYMBOL` column or a text file with one symbol per line also works |
| `SM_UNIVERSE=ALL` | No filter |

The top bar, the sidebar and the scanner funnel show which universe is active. Data Health logs how many symbols were excluded.

## Deploying to Vercel

Two ways, both producing the same static site:

* **Project linked to GitHub** (needs a GitHub login connection on the Vercel account): set the project's **Root Directory** to this folder (`projects/swing-master` in the monorepo, or the repository root in a standalone checkout). `vercel.json` then runs `python3 -m swing_master.main export-static public/index.html` on every push.
* **No GitHub link:** deploy the two files in [`deploy/vercel/`](deploy/vercel). Their build script clones the public branch, then runs the same export. `SM_GIT_REPO`, `SM_GIT_REF` and `SM_GIT_SUBDIR` choose the source. Redeploy to pick up new commits.

The build takes about 30 s and needs only the Python 3 and git that ship in Vercel's build image.

Vercel runs short-lived functions without a persistent disk, so the live engine does not run there. Paper trading, settings changes, background scans and Telegram alerts belong on an always-on host next to the market data (for example a VPS running `python3 -m swing_master.main serve --host 0.0.0.0`). The Vercel site shows a snapshot taken at build time.

## Execution modes and safety

`BACKTEST`, `PAPER` (default), `MANUAL` (proposals only), `SEMI_AUTO` (the system proposes, you confirm on Active Trades) and `AUTO`. `AUTO` refuses to start unless `SM_LIVE_TRADING_ENABLED=1` **and** a validated research record is supplied. Every order passes the `SafeBrokerGateway`, which enforces:

- duplicate-order prevention
- rate limiting
- retries on network errors only
- kill switch
- maximum daily loss and maximum open risk
- order reconciliation

A Zerodha Kite adapter is included but never constructed automatically. Credentials are read from environment variables (`KITE_API_KEY`, `KITE_ACCESS_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) and are never stored in files.

## Documentation

* [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): directory tree, schemas, configuration, scoring, backtest assumptions, and the build brief section by section.
