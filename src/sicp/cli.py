"""Command line interface for direct SICP interactions."""
from __future__ import annotations

import argparse
import logging

from .client import ClientConfig, SICPClient
from .protocol import parse_hex_color

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Philips SICP LED strip client")
    parser.add_argument("--host", default="192.168.2.98", help="Display hostname or IP address")
    parser.add_argument("--port", type=int, default=5000, help="SICP TCP port")
    parser.add_argument("--timeout", type=float, default=5.0, help="Socket timeout in seconds")
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Number of retry attempts after the initial send (default 2)",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=1.0,
        help="Delay in seconds between retries (default 1.0)",
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

    return parser


def _build_client(args: argparse.Namespace) -> SICPClient:
    config = ClientConfig(
        host=args.host,
        port=args.port,
        timeout=args.timeout,
        retries=args.retries,
        retry_delay=args.retry_delay,
    )
    return SICPClient(config)


def handle_set(args: argparse.Namespace) -> None:
    client = _build_client(args)
    red, green, blue = parse_hex_color(args.color)
    status = client.set_led(on=not args.off, red=red, green=green, blue=blue)
    LOGGER.info(
        "LED state: %s %s (%s)",
        "ON" if status.led.on else "OFF",
        status.led.as_hex(),
        (status.led.red, status.led.green, status.led.blue),
    )


def handle_get(args: argparse.Namespace) -> None:
    client = _build_client(args)
    status = client.get_status()
    LOGGER.info(
        "LED state: %s %s (%s)",
        "ON" if status.led.on else "OFF",
        status.led.as_hex(),
        (status.led.red, status.led.green, status.led.blue),
    )


def handle_power(args: argparse.Namespace) -> None:
    client = _build_client(args)
    status = client.set_power(on=args.state == "on")
    LOGGER.info("Power state: %s", "ON" if status.power.on else "OFF")


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


__all__ = ["main"]
