"""Low-level helpers for constructing and sending Philips SICP frames."""

from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 5000
FRAME_SIZE = 0x09
CONTROL_BYTE = 0x01
GROUP_BYTE = 0x00
CMD_SET = 0xF3
CMD_GET = 0xF4
POWER_CONTROL = 0x18

DEFAULT_TIMEOUT = 5.0
DEFAULT_RETRIES = 2
DEFAULT_RETRY_DELAY = 1.0


class ProtocolError(RuntimeError):
    """Raised when a SICP reply is malformed."""


@dataclass
class LedStatus:
    """Represents the LED colour and on/off state returned by the panel."""

    is_on: bool
    red: int
    green: int
    blue: int

    @property
    def hex_color(self) -> str:
        return f"#{self.red:02X}{self.green:02X}{self.blue:02X}"


@dataclass
class PowerStatus:
    """Represents the power status returned by the panel."""

    is_on: Optional[bool]


def _clamp_color(value: int) -> int:
    if not 0 <= value <= 255:
        raise ValueError("color values must be in range 0-255")
    return value


def _checksum(frame: Iterable[int]) -> int:
    value = 0
    for byte in frame:
        value ^= byte
    return value


def parse_hex_color(color: str) -> Tuple[int, int, int]:
    if not color:
        raise ValueError("color must be provided")
    normalized = color.strip()
    if normalized.startswith("#"):
        normalized = normalized[1:]
    if len(normalized) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in normalized):
        raise ValueError("expected hex format RRGGBB")
    red = int(normalized[0:2], 16)
    green = int(normalized[2:4], 16)
    blue = int(normalized[4:6], 16)
    return red, green, blue


def build_set_frame(*, on: bool, red: int, green: int, blue: int) -> bytes:
    red = _clamp_color(red if on else 0)
    green = _clamp_color(green if on else 0)
    blue = _clamp_color(blue if on else 0)
    parts: List[int] = [
        FRAME_SIZE,
        CONTROL_BYTE,
        GROUP_BYTE,
        CMD_SET,
        0x01 if on else 0x00,
        red,
        green,
        blue,
    ]
    parts.append(_checksum(parts))
    return bytes(parts)


def build_get_frame() -> bytes:
    parts: List[int] = [
        FRAME_SIZE,
        CONTROL_BYTE,
        GROUP_BYTE,
        CMD_GET,
        0x00,
        0x00,
        0x00,
        0x00,
    ]
    parts.append(_checksum(parts))
    return bytes(parts)


def build_power_frame(*, on: bool) -> bytes:
    parts: List[int] = [
        0x06,
        0x00,
        0x00,
        POWER_CONTROL,
        0x02 if on else 0x01,
    ]
    parts.append(_checksum(parts))
    return bytes(parts)


def build_power_query_frame() -> bytes:
    """Best-effort power status frame.

    The Philips SICP documentation exposes a power control function on command ``0x18``.
    Empirically the panel accepts ``0x00`` as a "query" verb, replying with the current
    power state in the acknowledgement payload.  Some firmwares always echo the last
    command instead of responding with the real state; callers should therefore treat
    the result as a best-effort hint.
    """

    parts: List[int] = [
        0x06,
        0x00,
        0x00,
        POWER_CONTROL,
        0x00,
    ]
    parts.append(_checksum(parts))
    return bytes(parts)


def send_frame(
    host: str,
    port: int,
    frame: bytes,
    *,
    timeout: float,
    expect_reply: bool,
) -> bytes:
    _LOGGER.debug("Connecting to %s:%s (timeout %.1fs)", host, port, timeout)
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            _LOGGER.debug("Connected. Sending %s", format_frame(frame))
            sock.sendall(frame)
            if not expect_reply:
                _LOGGER.debug("No reply requested; returning after send.")
                return b""
            sock.settimeout(timeout)
            first = sock.recv(1)
            if not first:
                raise ProtocolError("Connection closed without reply data")
            expected = first[0]
            received = bytearray(first)
            while len(received) < expected:
                chunk = sock.recv(expected - len(received))
                if not chunk:
                    break
                received.extend(chunk)
            if len(received) != expected:
                _LOGGER.warning(
                    "Expected %s bytes but only received %s: %s",
                    expected,
                    len(received),
                    format_frame(received),
                )
            else:
                _LOGGER.debug("Received reply: %s", format_frame(received))
            return bytes(received)
    except OSError as exc:
        _LOGGER.debug("Socket error while communicating with %s:%s: %s", host, port, exc)
        raise ConnectionError(f"Unable to reach {host}:{port} ({exc})") from exc


def send_with_retries(
    *,
    host: str,
    port: int,
    frame: bytes,
    timeout: float = DEFAULT_TIMEOUT,
    expect_reply: bool,
    retries: int = DEFAULT_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY,
) -> bytes:
    attempts = max(1, retries + 1)
    for attempt in range(1, attempts + 1):
        try:
            return send_frame(
                host,
                port,
                frame,
                timeout=timeout,
                expect_reply=expect_reply,
            )
        except ConnectionError as exc:
            if attempt == attempts:
                raise
            _LOGGER.warning(
                "Attempt %s/%s failed communicating with %s:%s - %s", attempt, attempts, host, port, exc
            )
            if retry_delay > 0:
                time.sleep(retry_delay)
    return b""


def format_frame(frame: bytes) -> str:
    return " ".join(f"{byte:02X}" for byte in frame)


def parse_led_reply(reply: bytes) -> LedStatus:
    if len(reply) < 8:
        raise ProtocolError(f"Unexpected LED reply length ({len(reply)} bytes)")
    is_on = reply[4] == 0x01
    red, green, blue = reply[5], reply[6], reply[7]
    return LedStatus(is_on=is_on, red=red, green=green, blue=blue)


def parse_power_reply(reply: bytes) -> PowerStatus:
    if not reply:
        raise ProtocolError("Empty power reply")
    if reply[0] != len(reply):
        _LOGGER.debug("Power reply reported %s bytes but got %s", reply[0], len(reply))
    if len(reply) >= 5:
        indicator = reply[4]
        if indicator in (0x00, 0x01, 0x02):
            # 0x01 tends to represent "off", 0x02 represents "on" on known panels.
            if indicator == 0x00:
                return PowerStatus(is_on=None)
            return PowerStatus(is_on=indicator == 0x02)
    return PowerStatus(is_on=None)
