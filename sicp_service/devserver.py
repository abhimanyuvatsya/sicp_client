"""Development server entrypoint with auto-reload support.

Run with:

  SICP_CONFIG=./config.local.yaml \
  uvicorn sicp_service.devserver:app --reload --host 127.0.0.1 --port 8080

This bootstraps the same manager/MQTT + web app as the main service,
but leaves process control to uvicorn so --reload works on code changes.
"""

from __future__ import annotations

import os
from pathlib import Path

from .config import load_config
from .logging_utils import LogBufferHandler, configure_logging
from .manager import TabletManager
from .mqtt import MQTTManager
from .web import create_app


def _config_path() -> Path:
    # Allow overriding via env; default to a local dev config in the repo.
    raw = os.environ.get("SICP_CONFIG", "./config.local.yaml")
    return Path(raw)


# Build the app and wire lifecycle so uvicorn --reload can host it.
cfg = load_config(_config_path())
log_buffer = LogBufferHandler()
configure_logging(log_buffer)

manager = TabletManager(cfg)
mqtt_manager = MQTTManager(cfg, manager)
app = create_app(manager, log_buffer)


@app.on_event("startup")
async def _on_startup() -> None:
    await manager.start()
    await mqtt_manager.start()


@app.on_event("shutdown")
async def _on_shutdown() -> None:
    await mqtt_manager.stop()
    await manager.stop()

