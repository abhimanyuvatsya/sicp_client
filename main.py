"""Entry point for running the SICP controller service."""

from __future__ import annotations

import argparse
import logging
import pathlib

import uvicorn

from sicp_client import load_config
from sicp_client.config import DEFAULT_CONFIG_PATH
from sicp_client.logging_utils import InMemoryLogHandler
from sicp_client.manager import TabletManager
from sicp_client.mqtt import MqttBridge
from sicp_client.web import create_app


def configure_logging(log_handler: InMemoryLogHandler, *, level: str, path: str | None) -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)
    log_handler.setFormatter(formatter)
    root.addHandler(log_handler)
    if path:
        file_handler = logging.FileHandler(path)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)


def build_app(config_path: pathlib.Path):
    config = load_config(config_path)
    log_handler = InMemoryLogHandler()
    configure_logging(log_handler, level=config.logging.level, path=config.logging.path)
    manager = TabletManager(config)
    mqtt = MqttBridge(config.mqtt, manager)
    app = create_app(config, manager, mqtt, log_handler)
    return app, config


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SICP controller service")
    parser.add_argument(
        "--config",
        type=pathlib.Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to configuration file",
    )
    args = parser.parse_args()
    app, config = build_app(args.config)
    uvicorn.run(app, host=config.web.host, port=config.web.port)


if __name__ == "__main__":
    main()
