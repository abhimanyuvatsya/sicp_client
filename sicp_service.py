"""Entry point for the SICP control daemon."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path

import uvicorn

from sicp_client.config import ConfigurationError, load_service_config
from sicp_client.service import TabletService
from sicp_client.web import create_app


async def _run(args: argparse.Namespace) -> None:
    config = load_service_config(Path(args.config))
    service = TabletService(config)
    await service.start()

    app = create_app(service)
    server_config = uvicorn.Config(
        app,
        host=config.web.bind_host,
        port=config.web.bind_port,
        log_level=args.log_level.lower(),
        reload=False,
    )
    server = uvicorn.Server(server_config)
    try:
        await server.serve()
    finally:
        await service.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Philips SICP control service")
    parser.add_argument(
        "--config",
        default=os.environ.get("SICP_CONFIG", "/etc/sicp/config.yml"),
        help="Path to the YAML configuration file",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Root logging level",
    )
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper()), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    try:
        asyncio.run(_run(args))
    except ConfigurationError as exc:
        raise SystemExit(f"Configuration error: {exc}")


if __name__ == "__main__":
    main()
