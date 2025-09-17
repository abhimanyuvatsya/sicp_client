"""FastAPI application exposing a web UI and REST API."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from .config import Config
from .logging_utils import InMemoryLogHandler
from .manager import TabletManager
from .mqtt import MqttBridge

LOGGER = logging.getLogger(__name__)

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def create_app(config: Config, manager: TabletManager, mqtt: MqttBridge, logs: InMemoryLogHandler) -> FastAPI:
    app = FastAPI(title="SICP Tablet Controller")

    manager.register_listener(lambda tablet, status: mqtt.publish_status(tablet, status))

    @app.on_event("startup")
    async def _startup() -> None:  # noqa: WPS430
        LOGGER.info("Starting application")
        await manager.start()
        mqtt.start()

    @app.on_event("shutdown")
    async def _shutdown() -> None:  # noqa: WPS430
        LOGGER.info("Stopping application")
        await mqtt.stop()
        await manager.stop()

    app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent.parent / "templates/static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):  # noqa: ANN001
        statuses = manager.get_all_statuses()
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "config": config,
                "statuses": statuses,
            },
        )

    @app.get("/logs", response_class=HTMLResponse)
    async def view_logs(request: Request):  # noqa: ANN001
        return templates.TemplateResponse(
            "logs.html",
            {
                "request": request,
                "records": logs.get_records(),
            },
        )

    @app.post("/tablets/{identifier}/led")
    async def form_set_led(identifier: str, state: str = Form(...), color: str = Form("#FFFFFF")):
        await manager.set_led(identifier, on=state.upper() == "ON", color=color)
        return RedirectResponse(url="/", status_code=303)

    @app.post("/tablets/{identifier}/power")
    async def form_set_power(identifier: str, state: str = Form(...)):
        await manager.set_power(identifier, on=state.upper() == "ON")
        return RedirectResponse(url="/", status_code=303)

    @app.get("/api/tablets")
    async def api_list_tablets():
        data = {tablet.identifier: manager.get_status(tablet.identifier).as_dict() for tablet in config.tablets}
        return JSONResponse(data)

    @app.get("/api/tablets/{identifier}")
    async def api_get_tablet(identifier: str):
        status = manager.get_status(identifier)
        return JSONResponse(status.as_dict())

    @app.post("/api/tablets/{identifier}/led")
    async def api_set_led(identifier: str, payload: Dict[str, Any]):  # noqa: ANN001
        state = str(payload.get("state", "")).upper()
        on = state != "OFF"
        color_value = payload.get("color") or payload.get("hex")
        color = None
        if isinstance(color_value, str):
            color = color_value
        elif isinstance(color_value, dict):
            try:
                color = "#{:02X}{:02X}{:02X}".format(
                    int(color_value.get("r", 0)),
                    int(color_value.get("g", 0)),
                    int(color_value.get("b", 0)),
                )
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Invalid RGB payload")
        await manager.set_led(identifier, on=on, color=color)
        status = manager.get_status(identifier)
        return JSONResponse(status.as_dict())

    @app.post("/api/tablets/{identifier}/power")
    async def api_set_power(identifier: str, payload: Dict[str, Any]):  # noqa: ANN001
        on = str(payload.get("state", "")).upper() != "OFF"
        await manager.set_power(identifier, on=on)
        status = manager.get_status(identifier)
        return JSONResponse(status.as_dict())

    @app.get("/api/logs")
    async def api_logs():
        return JSONResponse([record.as_dict() for record in logs.get_records()])

    return app
