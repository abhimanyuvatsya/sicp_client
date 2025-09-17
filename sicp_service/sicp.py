"""Low-level Philips SICP protocol implementation."""

from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass
from typing import Iterable, Optional

LOGGER = logging.getLogger(__name__)

FRAME_SIZE = 0x09
CONTROL_BYTE = 0x01
GROUP_BYTE = 0x00
CMD_SET = 0xF3
CMD_GET = 0xF4
CMD_POWER = 0x18
DEFAULT_TIMEOUT = 3.0
DEFAULT_RETRIES = 2
DEFAULT_RETRY_DELAY = 1.0


class SICPError(Exception):
    """Base class for SICP related errors."""


class SICPValidationError(SICPError):
    """Raised when protocol frames cannot be parsed."""


@dataclass
class LEDStatus:
    """Represents the LED state retrieved from a tablet."""

    on: bool
    red: int
    green: int
    blue: int


@dataclass
class TabletStatus:
    """Represents the full tablet state."""

    led: LEDStatus
    power_on: Optional[bool]


def _clamp_color(value: int) -> int:
    if not 0 <= value <= 255:
        raise ValueError("color values must be in range 0-255")
    return value


def _checksum(frame: Iterable[int]) -> int:
    value = 0
    for byte in frame:
        value ^= byte
    return value


def build_set_frame(*, on: bool, red: int, green: int, blue: int) -> bytes:
    red = _clamp_color(red if on else 0)
    green = _clamp_color(green if on else 0)
    blue = _clamp_color(blue if on else 0)
    parts = [
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
    parts = [
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
    parts = [
        0x06,
        0x00,
        0x00,
        CMD_POWER,
        0x02 if on else 0x01,
    ]
    parts.append(_checksum(parts))
    return bytes(parts)


def build_power_query_frame() -> bytes:
    parts = [
        0x06,
        0x00,
        0x00,
        CMD_POWER,
        0x00,
    ]
    parts.append(_checksum(parts))
    return bytes(parts)


def parse_led_status(frame: bytes) -> LEDStatus:
    if len(frame) < 8:
        raise SICPValidationError(f"Frame too short to parse LED status: {frame.hex()}")
    if frame[3] not in {CMD_SET, CMD_GET}:
        raise SICPValidationError(f"Unexpected command byte in reply: {frame[3]:02X}")
    led_on = frame[4] == 0x01
    red, green, blue = frame[5], frame[6], frame[7]
    return LEDStatus(on=led_on, red=red, green=green, blue=blue)


def parse_power_reply(frame: bytes) -> Optional[bool]:
    if len(frame) < 5:
        return None
    if frame[3] != CMD_POWER:
        return None
    if frame[4] == 0x02:
        return True
    if frame[4] == 0x01:
        return False
    return None


def format_frame(frame: bytes) -> str:
    return " ".join(f"{byte:02X}" for byte in frame)


class SICPClient:
    """Blocking client for communicating with Philips tablets."""

    def __init__(self, host: str, port: int = 5000) -> None:
        self.host = host
        self.port = port

    def send_frame(
        self,
        frame: bytes,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        expect_reply: bool = True,
    ) -> bytes:
        LOGGER.debug("Connecting to %s:%s", self.host, self.port)
        try:
            with socket.create_connection((self.host, self.port), timeout=timeout) as sock:
                LOGGER.debug("Connected. Sending %s", format_frame(frame))
                sock.sendall(frame)
                if not expect_reply:
                    LOGGER.debug("Send complete; no reply requested")
                    return b""
                sock.settimeout(timeout)
                reply = self._receive_reply(sock)
                LOGGER.debug("Received reply: %s", format_frame(reply))
                return reply
        except OSError as exc:
            raise SICPError(f"Unable to reach {self.host}:{self.port}: {exc}") from exc

    def _receive_reply(self, sock: socket.socket) -> bytes:
        first = sock.recv(1)
        if not first:
            raise SICPError("Connection closed before reply received")
        expected = first[0]
        received = bytearray(first)
        while len(received) < expected:
            chunk = sock.recv(expected - len(received))
            if not chunk:
                raise SICPError("Socket closed before full reply was received")
            received.extend(chunk)
        return bytes(received)

    def _send_with_retries(
        self,
        frame: bytes,
        *,
        timeout: float,
        expect_reply: bool,
        retries: int,
        retry_delay: float,
    ) -> bytes:
        attempts = max(1, retries + 1)
        last_error: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            try:
                return self.send_frame(frame, timeout=timeout, expect_reply=expect_reply)
            except SICPError as exc:
                last_error = exc
                LOGGER.warning(
                    "Attempt %s/%s failed communicating with %s:%s: %s",
                    attempt,
                    attempts,
                    self.host,
                    self.port,
                    exc,
                )
                if attempt < attempts:
                    time.sleep(max(0.0, retry_delay))
        if last_error:
            raise last_error
        raise SICPError("Unknown error while sending frame")

    def set_led(
        self,
        *,
        on: bool,
        red: int,
        green: int,
        blue: int,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY,
    ) -> LEDStatus:
        frame = build_set_frame(on=on, red=red, green=green, blue=blue)
        reply = self._send_with_retries(
            frame,
            timeout=timeout,
            expect_reply=True,
            retries=retries,
            retry_delay=retry_delay,
        )
        status = parse_led_status(reply)
        return status

    def get_led_status(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY,
    ) -> LEDStatus:
        frame = build_get_frame()
        reply = self._send_with_retries(
            frame,
            timeout=timeout,
            expect_reply=True,
            retries=retries,
            retry_delay=retry_delay,
        )
        return parse_led_status(reply)

    def set_power(
        self,
        *,
        on: bool,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY,
    ) -> Optional[bool]:
        frame = build_power_frame(on=on)
        reply = self._send_with_retries(
            frame,
            timeout=timeout,
            expect_reply=True,
            retries=retries,
            retry_delay=retry_delay,
        )
        return parse_power_reply(reply)

    def get_power_status(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY,
    ) -> Optional[bool]:
        frame = build_power_query_frame()
        reply = self._send_with_retries(
            frame,
            timeout=timeout,
            expect_reply=True,
            retries=retries,
            retry_delay=retry_delay,
        )
        return parse_power_reply(reply)

    def get_status(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY,
    ) -> TabletStatus:
        led = self.get_led_status(timeout=timeout, retries=retries, retry_delay=retry_delay)
        power = self.get_power_status(timeout=timeout, retries=retries, retry_delay=retry_delay)
        return TabletStatus(led=led, power_on=power)
