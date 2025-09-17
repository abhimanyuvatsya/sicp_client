"""In-memory logging buffer for the web UI."""

from __future__ import annotations

import logging
from collections import deque
from typing import Deque, Iterable, Tuple


class MemoryLogHandler(logging.Handler):
    """Stores recent log messages in memory."""

    def __init__(self, max_entries: int = 1000) -> None:
        super().__init__()
        self._buffer: Deque[Tuple[int, str]] = deque(maxlen=max_entries)
        self._formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - simple storage
        msg = self._formatter.format(record)
        self._buffer.append((record.levelno, msg))

    def entries(self) -> Iterable[Tuple[int, str]]:
        return list(self._buffer)

    def clear(self) -> None:
        self._buffer.clear()
