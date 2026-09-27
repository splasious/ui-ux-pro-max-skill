"""Notification architecture (Section 47) -- decoupled from strategy logic.

The simulator/strategy only *publishes* events on a ``NotificationBus``.
Channels subscribe to the bus; a failing channel can never affect trading.

Telegram credentials come from ``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_CHAT_ID``
environment variables.  Without them the Telegram channel stays disabled.
"""
from __future__ import annotations

import json
import os
import urllib.request
from collections import deque
from datetime import datetime
from typing import Callable, Deque, Dict, List

EVENT_TYPES = {
    "NEW_READY_SETUP": "New READY setup",
    "TRADE_TRIGGERED": "Trade triggered",
    "SL_MODIFIED": "Stop-loss modified",
    "T1_HIT": "T1 hit", "T2_HIT": "T2 hit", "T3_HIT": "T3 hit",
    "TRAILING_SL_CHANGED": "Trailing stop changed",
    "POSITION_CLOSED": "Position closed",
    "RISK_LIMIT_REACHED": "Risk limit reached",
    "DATA_DISCONNECTED": "Data feed disconnected",
    "BROKER_DISCONNECTED": "Broker disconnected",
}


def format_message(kind: str, payload: Dict) -> str:
    title = EVENT_TYPES.get(kind, kind)
    parts = [f"{k}: {v}" for k, v in payload.items() if k not in ("type",) and v is not None]
    return f"[Swing Master] {title}\n" + "\n".join(parts)


class NotificationBus:
    def __init__(self, history: int = 500):
        self._subs: List[Callable[[str, Dict], None]] = []
        self.history: Deque[Dict] = deque(maxlen=history)
        self.errors: Deque[str] = deque(maxlen=50)

    def subscribe(self, fn: Callable[[str, Dict], None]) -> None:
        self._subs.append(fn)

    def publish(self, kind: str, payload: Dict) -> None:
        self.history.append({"type": kind, "title": EVENT_TYPES.get(kind, kind), "at": datetime.now().isoformat(),
                             **payload})
        for fn in self._subs:
            try:
                fn(kind, payload)
            except Exception as exc:  # channel failures are isolated and recorded
                self.errors.append(f"{getattr(fn, '__name__', fn)}: {exc}")


class TelegramNotifier:
    def __init__(self, token_env: str = "TELEGRAM_BOT_TOKEN", chat_env: str = "TELEGRAM_CHAT_ID",
                 allowed: tuple = tuple(EVENT_TYPES)):
        self.token = os.environ.get(token_env)
        self.chat_id = os.environ.get(chat_env)
        self.allowed = set(allowed)
        self.enabled = bool(self.token and self.chat_id)

    def __call__(self, kind: str, payload: Dict) -> None:
        if not self.enabled or kind not in self.allowed:
            return
        body = json.dumps({"chat_id": self.chat_id, "text": format_message(kind, payload)}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{self.token}/sendMessage", data=body,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5).read()

    def status(self) -> Dict:
        return {"channel": "telegram", "enabled": self.enabled,
                "detail": "configured" if self.enabled else "set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"}
