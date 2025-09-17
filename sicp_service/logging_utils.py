"""Logging utilities for the SICP service."""

from __future__ import annotations

import logging
from collections import deque
from typing import Deque, Iterable, List


class LogBufferHandler(logging.Handler):
    """In-memory logging handler for exposing recent log lines."""

    def __init__(self, capacity: int = 1000) -> None:
        super().__init__()
        self.capacity = capacity
        self._records: Deque[str] = deque(maxlen=capacity)
        self.formatter = logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:  # pylint: disable=broad-except
            self.handleError(record)
            return
        self._records.append(msg)

    def get_lines(self) -> List[str]:
        return list(self._records)

    def clear(self) -> None:
        self._records.clear()


def configure_logging(buffer_handler: LogBufferHandler, *, log_file: str | None = None) -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(buffer_handler.formatter)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(buffer_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(buffer_handler.formatter)
        root_logger.addHandler(file_handler)
