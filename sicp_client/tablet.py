"""Tablet coordination logic."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .config import TabletConfig
from .protocol import (
    ProtocolError,
    build_get_frame,
    build_power_frame,
    build_power_query_frame,
    build_set_frame,
    parse_led_reply,
    parse_power_reply,
    parse_hex_color,
    send_with_retries,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class TabletState:
    name: str
    online: bool = False
    led_on: Optional[bool] = None
    led_hex: Optional[str] = None
    power_on: Optional[bool] = None
    last_queried: Optional[datetime] = None
    last_success: Optional[datetime] = None
    last_error: Optional[str] = None

    def snapshot(self) -> "TabletState":
        return TabletState(
            name=self.name,
            online=self.online,
            led_on=self.led_on,
            led_hex=self.led_hex,
            power_on=self.power_on,
            last_queried=self.last_queried,
            last_success=self.last_success,
            last_error=self.last_error,
        )


class TabletController:
    """Coordinates IO with a single physical tablet."""

    def __init__(self, config: TabletConfig) -> None:
        self.config = config
        self._lock = asyncio.Lock()
        self.state = TabletState(name=config.name)

    async def _send(self, frame: bytes, *, expect_reply: bool) -> bytes:
        return await asyncio.to_thread(
            send_with_retries,
            host=self.config.host,
            port=self.config.port,
            frame=frame,
            timeout=self.config.timeout,
            expect_reply=expect_reply,
            retries=self.config.retries,
            retry_delay=self.config.retry_delay,
        )

    async def refresh_state(self) -> TabletState:
        async with self._lock:
            now = datetime.now(timezone.utc)
            self.state.last_queried = now
            try:
                led_reply = await self._send(build_get_frame(), expect_reply=True)
                led = parse_led_reply(led_reply)
                self.state.led_on = led.is_on
                self.state.led_hex = led.hex_color
                self.state.online = True
                try:
                    power_reply = await self._send(build_power_query_frame(), expect_reply=True)
                    power = parse_power_reply(power_reply)
                    self.state.power_on = power.is_on
                except (ConnectionError, ProtocolError) as power_exc:
                    _LOGGER.debug(
                        "Unable to query power state for %s: %s", self.config.name, power_exc
                    )
                self.state.last_success = now
                self.state.last_error = None
            except (ConnectionError, ProtocolError) as exc:
                self.state.online = False
                self.state.last_error = str(exc)
                _LOGGER.warning("Failed to refresh state for %s: %s", self.config.name, exc)
            return self.state.snapshot()

    async def set_led(self, *, color_hex: Optional[str], turn_on: bool) -> TabletState:
        async with self._lock:
            target_hex = color_hex
            if turn_on and not target_hex and self.state.led_hex:
                target_hex = self.state.led_hex
            if target_hex:
                red, green, blue = parse_hex_color(target_hex)
            else:
                red, green, blue = 0, 0, 0
            frame = build_set_frame(on=turn_on, red=red, green=green, blue=blue)
            await self._send(frame, expect_reply=True)
            confirm = await self._send(build_get_frame(), expect_reply=True)
            led = parse_led_reply(confirm)
            self.state.led_on = led.is_on
            self.state.led_hex = led.hex_color
            self.state.online = True
            now = datetime.now(timezone.utc)
            self.state.last_success = now
            self.state.last_queried = now
            self.state.last_error = None
            return self.state.snapshot()

    async def set_power(self, *, turn_on: bool) -> TabletState:
        async with self._lock:
            frame = build_power_frame(on=turn_on)
            reply = await self._send(frame, expect_reply=True)
            power = parse_power_reply(reply)
            if power.is_on is not None and power.is_on != turn_on:
                _LOGGER.warning(
                    "Tablet %s reported power %s after set %s", self.config.name, power.is_on, turn_on
                )
            # Query again to update LED/power hints
            try:
                status = await self._send(build_power_query_frame(), expect_reply=True)
                power = parse_power_reply(status)
            except (ConnectionError, ProtocolError) as exc:
                _LOGGER.debug("Power status query after set failed for %s: %s", self.config.name, exc)
            self.state.power_on = power.is_on if power.is_on is not None else turn_on
            self.state.online = True
            now = datetime.now(timezone.utc)
            self.state.last_success = now
            self.state.last_queried = now
            self.state.last_error = None
            return self.state.snapshot()

    def get_state(self) -> TabletState:
        return self.state.snapshot()
