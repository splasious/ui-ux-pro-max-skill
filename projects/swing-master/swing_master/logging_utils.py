"""Structured (JSON) logging with an in-memory ring buffer for the UI (Section 57)."""
from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime
from typing import Deque, Dict, List

CATEGORIES = ("market_data", "pivot", "structure", "zone", "signal", "order", "execution", "stop", "target",
              "error", "connection", "risk", "system")


class RingBufferHandler(logging.Handler):
    def __init__(self, capacity: int = 6000):
        super().__init__()
        self.buffer: Deque[Dict] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        self.buffer.append({
            "ts": getattr(record, "at", None) or datetime.fromtimestamp(record.created).isoformat(timespec="seconds"),
            "level": record.levelname,
            "category": getattr(record, "category", "system"),
            "message": record.getMessage(),
            "data": getattr(record, "data", None),
        })


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"ts": datetime.fromtimestamp(record.created).isoformat(timespec="seconds"),
                           "level": record.levelname, "category": getattr(record, "category", "system"),
                           "message": record.getMessage(), "data": getattr(record, "data", None)}, default=str)


_buffer = RingBufferHandler()
_logger = logging.getLogger("trading_master")
if not _logger.handlers:
    _logger.setLevel(logging.INFO)
    _logger.addHandler(_buffer)
    stream = logging.StreamHandler()
    stream.setFormatter(JsonFormatter())
    stream.setLevel(logging.WARNING)
    _logger.addHandler(stream)


def log(category: str, message: str, level: int = logging.INFO, at: str = None, **data) -> None:
    """``at`` stamps the entry with market time (audit events) instead of wall-clock time."""
    _logger.log(level, message, extra={"category": category, "data": data or None, "at": at})


def clear() -> None:
    _buffer.buffer.clear()


def recent(limit: int = 300, category: str = None) -> List[Dict]:
    items = list(_buffer.buffer)
    if category:
        items = [x for x in items if x["category"] == category]
    return sorted(items, key=lambda x: x["ts"], reverse=True)[:limit]


def counts() -> Dict[str, int]:
    out: Dict[str, int] = {}
    for x in _buffer.buffer:
        out[x["category"]] = out.get(x["category"], 0) + 1
    return out
