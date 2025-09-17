"""Helpers for building and parsing Philips SICP frames."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Tuple

FRAME_SIZE = 0x09
CONTROL_BYTE = 0x01
GROUP_BYTE = 0x00
CMD_SET = 0xF3
CMD_GET = 0xF4
CMD_POWER = 0x18


class ProtocolError(Exception):
    """Raised when a SICP frame cannot be parsed."""


@dataclass
class LedState:
    """Represents the state of the LED accent strip."""

    on: bool
    red: int
    green: int
    blue: int

    def as_hex(self) -> str:
        return f"#{self.red:02X}{self.green:02X}{self.blue:02X}"


@dataclass
class PowerState:
    """Represents the power state of the display."""

    on: bool


@dataclass
class TabletStatus:
    """Combined LED and power status returned by GET frames."""

    led: LedState
    power: PowerState


def _clamp_color(value: int) -> int:
    if not 0 <= value <= 255:
        raise ValueError("color values must be in range 0-255")
    return value


def checksum(frame: Iterable[int]) -> int:
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
    parts.append(checksum(parts))
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
    parts.append(checksum(parts))
    return bytes(parts)


def build_power_frame(*, on: bool) -> bytes:
    parts = [
        0x06,
        0x00,
        0x00,
        CMD_POWER,
        0x02 if on else 0x01,
    ]
    parts.append(checksum(parts))
    return bytes(parts)


def parse_get_reply(frame: bytes) -> TabletStatus:
    """Parse a reply to a GET frame.

    The protocol is lightly documented in the Philips SICP specification. For
    the displays we have tested the layout is::

        [0]: frame length (0x09)
        [1]: control byte (0x01)
        [2]: group byte (0x00)
        [3]: command echo (0xF4)
        [4]: LED on/off flag (0x01 on, 0x00 off)
        [5]: LED red value
        [6]: LED green value
        [7]: LED blue value
        [8]: checksum (XOR of previous bytes)

    Some firmware revisions also reflect the panel power state as part of the
    LED data. We assume the LED flag mirrors the accent state and treat the
    panel power as *on* when any of the colour bytes are non-zero or when the
    LED flag is set. This heuristic matches the behaviour documented in the
    latest Philips signage SICP specification.
    """

    if len(frame) < 9:
        raise ProtocolError(f"GET reply too short: {frame!r}")
    if frame[0] != len(frame):
        raise ProtocolError(
            f"GET reply length mismatch: header={frame[0]} actual={len(frame)}"
        )
    if frame[3] != CMD_GET:
        raise ProtocolError(f"Unexpected command echo in GET reply: 0x{frame[3]:02X}")
    expected_checksum = checksum(frame[:-1])
    if frame[-1] != expected_checksum:
        raise ProtocolError("Checksum mismatch in GET reply")
    led_on = bool(frame[4])
    red, green, blue = frame[5], frame[6], frame[7]
    power_on = led_on or any(v > 0 for v in (red, green, blue))
    led = LedState(on=led_on, red=red, green=green, blue=blue)
    power = PowerState(on=power_on)
    return TabletStatus(led=led, power=power)


def parse_hex_color(color: str) -> Tuple[int, int, int]:
    if not color:
        raise ValueError("color must be provided")
    normalized = color.strip()
    if normalized.startswith("#"):
        normalized = normalized[1:]
    if len(normalized) != 6 or any(
        ch not in "0123456789abcdefABCDEF" for ch in normalized
    ):
        raise ValueError("expected hex format RRGGBB")
    red = int(normalized[0:2], 16)
    green = int(normalized[2:4], 16)
    blue = int(normalized[4:6], 16)
    return red, green, blue


def format_frame(frame: bytes) -> str:
    return " ".join(f"{byte:02X}" for byte in frame)
