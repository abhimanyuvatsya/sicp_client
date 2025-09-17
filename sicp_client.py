#!/usr/bin/env python3
"""Simple Philips SICP client to control LED accent strips."""

from __future__ import annotations

import argparse
import logging
from typing import Iterable

from sicp_client import protocol

LOGGER = logging.getLogger(__name__)


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
    value = int(value_str, base)
    if not 0 <= value <= 0xFF:
        raise ValueError(f"Byte out of range (0-255): {token}")
    return value


def format_frame(frame: Iterable[int]) -> str:
    return " ".join(f"{byte:02X}" for byte in frame)


def handle_set(args: argparse.Namespace) -> None:
    try:
        red, green, blue = protocol.parse_hex_color(args.color)
    except ValueError as exc:
        print(f"Invalid color: {exc}")
        return
    frame = protocol.build_set_frame(
        on=not args.off,
        red=red,
        green=green,
        blue=blue,
    )
    reply = protocol.send_with_retries(
        host=args.host,
        port=args.port,
        frame=frame,
        timeout=args.timeout,
        expect_reply=False,
        retries=args.retries,
        retry_delay=args.retry_delay,
    )
    if reply:
        print(format_frame(reply))


def handle_get(args: argparse.Namespace) -> None:
    state = protocol.query_led_state(
        host=args.host,
        port=args.port,
        timeout=args.timeout,
        retries=args.retries,
        retry_delay=args.retry_delay,
    )
    print(f"LED on={state.on} color={state.hex_color}")


def handle_power(args: argparse.Namespace) -> None:
    power_state = protocol.set_power_state(
        host=args.host,
        port=args.port,
        on=args.action == "on",
        timeout=args.timeout,
        retries=args.retries,
        retry_delay=args.retry_delay,
    )
    print(f"Power state is now {'ON' if power_state.on else 'OFF'}")


def handle_power_get(args: argparse.Namespace) -> None:
    power_state = protocol.query_power_state(
        host=args.host,
        port=args.port,
        timeout=args.timeout,
        retries=args.retries,
        retry_delay=args.retry_delay,
    )
    print(f"Power state: {'ON' if power_state.on else 'OFF'}")


def handle_raw(args: argparse.Namespace) -> None:
    frame = bytes(_parse_byte(token) for token in args.bytes)
    reply = protocol.send_with_retries(
        host=args.host,
        port=args.port,
        frame=frame,
        timeout=args.timeout,
        expect_reply=args.reply,
        retries=args.retries,
        retry_delay=args.retry_delay,
    )
    if reply:
        print(format_frame(reply))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Control Philips signage LED strips")
    parser.set_defaults(func=None)
    parser.add_argument("--host", default=protocol.DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=protocol.DEFAULT_PORT)
    parser.add_argument("--timeout", type=float, default=protocol.DEFAULT_TIMEOUT)
    parser.add_argument("--retries", type=int, default=protocol.DEFAULT_RETRIES)
    parser.add_argument("--retry-delay", type=float, default=protocol.DEFAULT_RETRY_DELAY)

    subparsers = parser.add_subparsers(dest="command")

    set_parser = subparsers.add_parser("set", help="Set LED color")
    set_parser.add_argument("--color", default="#FFFFFF")
    set_parser.add_argument("--off", action="store_true", help="Turn LEDs off")
    set_parser.set_defaults(func=handle_set)

    get_parser = subparsers.add_parser("get", help="Get LED status")
    get_parser.set_defaults(func=handle_get)

    power_parser = subparsers.add_parser("power", help="Control panel power")
    power_sub = power_parser.add_subparsers(dest="action", required=True)
    power_on = power_sub.add_parser("on", help="Power on the panel")
    power_on.set_defaults(func=handle_power)
    power_off = power_sub.add_parser("off", help="Power off the panel")
    power_off.set_defaults(func=handle_power)
    power_status = power_sub.add_parser("status", help="Get power status")
    power_status.set_defaults(func=handle_power_get)

    raw_parser = subparsers.add_parser("raw", help="Send a raw frame")
    raw_parser.add_argument("bytes", nargs="+", help="Frame bytes in hex or decimal")
    raw_parser.add_argument("--reply", action="store_true", help="Expect a reply")
    raw_parser.set_defaults(func=handle_raw)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.func is None:
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
