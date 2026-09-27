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
    def __init__(self, capacity: int = 2000):
        super().__init__()
        self.buffer: Deque[Dict] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        self.buffer.append({
            "ts": datetime.fromtimestamp(record.created).isoformat(timespec="seconds"),
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


def log(category: str, message: str, level: int = logging.INFO, **data) -> None:
    _logger.log(level, message, extra={"category": category, "data": data or None})


def recent(limit: int = 300, category: str = None) -> List[Dict]:
    items = list(_buffer.buffer)
    if category:
        items = [x for x in items if x["category"] == category]
    return items[-limit:][::-1]
