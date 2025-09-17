#!/usr/bin/env python3
"""Simple Philips SICP client to control LED accent strips."""

from __future__ import annotations

import argparse
import socket
import time
from typing import Iterable, List, Tuple

DEFAULT_HOST = "192.168.2.98"
DEFAULT_PORT = 5000
FRAME_SIZE = 0x09
CONTROL_BYTE = 0x01
GROUP_BYTE = 0x00
CMD_SET = 0xF3
CMD_GET = 0xF4
DEFAULT_RETRIES = 2
DEFAULT_RETRY_DELAY = 1.0


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


def _parse_byte(token: str) -> int:
    raw = token.lower()
    if raw.startswith("0x"):
        base = 16
        value_str = raw[2:]
    elif all(ch in "0123456789" for ch in raw):
        base = 10
        value_str = raw
    elif all(ch in "0123456789abcdef" for ch in raw):
        base = 16
        value_str = raw
    else:
        raise ValueError(f"Invalid byte token: {token}")
    try:
        value = int(value_str, base)
    except ValueError as exc:
        raise ValueError(f"Invalid byte value: {token}") from exc
    if not 0 <= value <= 0xFF:
        raise ValueError(f"Byte out of range (0-255): {token}")
    return value


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
        0x18,
        0x02 if on else 0x01,
    ]
    parts.append(_checksum(parts))
    return bytes(parts)


def send_frame(host: str, port: int, frame: bytes, *, timeout: float, expect_reply: bool) -> bytes:
    print(f"[debug] Connecting to {host}:{port} (timeout {timeout}s)")
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            print(f"[debug] Connected. Sending {len(frame)} bytes: {format_frame(frame)}")
            sock.sendall(frame)
            if not expect_reply:
                print("[debug] No reply requested; returning after send.")
                return b""
            sock.settimeout(timeout)
            print("[debug] Waiting for reply...")
            first = sock.recv(1)
            if not first:
                print("[debug] Connection closed without data.")
                return b""
            expected = first[0]
            print(f"[debug] First byte indicates {expected} total bytes in reply.")
            received = bytearray(first)
            while len(received) < expected:
                try:
                    chunk = sock.recv(expected - len(received))
                except socket.timeout:
                    print("[debug] Timed out while waiting for additional reply bytes.")
                    break
                if not chunk:
                    print("[debug] Socket closed before full reply was received.")
                    break
                received.extend(chunk)
            print(f"[debug] Received {len(received)} bytes in reply: {format_frame(received)}")
            return bytes(received)
    except OSError as exc:
        print(f"[debug] Connection attempt failed: {exc}")
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
    for attempt in range(1, attempts + 1):
        print(f"[debug] Send attempt {attempt}/{attempts}")
        try:
            return send_frame(
                host,
                port,
                frame,
                timeout=timeout,
                expect_reply=expect_reply,
            )
        except ConnectionError as exc:
            print(f"[debug] Attempt {attempt} failed: {exc}")
            if attempt == attempts:
                raise
            if retry_delay > 0:
                print(f"[debug] Waiting {retry_delay}s before retrying")
                time.sleep(retry_delay)
    return b""


def format_frame(frame: bytes) -> str:
    return " ".join(f"{byte:02X}" for byte in frame)


def handle_set(args: argparse.Namespace) -> None:
    try:
        red, green, blue = parse_hex_color(args.color)
    except ValueError as exc:
        print(f"Invalid color: {exc}")
        return
    normalized = args.color.strip()
    if not normalized.startswith("#"):
        normalized = f"#{normalized}"
    normalized = normalized.upper()
    frame = build_set_frame(
        on=not args.off,
        red=red,
        green=green,
        blue=blue,
    )
    try:
        reply = send_with_retries(
            host=args.host,
            port=args.port,
            frame=frame,
            timeout=args.timeout,
            expect_reply=True,
            retries=args.retries,
            retry_delay=args.retry_delay,
        )
    except ConnectionError as exc:
        print(exc)
        return
    state = "OFF" if args.off else f"ON {normalized} ({red}, {green}, {blue})"
    print(f"Sent SET frame ({state}): {format_frame(frame)}")
    if reply:
        if len(reply) >= 1 and reply[0] == len(reply):
            print(f"Ack: {format_frame(reply)}")
        else:
            print(f"Partial reply ({len(reply)} bytes): {format_frame(reply)}")
    else:
        print("No acknowledgement received (timed out).")


