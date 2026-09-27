"""Application settings.

Secrets are NEVER stored here -- only the names of the environment variables
that hold them.  Everything can be overridden with ``SM_*`` environment vars.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PACKAGE_ROOT.parent


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class AppSettings:
    APP_NAME: str = "Swing Master"
    VERSION: str = "0.1.0"
    HOST: str = field(default_factory=lambda: _env("SM_HOST", "127.0.0.1"))
    PORT: int = field(default_factory=lambda: int(_env("SM_PORT", "8765")))

    # DEMO -> deterministic synthetic data, clearly labelled everywhere.
    # CSV  -> historical files from DATA_DIR (see data/historical.py for the format).
    DATA_SOURCE: str = field(default_factory=lambda: _env("SM_DATA_SOURCE", "DEMO"))
    DATA_DIR: Path = field(default_factory=lambda: Path(_env("SM_DATA_DIR", str(PROJECT_ROOT / "sample_data"))))
    POSITIONING_CSV: str = field(default_factory=lambda: _env("SM_POSITIONING_CSV", ""))

    # FNO -> NSE F&O underlyings only (stocks with futures + index anchors); ALL -> no filter.
    UNIVERSE: str = field(default_factory=lambda: _env("SM_UNIVERSE", "FNO"))
    # Optional current F&O list (NSE fo_mktlots.csv, a CSV with a SYMBOL column, or one symbol per line).
    FNO_LIST: str = field(default_factory=lambda: _env("SM_FNO_LIST", ""))

    DEMO_SEED: int = field(default_factory=lambda: int(_env("SM_DEMO_SEED", "123")))
    DEMO_START: str = field(default_factory=lambda: _env("SM_DEMO_START", "2022-01-03"))
    DEMO_END: str = field(default_factory=lambda: _env("SM_DEMO_END", "2026-09-25"))

    STATE_DIR: Path = field(default_factory=lambda: Path(_env("SM_STATE_DIR", str(PROJECT_ROOT / ".state"))))

    EXECUTION_MODE: str = field(default_factory=lambda: _env("SM_EXECUTION_MODE", "PAPER"))
    # Live broker execution stays disabled until research has been validated.
    LIVE_TRADING_ENABLED: bool = field(default_factory=lambda: _env("SM_LIVE_TRADING_ENABLED", "0") == "1")
    PAPER_REPLAY_BARS: int = 120

    # Names of environment variables only -- never values.
    KITE_API_KEY_ENV: str = "KITE_API_KEY"
    KITE_ACCESS_TOKEN_ENV: str = "KITE_ACCESS_TOKEN"
    TELEGRAM_TOKEN_ENV: str = "TELEGRAM_BOT_TOKEN"
    TELEGRAM_CHAT_ENV: str = "TELEGRAM_CHAT_ID"

    LOG_LEVEL: str = field(default_factory=lambda: _env("SM_LOG_LEVEL", "INFO"))

    @property
    def raw_db_path(self) -> Path:
        return self.STATE_DIR / "market_raw.sqlite3"

    @property
    def analytics_db_path(self) -> Path:
        return self.STATE_DIR / "analytics.sqlite3"

    @property
    def is_demo(self) -> bool:
        return self.DATA_SOURCE.upper() == "DEMO"
