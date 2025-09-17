"""Backward compatible CLI for issuing single SICP commands."""

from __future__ import annotations

import argparse
from sicp_client import protocol


def _parse_byte(token: str) -> int:
    raw = token.lower()
    if raw.startswith("0x"):
        value = int(raw[2:], 16)
    elif all(ch in "0123456789" for ch in raw):
        value = int(raw, 10)
    elif all(ch in "0123456789abcdef" for ch in raw):
        value = int(raw, 16)
    else:
        raise ValueError(f"Invalid byte token: {token}")
    if not 0 <= value <= 0xFF:
        raise ValueError(f"Byte out of range (0-255): {token}")
    return value


def _send(frame: bytes, *, args: argparse.Namespace, expect_reply: bool) -> bytes:
    return protocol.send_with_retries(
        host=args.host,
        port=args.port,
        frame=frame,
        timeout=args.timeout,
        expect_reply=expect_reply,
        retries=args.retries,
        retry_delay=args.retry_delay,
    )


def handle_set(args: argparse.Namespace) -> None:
    red, green, blue = protocol.parse_hex_color(args.color)
    frame = protocol.build_set_frame(
        on=not args.off,
        red=red,
        green=green,
        blue=blue,
    )
    reply = _send(frame, args=args, expect_reply=True)
    status = "OFF" if args.off else f"ON #{red:02X}{green:02X}{blue:02X}"
    print(f"Sent SET frame ({status}): {protocol.format_frame(frame)}")
    if reply:
        print(f"Ack: {protocol.format_frame(reply)}")


def handle_get(args: argparse.Namespace) -> None:
    frame = protocol.build_get_frame()
    reply = _send(frame, args=args, expect_reply=True)
    print(f"Sent GET frame: {protocol.format_frame(frame)}")
    if reply:
        print(f"Reply: {protocol.format_frame(reply)}")


def handle_power(args: argparse.Namespace) -> None:
    frame = protocol.build_power_frame(on=args.state == "on")
    reply = _send(frame, args=args, expect_reply=True)
    print(f"Sent POWER frame ({args.state.upper()}): {protocol.format_frame(frame)}")
    if reply:
        print(f"Ack: {protocol.format_frame(reply)}")


def handle_raw(args: argparse.Namespace) -> None:
    frame = bytes(_parse_byte(token) for token in args.bytes)
    reply = _send(frame, args=args, expect_reply=args.reply)
    print(f"Sent RAW frame: {protocol.format_frame(frame)}")
    if args.reply and reply:
        print(f"Reply: {protocol.format_frame(reply)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Philips SICP LED strip client")
    parser.add_argument("--host", default="192.168.2.98", help="Display hostname or IP address")
    parser.add_argument("--port", type=int, default=protocol.DEFAULT_PORT, help="SICP TCP port")
    parser.add_argument("--timeout", type=float, default=protocol.DEFAULT_TIMEOUT, help="Socket timeout in seconds")
    parser.add_argument(
        "--retries",
        type=int,
        default=protocol.DEFAULT_RETRIES,
        help="Number of retry attempts after the initial send",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=protocol.DEFAULT_RETRY_DELAY,
        help="Delay in seconds between retries",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    set_parser = subparsers.add_parser("set", help="Set LED on/off and color")
    set_parser.add_argument("--color", default="#FFFFFF", help="Hex color RRGGBB (e.g. #FF8800)")
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
