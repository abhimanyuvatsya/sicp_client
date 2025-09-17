"""Networking helpers for communicating with Philips SICP displays."""
from __future__ import annotations

import logging
import socket
import time
from typing import Callable

from .protocol import format_frame

LOGGER = logging.getLogger(__name__)


class ConnectionError(RuntimeError):
    """Raised when the controller cannot reach a panel."""


def send_frame(
    host: str,
    port: int,
    frame: bytes,
    *,
    timeout: float,
    expect_reply: bool,
) -> bytes:
    LOGGER.debug("Connecting to %s:%s (timeout=%ss)", host, port, timeout)
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            LOGGER.debug("Connected. Sending %s bytes: %s", len(frame), format_frame(frame))
            sock.sendall(frame)
            if not expect_reply:
                LOGGER.debug("No reply requested; returning after send.")
                return b""
            sock.settimeout(timeout)
            LOGGER.debug("Waiting for reply...")
            first = sock.recv(1)
            if not first:
                LOGGER.debug("Connection closed without data.")
                return b""
            expected = first[0]
            LOGGER.debug("First byte indicates %s total bytes in reply.", expected)
            received = bytearray(first)
            while len(received) < expected:
                try:
                    chunk = sock.recv(expected - len(received))
                except socket.timeout:
                    LOGGER.debug("Timed out while waiting for additional reply bytes.")
                    break
                if not chunk:
                    LOGGER.debug("Socket closed before full reply was received.")
                    break
                received.extend(chunk)
            LOGGER.debug("Received %s bytes in reply: %s", len(received), format_frame(received))
            return bytes(received)
    except OSError as exc:
        LOGGER.debug("Connection attempt failed: %s", exc)
        raise ConnectionError(f"Unable to reach {host}:{port} ({exc})") from exc


def send_with_retries(
    *,
    host: str,
    port: int,
    frame: bytes,
    timeout: float,
    expect_reply: bool,
    retries: int,
    retry_delay: float,
    retry_hook: Callable[[int, int], None] | None = None,
) -> bytes:
    attempts = max(1, retries + 1)
    for attempt in range(1, attempts + 1):
        LOGGER.debug("Send attempt %s/%s", attempt, attempts)
        try:
            return send_frame(
                host,
                port,
                frame,
                timeout=timeout,
                expect_reply=expect_reply,
            )
        except ConnectionError:
            LOGGER.debug("Attempt %s failed", attempt, exc_info=True)
            if attempt == attempts:
                raise
            if retry_delay > 0:
                if retry_hook is not None:
                    retry_hook(attempt, attempts)
                LOGGER.debug("Waiting %ss before retrying", retry_delay)
                time.sleep(retry_delay)
    return b""
