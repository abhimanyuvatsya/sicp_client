"""Embedded web interface for the SICP service."""

from __future__ import annotations

import html
import logging
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, validator

from .logging_utils import LogBufferHandler
from .manager import TabletManager, TabletState

LOGGER = logging.getLogger(__name__)


class ColorPayload(BaseModel):
    hex: Optional[str] = Field(None, description="Hex color string, e.g. #FF0000")
    r: Optional[int] = Field(None, ge=0, le=255)
    g: Optional[int] = Field(None, ge=0, le=255)
    b: Optional[int] = Field(None, ge=0, le=255)

    @validator("hex")
    def normalize_hex(cls, value: Optional[str]) -> Optional[str]:  # pylint: disable=no-self-argument
        if value is None:
            return None
        stripped = value.strip()
        if stripped.startswith("#"):
            stripped = stripped[1:]
        if len(stripped) != 6:
            raise ValueError("Hex color must be 6 characters")
        int(stripped, 16)  # validation
        return stripped.upper()

    def rgb(self) -> Dict[str, int]:
        if self.hex:
            return {
                "red": int(self.hex[0:2], 16),
                "green": int(self.hex[2:4], 16),
                "blue": int(self.hex[4:6], 16),
            }
        return {
            "red": self.r or 0,
            "green": self.g or 0,
            "blue": self.b or 0,
        }


class LightRequest(BaseModel):
    state: Optional[str] = Field(None, description="Desired state ON/OFF")
    on: Optional[bool] = Field(None, description="Boolean power flag")
    color: Optional[ColorPayload] = None


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
        if desired_on is None:
            desired_on = True
        if payload.color:
            rgb = payload.color.rgb()
        else:
            rgb = {
                "red": current_state.red,
                "green": current_state.green,
                "blue": current_state.blue,
            }
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
            rows.append(
                f"<tr><td>{html.escape(tablet_id)}</td>"
                f"<td>{html.escape(status)}</td>"
                f"<td>{html.escape(state.hex_color)}</td>"
                f"<td>{'ON' if state.power_on else 'OFF'}</td>"
                f"<td><input type='color' id='color-{html.escape(tablet_id)}' value='{state.hex_color}' /></td>"
                f"<td><button onclick=sendLight('{html.escape(tablet_id)}')>Set Light</button></td>"
                f"<td><button onclick=togglePower('{html.escape(tablet_id)}',true)>Power On</button>"
                f"<button onclick=togglePower('{html.escape(tablet_id)}',false)>Power Off</button></td></tr>"
            )
        table_html = "".join(rows) or "<tr><td colspan='7'>No tablets configured</td></tr>"
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
                        <th>Power</th>
                        <th>Color</th>
                        <th>Light Control</th>
                        <th>Power Control</th>
                    </tr>
                </thead>
                <tbody>
                    {table_html}
                </tbody>
            </table>
            <script>
            async function sendLight(id) {{
                const colorInput = document.getElementById(`color-${{id}}`);
                const color = colorInput ? colorInput.value : '#000000';
                await fetch(`/api/tablets/${{id}}/light`, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ state: 'ON', color: {{ hex: color }} }}),
                }});
                window.location.reload();
            }}
            async function togglePower(id, on) {{
                await fetch(`/api/tablets/${{id}}/power`, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ state: on ? 'ON' : 'OFF' }}),
                }});
                window.location.reload();
            }}
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
