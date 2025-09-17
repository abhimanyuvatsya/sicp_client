"""Main entry point for the SICP controller service."""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from signal import SIGINT, SIGTERM
from typing import Iterable

import uvicorn

from .config import ConfigError, ServiceConfig, load_config
from .logging_utils import RingBufferHandler
from .mqtt_bridge import MQTTBridge
from .tablet import TabletManager
from .web import create_app

LOGGER = logging.getLogger(__name__)


def configure_logging(buffer_size: int) -> RingBufferHandler:
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)
    ring = RingBufferHandler(buffer_size)
    ring.setFormatter(formatter)
    root.addHandler(ring)
    return ring


async def refresh_all(manager: TabletManager, bridge: MQTTBridge) -> None:
    for controller in manager:
        status = await controller.refresh()
        if status is not None:
            await bridge.publish_state(controller)


async def run_service(config: ServiceConfig) -> None:
    templates_dir = Path(__file__).resolve().parent / "templates"
    log_handler = configure_logging(config.log_buffer)
    manager = TabletManager(config)
    bridge = MQTTBridge(manager, config.mqtt)
    app = create_app(manager, log_handler, templates_dir=str(templates_dir))

    server_config = uvicorn.Config(
        app,
        host=config.web_host,
        port=config.web_port,
        log_config=None,
        loop="asyncio",
    )
    server = uvicorn.Server(server_config)

    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        LOGGER.info("Received shutdown signal")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (SIGINT, SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    await bridge.start()
    await refresh_all(manager, bridge)

    poll_task = asyncio.create_task(manager.poll_forever(), name="poller")
    mqtt_task = asyncio.create_task(bridge.run(), name="mqtt")
    server_task = asyncio.create_task(server.serve(), name="web")
    stop_waiter = asyncio.create_task(stop_event.wait(), name="stop-waiter")

    done, _ = await asyncio.wait(
        {stop_waiter, server_task}, return_when=asyncio.FIRST_COMPLETED
    )
    if server_task in done and not server.should_exit:
        LOGGER.error("Web server exited unexpectedly")
        stop_event.set()

    LOGGER.info("Stopping service tasks")
    server.should_exit = True

    stop_waiter.cancel()
    await asyncio.gather(stop_waiter, return_exceptions=True)
    for task in (poll_task, mqtt_task):
        task.cancel()
    await asyncio.gather(poll_task, mqtt_task, return_exceptions=True)
    await bridge.stop()
    await server_task
    LOGGER.info("Shutdown complete")


async def async_main(args: argparse.Namespace) -> None:
    config_path = Path(args.config).resolve()
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        LOGGER.error("Failed to load configuration: %s", exc)
        raise SystemExit(1) from exc

    await run_service(config)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Philips SICP controller service")
    parser.add_argument(
        "--config",
        default="/etc/sicp/config.yaml",
        help="Path to configuration file",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        LOGGER.info("Interrupted")


__all__ = ["main"]
