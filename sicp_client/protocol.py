"""Low level Philips SICP helpers."""

from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

LOGGER = logging.getLogger(__name__)

DEFAULT_HOST = "192.168.2.98"
DEFAULT_PORT = 5000
DEFAULT_TIMEOUT = 5.0
DEFAULT_RETRIES = 2
DEFAULT_RETRY_DELAY = 1.0

FRAME_SIZE = 0x09
CONTROL_BYTE = 0x01
GROUP_BYTE = 0x00
CMD_SET = 0xF3
CMD_GET = 0xF4
CMD_POWER_SET = 0x18
CMD_POWER_GET = 0x19


class ProtocolError(RuntimeError):
    """Raised when a received frame could not be parsed."""


@dataclass
class LedState:
    """Represents LED state returned by the panel."""

    on: bool
    red: int
    green: int
    blue: int

    @property
    def hex_color(self) -> str:
        return f"#{self.red:02X}{self.green:02X}{self.blue:02X}"


@dataclass
class PowerState:
    """Represents panel power state."""

    on: bool


@dataclass
class TabletState:
    power: PowerState
    led: LedState


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
        CMD_POWER_SET,
        0x02 if on else 0x01,
    ]
    parts.append(_checksum(parts))
    return bytes(parts)


def build_power_status_frame() -> bytes:
    parts: List[int] = [
        0x06,
        0x00,
        0x00,
        CMD_POWER_GET,
        0x00,
    ]
    parts.append(_checksum(parts))
    return bytes(parts)


def format_frame(frame: bytes) -> str:
    return " ".join(f"{byte:02X}" for byte in frame)


def _parse_led_state(frame: bytes) -> LedState:
    if len(frame) < 8:
        raise ProtocolError("Unexpected LED state frame length")
    if frame[3] != CMD_GET:
        raise ProtocolError(f"Unexpected command byte in LED frame: 0x{frame[3]:02X}")
    on_flag = frame[4] == 0x01
    red, green, blue = frame[5], frame[6], frame[7]
    return LedState(on=on_flag and any((red, green, blue)), red=red, green=green, blue=blue)


def _parse_power_state(frame: bytes) -> PowerState:
    if len(frame) < 5:
        raise ProtocolError("Unexpected power state frame length")
    if frame[3] != CMD_POWER_GET:
        raise ProtocolError(f"Unexpected command byte in power frame: 0x{frame[3]:02X}")
    payload = frame[4]
    if payload not in (0x01, 0x02):
        raise ProtocolError(f"Unexpected power payload byte: 0x{payload:02X}")
    return PowerState(on=payload == 0x02)


def send_frame(
    host: str,
    port: int,
    frame: bytes,
    *,
    timeout: float,
    expect_reply: bool,
) -> bytes:
    LOGGER.debug("Connecting to %s:%s (timeout %.1fs)", host, port, timeout)
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
) -> bytes:
    attempts = max(1, retries + 1)
    last_error: Optional[Exception] = None
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
        except ConnectionError as exc:
            last_error = exc
            LOGGER.warning("Attempt %s failed: %s", attempt, exc)
            if attempt == attempts:
                break
            if retry_delay > 0:
                LOGGER.debug("Waiting %.2fs before retrying", retry_delay)
                time.sleep(retry_delay)
    assert last_error is not None
    raise last_error


def query_led_state(
    *,
    host: str,
    port: int,
    timeout: float,
    retries: int = DEFAULT_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY,
) -> LedState:
    frame = build_get_frame()
    reply = send_with_retries(
        host=host,
        port=port,
        frame=frame,
        timeout=timeout,
        expect_reply=True,
        retries=retries,
        retry_delay=retry_delay,
    )
    if not reply:
        raise ProtocolError("Empty LED state reply")
    return _parse_led_state(reply)


def query_power_state(
    *,
    host: str,
    port: int,
    timeout: float,
    retries: int = DEFAULT_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY,
) -> PowerState:
    frame = build_power_status_frame()
    reply = send_with_retries(
        host=host,
        port=port,
        frame=frame,
        timeout=timeout,
        expect_reply=True,
        retries=retries,
        retry_delay=retry_delay,
    )
    if not reply:
        raise ProtocolError("Empty power state reply")
    return _parse_power_state(reply)


def set_led_state(
    *,
    host: str,
    port: int,
    on: bool,
    red: int,
    green: int,
    blue: int,
    timeout: float,
    retries: int = DEFAULT_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY,
) -> LedState:
    frame = build_set_frame(on=on, red=red, green=green, blue=blue)
    send_with_retries(
        host=host,
        port=port,
        frame=frame,
        timeout=timeout,
        expect_reply=False,
        retries=retries,
        retry_delay=retry_delay,
    )
    confirmation = query_led_state(
        host=host,
        port=port,
        timeout=timeout,
        retries=retries,
        retry_delay=retry_delay,
    )
    if confirmation.on != on or (
        confirmation.red != (red if on else 0)
        or confirmation.green != (green if on else 0)
        or confirmation.blue != (blue if on else 0)
    ):
        raise ProtocolError("LED confirmation mismatch")
    return confirmation


def set_power_state(
    *,
    host: str,
    port: int,
    on: bool,
    timeout: float,
    retries: int = DEFAULT_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY,
) -> PowerState:
    frame = build_power_frame(on=on)
    send_with_retries(
        host=host,
        port=port,
        frame=frame,
        timeout=timeout,
        expect_reply=False,
        retries=retries,
        retry_delay=retry_delay,
    )
    confirmation = query_power_state(
        host=host,
        port=port,
        timeout=timeout,
        retries=retries,
        retry_delay=retry_delay,
    )
    if confirmation.on != on:
        raise ProtocolError("Power confirmation mismatch")
    return confirmation
