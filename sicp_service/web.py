"""Embedded web interface for the SICP service."""

from __future__ import annotations

import html
import logging
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .logging_utils import LogBufferHandler
from .manager import TabletManager, TabletState
from . import presets

LOGGER = logging.getLogger(__name__)


class LightRequest(BaseModel):
    state: Optional[str] = Field(None, description="Desired state ON/OFF")
    on: Optional[bool] = Field(None, description="Boolean power flag")
    preset: Optional[str] = Field(None, description="Preset identifier")


class PowerRequest(BaseModel):
    state: Optional[str] = Field(None, description="ON/OFF value")
    on: Optional[bool] = Field(None)


def create_app(tablets: TabletManager, log_handler: LogBufferHandler) -> FastAPI:
    app = FastAPI(title="SICP Tablet Controller")

    def _resolve_tablet(tablet_id: str) -> TabletState:
        try:
            return tablets.get_state(tablet_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unknown tablet") from exc

    @app.get("/api/tablets")
    async def list_tablets() -> Dict[str, Dict[str, object]]:
        return {tablet_id: state.as_dict() for tablet_id, state in tablets.all_states().items()}

    @app.get("/api/tablets/{tablet_id}")
    async def get_tablet(tablet_id: str) -> Dict[str, object]:
        state = _resolve_tablet(tablet_id)
        return state.as_dict()

    @app.post("/api/tablets/{tablet_id}/light")
    async def set_light(tablet_id: str, payload: LightRequest) -> Dict[str, object]:
        current_state = _resolve_tablet(tablet_id)
        desired_on = payload.on
        if desired_on is None and payload.state:
            desired_on = payload.state.upper() != "OFF"
        if payload.preset == "off":
            desired_on = False
        if desired_on is None:
            desired_on = True
        if desired_on:
            preset_id = payload.preset or current_state.preset
            if not preset_id:
                raise HTTPException(status_code=400, detail="Preset must be provided when turning LEDs on")
            try:
                preset = presets.resolve(preset_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            rgb = {
                "red": preset.red,
                "green": preset.green,
                "blue": preset.blue,
            }
        else:
            rgb = {"red": 0, "green": 0, "blue": 0}
        state = await tablets.set_light(
            tablet_id,
            on=desired_on,
            red=rgb["red"],
            green=rgb["green"],
            blue=rgb["blue"],
        )
        return state.as_dict()

    @app.post("/api/tablets/{tablet_id}/power")
    async def set_power(tablet_id: str, payload: PowerRequest) -> Dict[str, object]:
        _resolve_tablet(tablet_id)
        desired_on = payload.on
        if desired_on is None and payload.state:
            desired_on = payload.state.upper() != "OFF"
        if desired_on is None:
            raise HTTPException(status_code=400, detail="Power state must be provided")
        state = await tablets.set_power(tablet_id, on=desired_on)
        return state.as_dict()

    @app.get("/")
    async def index() -> HTMLResponse:
        rows = []
        for tablet_id, state in tablets.all_states().items():
            status = "Online" if state.available else "Offline"
            current_preset = state.preset or ("off" if not state.led_on else None)
            preset_buttons = []
            for preset in presets.presets():
                classes = ["preset"]
                if preset.identifier == "off":
                    classes.append("off")
                if current_preset == preset.identifier:
                    classes.append("selected")
                class_attr = " ".join(classes)
                preset_buttons.append(
                    f"<button class='{class_attr}' data-preset='{preset.identifier}' style='background-color: {preset.hex_value};'>"
                    f"{html.escape(preset.label)}</button>"
                )
            preset_controls = "".join(preset_buttons)
            color_display = "Off" if (state.preset == "off" or not state.led_on) else state.hex_color
            rows.append(
                f"<tr><td>{html.escape(tablet_id)}</td>"
                f"<td>{html.escape(status)}</td>"
                f"<td>{html.escape(color_display)}</td>"
                f"<td><div class='preset-grid' data-tablet='{html.escape(tablet_id)}'>{preset_controls}</div></td>"
                f"<td><button class='wake-button' data-tablet='{html.escape(tablet_id)}'>Wake Device</button></td></tr>"
            )
        table_html = "".join(rows) or "<tr><td colspan='5'>No tablets configured</td></tr>"
        body = f"""
        <html>
        <head>
            <title>SICP Tablets</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 2rem; }}
                table {{ border-collapse: collapse; width: 100%; }}
                th, td {{ border: 1px solid #ccc; padding: 0.5rem; text-align: left; }}
                th {{ background-color: #f0f0f0; }}
                button {{ margin-right: 0.25rem; }}
                .preset-grid {{ display: flex; flex-wrap: wrap; gap: 0.25rem; }}
                .preset {{ border: none; color: #000; padding: 0.25rem 0.5rem; cursor: pointer; }}
                .preset.selected {{ outline: 2px solid #000; }}
                .preset.off {{ background-color: #f5f5f5; color: #000; }}
                .wake-button {{ border: 1px solid #007bff; background: #fff; color: #007bff; padding: 0.4rem 1rem; cursor: pointer; border-radius: 4px; }}
            </style>
        </head>
        <body>
            <h1>SICP Tablet Dashboard</h1>
            <p><a href='/logs'>View Logs</a></p>
            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Status</th>
                        <th>LED</th>
                        <th>Color</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {table_html}
                </tbody>
            </table>
            <script>
            document.querySelectorAll('.preset-grid').forEach(grid => {{
                grid.addEventListener('click', async event => {{
                    const target = event.target.closest('.preset');
                    if (!target) return;
                    event.preventDefault();
                    const tabletId = grid.dataset.tablet;
                    grid.querySelectorAll('.preset').forEach(btn => btn.classList.remove('selected'));
                    target.classList.add('selected');
                    const presetId = target.dataset.preset;
                    const payload = presetId === 'off'
                        ? {{state: 'OFF'}}
                        : {{state: 'ON', preset: presetId}};
                    await fetch(`/api/tablets/${{tabletId}}/light`, {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify(payload),
                    }});
                    window.location.reload();
                }});
            }});
            document.querySelectorAll('.wake-button').forEach(button => {{
                button.addEventListener('click', async event => {{
                    event.preventDefault();
                    const tabletId = button.dataset.tablet;
                    await fetch(`/api/tablets/${{tabletId}}/power`, {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{state: 'ON'}}),
                    }});
                    window.location.reload();
                }});
            }});
            </script>
        </body>
        </html>
        """
        return HTMLResponse(content=body)

    @app.get("/logs")
    async def get_logs() -> HTMLResponse:
        lines = "\n".join(html.escape(line) for line in log_handler.get_lines())
        content = f"""
        <html>
        <head><title>Service Logs</title></head>
        <body>
            <h1>Recent Logs</h1>
            <p><a href='/'>Back to dashboard</a></p>
            <pre>{lines}</pre>
        </body>
        </html>
        """
        return HTMLResponse(content=content)

    return app
