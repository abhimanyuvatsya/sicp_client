"""Logging helpers."""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Deque, Iterable, List


@dataclass
class LogRecord:
    created: datetime
    level: str
    logger: str
    message: str

    def as_dict(self) -> dict:
        return {
            "created": self.created.isoformat(),
            "level": self.level,
            "logger": self.logger,
            "message": self.message,
        }


class InMemoryLogHandler(logging.Handler):
    """Stores the most recent log records in memory for display in the web UI."""

    def __init__(self, capacity: int = 500) -> None:
        super().__init__()
        self.capacity = capacity
        self._records: Deque[LogRecord] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        message = self.format(record)
        log_record = LogRecord(
            created=datetime.fromtimestamp(record.created),
            level=record.levelname,
            logger=record.name,
            message=message,
        )
        with self._lock:
            self._records.append(log_record)

    def get_records(self) -> List[LogRecord]:
        with self._lock:
            return list(self._records)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def iter_dicts(self) -> Iterable[dict]:
        for record in self.get_records():
            yield record.as_dict()
