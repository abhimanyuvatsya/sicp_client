"""FastAPI web application for manual control and monitoring."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .logging_utils import RingBufferHandler
from .protocol import parse_hex_color
from .tablet import TabletController, TabletManager


def create_app(
    manager: TabletManager,
    log_handler: RingBufferHandler,
    *,
    templates_dir: str,
) -> FastAPI:
    app = FastAPI(title="Philips SICP Controller")
    templates = Jinja2Templates(directory=templates_dir)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> Any:
        controllers = list(manager.controllers.values())
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "tablets": controllers,
            },
        )

    @app.post("/tablets/{tablet_id}/led")
    async def set_led(tablet_id: str, request: Request) -> RedirectResponse:
        controller = _get_controller(manager, tablet_id)
        form = await request.form()
        color = str(form.get("color", "#FFFFFF"))
        on = form.get("state", "on") == "on"
        try:
            red, green, blue = parse_hex_color(color)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await controller.set_led(on=on, red=red, green=green, blue=blue)
        return RedirectResponse(url="/", status_code=303)

    @app.post("/tablets/{tablet_id}/power")
    async def set_power(tablet_id: str, request: Request) -> RedirectResponse:
        controller = _get_controller(manager, tablet_id)
        form = await request.form()
        state = str(form.get("state", "off"))
        await controller.set_power(on=state == "on")
        return RedirectResponse(url="/", status_code=303)

    @app.get("/api/tablets")
    async def api_tablets() -> JSONResponse:
        payload: Dict[str, Any] = {}
        for controller in manager:
            payload[controller.config.id] = {
                "config": {
                    "name": controller.config.name,
                    "host": controller.config.host,
                    "port": controller.config.port,
                },
                "state": controller.state.as_dict(),
            }
        return JSONResponse(payload)

    @app.get("/logs", response_class=HTMLResponse)
    async def logs(request: Request) -> Any:
        entries = log_handler.formatted_records()
        return templates.TemplateResponse(
            "logs.html",
            {
                "request": request,
                "entries": entries[-200:],
            },
        )

    return app


def _get_controller(manager: TabletManager, tablet_id: str) -> TabletController:
    try:
        return manager.get(tablet_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown tablet {tablet_id}") from exc
