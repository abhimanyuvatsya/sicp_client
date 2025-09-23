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
            status_badge = (
                f"<span class='status-badge {'status-online' if state.available else 'status-offline'}'>"
                f"{html.escape(status)}</span>"
            )
            current_preset = state.preset or ("off" if not state.led_on else None)
            preset_buttons = []
            for preset in presets.presets():
                classes = ["preset-swatch"]
                is_off = preset.identifier == "off"
                # Determine text tone (light/dark) for contrast
                tone_class = "tone-dark"
                if is_off:
                    tone_class = "tone-light"
                else:
                    hexv = preset.hex_value.lstrip("#")
                    try:
                        r = int(hexv[0:2], 16)
                        g = int(hexv[2:4], 16)
                        b = int(hexv[4:6], 16)
                        yiq = (r * 299 + g * 587 + b * 114) / 1000
                        tone_class = "tone-light" if yiq > 160 else "tone-dark"
                    except Exception:  # fallback
                        tone_class = "tone-dark"
                classes.append(tone_class)
                if is_off:
                    classes.append("off")
                if current_preset == preset.identifier:
                    classes.append("selected")
                class_attr = " ".join(classes)
                check_mark = "<span class='swatch-check'>✓</span>" if current_preset == preset.identifier else ""
                preset_buttons.append(
                    """
                    <button class='{class_attr}' data-preset='{preset_id}' style='--swatch-color: {hex_value};'>
                        {check}
                    </button>
                    """.format(
                        class_attr=class_attr,
                        preset_id=html.escape(preset.identifier),
                        hex_value=html.escape(preset.hex_value),
                        check=check_mark,
                    )
                )
            preset_controls = "".join(preset_buttons)
            hex_color = html.escape(state.hex_color)
            if current_preset == "off":
                color_display = (
                    "<div class='color-display'>"
                    "<span class='color-chip color-off'></span>"
                    "</div>"
                )
            else:
                color_display = (
                    "<div class='color-display'>"
                    f"<span class='color-chip' style='--chip-color: {hex_color};'></span>"
                    f"<span class='color-label'>{hex_color}</span>"
                    "</div>"
                )
            rows.append(
                """
                <tr>
                    <td><span class='tablet-id'>{tablet_id}</span></td>
                    <td>{status_badge}</td>
                    <td>{color_display}</td>
                    <td><div class='preset-grid' data-tablet='{tablet_id_attr}'>{preset_controls}</div></td>
                    <td><button class='wake-button' data-tablet='{tablet_id_attr}'>Wake Device</button></td>
                </tr>
                """.format(
                    tablet_id=html.escape(tablet_id),
                    status_badge=status_badge,
                    color_display=color_display,
                    tablet_id_attr=html.escape(tablet_id),
                    preset_controls=preset_controls,
                )
            )
        table_html = "".join(rows) or "<tr><td colspan='5'>No tablets configured</td></tr>"
        body = f"""
        <html>
        <head>
            <title>SICP Tablets</title>
            <style>
                body {{
                    margin: 0;
                    font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                    background: #f5f7fb;
                    color: #1f2933;
                }}
                .container {{
                    max-width: 960px;
                    margin: 0 auto;
                    padding: 2.5rem 1.5rem 3rem;
                }}
                .header {{
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    margin-bottom: 1.75rem;
                }}
                .header h1 {{
                    margin: 0;
                    font-size: 1.85rem;
                    font-weight: 600;
                    letter-spacing: -0.02em;
                }}
                .logs-link {{
                    color: #2563eb;
                    text-decoration: none;
                    font-weight: 500;
                    border-bottom: 1px solid transparent;
                    transition: border-color 0.15s ease;
                }}
                .logs-link:hover {{ border-color: rgba(37,99,235,0.35); }}
                .card {{
                    background: #fff;
                    border-radius: 14px;
                    box-shadow: 0 12px 28px rgba(15, 23, 42, 0.08);
                    padding: 1.75rem;
                }}
                table {{
                    width: 100%;
                    border-collapse: separate;
                    border-spacing: 0;
                }}
                /* Fix column widths so layout doesn't jump */
                thead th:nth-child(1), tbody td:nth-child(1) {{ width: auto; }}  /* ID */
                thead th:nth-child(2), tbody td:nth-child(2) {{ width: 120px; }} /* Status */
                thead th:nth-child(3), tbody td:nth-child(3) {{ width: 160px; }} /* LED */
                thead th:nth-child(4), tbody td:nth-child(4) {{ width: 340px; }} /* Color presets */
                thead th:nth-child(5), tbody td:nth-child(5) {{ width: 160px; text-align: right; }} /* Actions */
                thead th {{
                    font-size: 0.75rem;
                    letter-spacing: 0.08em;
                    text-transform: uppercase;
                    color: #64748b;
                    font-weight: 600;
                    padding: 0.75rem 0.75rem 0.55rem;
                }}
                tbody td {{
                    padding: 0.95rem 0.75rem;
                    border-top: 1px solid #e2e8f0;
                    vertical-align: middle;
                }}
                tbody tr:hover {{ background: #f9fbff; }}
                .tablet-id {{ font-weight: 600; color: #111827; }}
                .status-badge {{
                    display: inline-flex;
                    align-items: center;
                    padding: 0.28rem 0.65rem;
                    border-radius: 999px;
                    font-size: 0.75rem;
                    font-weight: 600;
                    letter-spacing: 0.05em;
                    text-transform: uppercase;
                }}
                .status-online {{ background: rgba(34,197,94,0.12); color: #15803d; }}
                .status-offline {{ background: rgba(248,113,113,0.18); color: #b91c1c; }}
                .color-display {{
                    display: inline-flex;
                    align-items: center;
                    gap: 0.65rem;
                }}
                .color-chip {{
                    width: 18px;
                    height: 18px;
                    border-radius: 6px;
                    box-shadow: inset 0 0 0 1px rgba(15,23,42,0.12);
                    background: var(--chip-color, #94a3b8);
                }}
                .color-chip.color-off {{
                    background: #000000;
                }}
                .color-label {{ font-weight: 500; font-size: 0.9rem; color: #1f2933; }}
                .preset-grid {{
                    display: flex;
                    flex-wrap: nowrap;
                    gap: 0.5rem;
                    overflow-x: auto;
                    -webkit-overflow-scrolling: touch;
                    padding-bottom: 0.25rem;
                }}
                .preset-swatch {{
                    border: none;
                    width: 38px;
                    height: 38px;
                    border-radius: 10px;
                    background: var(--swatch-color, #94a3b8);
                    box-shadow: inset 0 0 0 1px rgba(15,23,42,0.18);
                    cursor: pointer;
                    position: relative;
                    transition: transform 0.15s ease, box-shadow 0.15s ease;
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    color: inherit;
                    font-weight: 700;
                    font-size: 1rem;
                }}
                .preset-swatch.tone-dark {{ color: #ffffff; }}
                .preset-swatch.tone-light {{ color: #111827; }}
                .preset-swatch::before {{
                    content: '';
                    position: absolute;
                    inset: 0;
                    border-radius: inherit;
                    box-shadow: inset 0 0 0 1px rgba(255,255,255,0.18);
                }}
                .preset-swatch:hover {{
                    transform: translateY(-2px) scale(1.03);
                    box-shadow: 0 10px 20px rgba(15,23,42,0.18);
                }}
                .preset-swatch.selected {{
                    box-shadow: 0 12px 24px rgba(37,99,235,0.35), inset 0 0 0 2px rgba(255,255,255,0.65);
                }}
                .preset-swatch.off {{
                    background: #000000;
                    color: #ffffff;
                }}
                .preset-swatch.off::before {{ box-shadow: inset 0 0 0 1px rgba(255,255,255,0.35); }}
                .swatch-check {{
                    position: relative;
                    z-index: 1;
                    text-shadow:
                        0 0 4px rgba(0,0,0,0.45),
                        0 0 2px rgba(255,255,255,0.65);
                }}
                .wake-button {{
                    border: none;
                    border-radius: 999px;
                    background: linear-gradient(135deg, #2563eb, #3b82f6);
                    color: #fff;
                    padding: 0.5rem 1.35rem;
                    font-weight: 600;
                    cursor: pointer;
                    box-shadow: 0 10px 22px rgba(59, 130, 246, 0.25);
                    transition: transform 0.15s ease, box-shadow 0.15s ease;
                }}
                .wake-button:hover {{
                    transform: translateY(-1px);
                    box-shadow: 0 14px 28px rgba(59, 130, 246, 0.35);
                }}
            </style>
        </head>
        <body>
            <div class='container'>
            <div class='header'>
                <h1>SICP Tablet Dashboard</h1>
                <a class='logs-link' href='/logs'>View Logs</a>
            </div>
            <div class='card'>
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
            </div>
            </div>
            <script>
            document.querySelectorAll('.preset-grid').forEach(grid => {{
                grid.addEventListener('click', async event => {{
                    const target = event.target.closest('.preset-swatch');
                    if (!target || !grid.contains(target)) {{
                        return;
                    }}
                    event.preventDefault();
                    const tabletId = grid.dataset.tablet;
                    grid.querySelectorAll('.preset-swatch').forEach(btn => btn.classList.remove('selected'));
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
