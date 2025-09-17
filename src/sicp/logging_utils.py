"""Logging helpers for the SICP controller."""
from __future__ import annotations

import logging
from collections import deque
from typing import Deque, Iterable, List


class RingBufferHandler(logging.Handler):
    """Store recent log records in memory for the web UI."""

    def __init__(self, capacity: int = 2000):
        super().__init__()
        self.capacity = capacity
        self._records: Deque[logging.LogRecord] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        self._records.append(record)

    def clear(self) -> None:
        self._records.clear()

    def records(self) -> Iterable[logging.LogRecord]:
        return list(self._records)

    def formatted_records(self) -> List[str]:
        formatter = self.formatter or logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        return [formatter.format(record) for record in self._records]