def handle_get(args: argparse.Namespace) -> None:
    frame = build_get_frame()
    try:
        reply = send_with_retries(
            host=args.host,
            port=args.port,
            frame=frame,
            timeout=args.timeout,
            expect_reply=True,
            retries=args.retries,
            retry_delay=args.retry_delay,
        )
    except ConnectionError as exc:
        print(exc)
        return
    print(f"Sent GET frame: {format_frame(frame)}")
    if len(reply) >= 1 and reply[0] == len(reply):
        print(f"Received reply: {format_frame(reply)}")
    elif reply:
        print(f"Partial reply ({len(reply)} bytes): {format_frame(reply)}")
    else:
        print("No reply received (timed out).")


def handle_power(args: argparse.Namespace) -> None:
    frame = build_power_frame(on=args.state == "on")
    try:
        reply = send_with_retries(
            host=args.host,
            port=args.port,
            frame=frame,
            timeout=args.timeout,
            expect_reply=True,
            retries=args.retries,
            retry_delay=args.retry_delay,
        )
    except ConnectionError as exc:
        print(exc)
        return
    print(f"Sent POWER frame ({args.state.upper()}): {format_frame(frame)}")
    if reply:
        print(f"Ack: {format_frame(reply)}")


def handle_raw(args: argparse.Namespace) -> None:
    try:
        frame = bytes(_parse_byte(token) for token in args.bytes)
    except ValueError as exc:
        print(exc)
        return
    try:
        reply = send_with_retries(
            host=args.host,
            port=args.port,
            frame=frame,
            timeout=args.timeout,
            expect_reply=args.reply,
            retries=args.retries,
            retry_delay=args.retry_delay,
        )
    except ConnectionError as exc:
        print(exc)
        return
    print(f"Sent RAW frame: {format_frame(frame)}")
    if args.reply:
        if reply:
            if len(reply) >= 1 and reply[0] == len(reply):
                print(f"Reply: {format_frame(reply)}")
            else:
                print(f"Partial reply ({len(reply)} bytes): {format_frame(reply)}")
        else:
            print("No reply received (timed out).")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Philips SICP LED strip client")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Display hostname or IP address")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="SICP TCP port")
    parser.add_argument("--timeout", type=float, default=5.0, help="Socket timeout in seconds")
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help="Number of retry attempts after the initial send (default 2)",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=DEFAULT_RETRY_DELAY,
        help="Delay in seconds between retries (default 1.0)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    set_parser = subparsers.add_parser("set", help="Set LED on/off and color")
    set_parser.add_argument("--color", default="#FFFFFF", help="Hex color RRGGBB (e.g. #FF8800")
    set_parser.add_argument("--off", action="store_true", help="Turn LEDs off instead of on")
    set_parser.set_defaults(func=handle_set)

    get_parser = subparsers.add_parser("get", help="Query current LED state")
    get_parser.set_defaults(func=handle_get)

    power_parser = subparsers.add_parser("power", help="Power on or off the display")
    power_parser.add_argument("state", choices=["on", "off"], help="Target power state")
    power_parser.set_defaults(func=handle_power)

    raw_parser = subparsers.add_parser("raw", help="Send raw frame bytes (hex or decimal)")
    raw_parser.add_argument("bytes", nargs="+", help="Frame bytes, e.g. 09 01 00 F3 01 00 00 00 F7")
    raw_parser.add_argument("--reply", action="store_true", help="Wait for a reply frame")
    raw_parser.set_defaults(func=handle_raw)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
