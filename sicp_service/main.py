"""Entry point for the SICP management service."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

import uvicorn

from . import config as config_module
from .logging_utils import LogBufferHandler, configure_logging
from .manager import TabletManager
from .mqtt import MQTTManager
from .web import create_app

LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Philips SICP tablet management service")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("/etc/sicp_service/config.yaml"),
        help="Path to service configuration file",
    )
    return parser.parse_args()


async def run_service(cfg: config_module.ServiceConfig) -> None:
    log_path = None
    if cfg.log_directory:
        path = Path(cfg.log_directory)
        path.mkdir(parents=True, exist_ok=True)
        log_path = str(path / "sicp_service.log")
    log_buffer = LogBufferHandler()
    configure_logging(log_buffer, log_file=log_path)

    manager = TabletManager(cfg)
    mqtt_manager = MQTTManager(cfg, manager)
    app = create_app(manager, log_buffer)

    server_config = uvicorn.Config(
        app,
        host=cfg.web.host,
        port=cfg.web.port,
        loop="asyncio",
        log_config=None,
    )
    server = uvicorn.Server(server_config)
    # uvicorn 0.27.x expects install_signal_handlers to remain callable, so
    # replace it with a no-op instead of assigning a boolean.
    server.install_signal_handlers = lambda: None

    await manager.start()
    await mqtt_manager.start()
    LOGGER.info("Web server listening on %s:%s", cfg.web.host, cfg.web.port)
    try:
        await server.serve()
    finally:
        await mqtt_manager.stop()
        await manager.stop()


def main() -> None:
    args = parse_args()
    cfg = config_module.load_config(args.config)
    asyncio.run(run_service(cfg))


if __name__ == "__main__":
    main()
