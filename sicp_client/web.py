"""FastAPI application for manual control and monitoring."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .service import TabletService
from .tablet import TabletState

_LOGGER = logging.getLogger(__name__)

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def serialize_state(state: TabletState) -> Dict[str, object]:
    return {
        "name": state.name,
        "online": state.online,
        "led_on": state.led_on,
        "led_hex": state.led_hex,
        "power_on": state.power_on,
        "last_queried": state.last_queried.isoformat() if state.last_queried else None,
        "last_success": state.last_success.isoformat() if state.last_success else None,
        "last_error": state.last_error,
    }


def create_app(service: TabletService) -> FastAPI:
    app = FastAPI(title="SICP Control Service")
    app.state.service = service

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        states = {slug: serialize_state(state) for slug, state in service.states().items()}
        configs = service.tablet_configs()
        return TEMPLATES.TemplateResponse(
            "index.html",
            {
                "request": request,
                "states": states,
                "configs": configs,
                "service": service,
            },
        )

    @app.post("/tablet/{slug}/led")
    async def set_led(slug: str, state: str = Form(...), color: str = Form("")) -> RedirectResponse:
        if slug not in service.tablet_configs():
            raise HTTPException(status_code=404, detail="Unknown tablet")
        turn_on = state.upper() != "OFF"
        color_hex = color or None
        await service.set_led(slug, turn_on, color_hex)
        return RedirectResponse(url="/", status_code=303)

    @app.post("/tablet/{slug}/power")
    async def set_power(slug: str, state: str = Form(...)) -> RedirectResponse:
        if slug not in service.tablet_configs():
            raise HTTPException(status_code=404, detail="Unknown tablet")
        turn_on = state.upper() == "ON"
        await service.set_power(slug, turn_on)
        return RedirectResponse(url="/", status_code=303)

    @app.post("/tablet/{slug}/refresh")
    async def refresh(slug: str) -> RedirectResponse:
        if slug not in service.tablet_configs():
            raise HTTPException(status_code=404, detail="Unknown tablet")
        await service.refresh(slug)
        return RedirectResponse(url="/", status_code=303)

    @app.get("/api/tablets")
    async def api_tablets() -> JSONResponse:
        payload = {slug: serialize_state(state) for slug, state in service.states().items()}
        return JSONResponse(payload)

    @app.get("/api/tablets/{slug}")
    async def api_tablet(slug: str) -> JSONResponse:
        if slug not in service.tablet_configs():
            raise HTTPException(status_code=404, detail="Unknown tablet")
        return JSONResponse(serialize_state(service.get_state(slug)))

    @app.get("/api/logs")
    async def api_logs() -> JSONResponse:
        return JSONResponse({"logs": service.logs()})

    return app
