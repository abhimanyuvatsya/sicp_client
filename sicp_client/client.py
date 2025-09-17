"""High level client that wraps SICP protocol helpers with retries and logging."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from . import protocol

LOGGER = logging.getLogger(__name__)


@dataclass
class ClientSettings:
    host: str
    port: int
    timeout: float
    retries: int
    retry_delay: float


class TabletClient:
    """Async wrapper around the synchronous protocol helpers."""

    def __init__(self, settings: ClientSettings) -> None:
        self.settings = settings
        self._lock = asyncio.Lock()

    async def _run(self, func, *args, **kwargs):
        async with self._lock:
            return await asyncio.to_thread(func, *args, **kwargs)

    async def get_led_state(self) -> protocol.LedState:
        LOGGER.debug("Querying LED state for %s:%s", self.settings.host, self.settings.port)
        return await self._run(
            protocol.query_led_state,
            host=self.settings.host,
            port=self.settings.port,
            timeout=self.settings.timeout,
            retries=self.settings.retries,
            retry_delay=self.settings.retry_delay,
        )

    async def set_led_state(self, *, on: bool, color: Optional[str] = None) -> protocol.LedState:
        if color is None:
            color = "#000000"
        red, green, blue = protocol.parse_hex_color(color)
        LOGGER.info(
            "Setting LED state for %s:%s -> on=%s color=%s",
            self.settings.host,
            self.settings.port,
            on,
            color,
        )
        return await self._run(
            protocol.set_led_state,
            host=self.settings.host,
            port=self.settings.port,
            on=on,
            red=red,
            green=green,
            blue=blue,
            timeout=self.settings.timeout,
            retries=self.settings.retries,
            retry_delay=self.settings.retry_delay,
        )

    async def get_power_state(self) -> protocol.PowerState:
        LOGGER.debug("Querying power state for %s:%s", self.settings.host, self.settings.port)
        return await self._run(
            protocol.query_power_state,
            host=self.settings.host,
            port=self.settings.port,
            timeout=self.settings.timeout,
            retries=self.settings.retries,
            retry_delay=self.settings.retry_delay,
        )

    async def set_power_state(self, *, on: bool) -> protocol.PowerState:
        LOGGER.info(
            "Setting power state for %s:%s -> on=%s",
            self.settings.host,
            self.settings.port,
            on,
        )
        return await self._run(
            protocol.set_power_state,
            host=self.settings.host,
            port=self.settings.port,
            on=on,
            timeout=self.settings.timeout,
            retries=self.settings.retries,
            retry_delay=self.settings.retry_delay,
        )

    async def get_tablet_state(self) -> protocol.TabletState:
        led, power = await asyncio.gather(self.get_led_state(), self.get_power_state())
        return protocol.TabletState(power=power, led=led)
