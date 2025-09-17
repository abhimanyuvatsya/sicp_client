"""Tablet management primitives."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Dict, Optional

from .client import ClientConfig, SICPClient, TabletStatus
from .config import ServiceConfig, TabletConfig
from .protocol import LedState
from .transport import ConnectionError

LOGGER = logging.getLogger(__name__)

StateCallback = Callable[["TabletController", TabletStatus], Awaitable[None]]


@dataclass
class TabletState:
    last_status: Optional[TabletStatus] = None
    last_success: Optional[datetime] = None
    last_error: Optional[str] = None

    def as_dict(self) -> Dict[str, object]:
        status = self.last_status
        led: Optional[LedState] = status.led if status else None
        power = status.power if status else None
        return {
            "led_on": led.on if led else None,
            "led_hex": led.as_hex() if led else None,
            "led_red": led.red if led else None,
            "led_green": led.green if led else None,
            "led_blue": led.blue if led else None,
            "power_on": power.on if power else None,
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "last_error": self.last_error,
        }


class TabletController:
    def __init__(self, config: TabletConfig, service_config: ServiceConfig):
        self.config = config
        client_config = ClientConfig(
            host=config.host,
            port=config.port,
            timeout=service_config.socket_timeout,
            retries=service_config.socket_retries,
            retry_delay=service_config.socket_retry_delay,
        )
        self._client = SICPClient(client_config)
        self._state = TabletState()
        self._lock = asyncio.Lock()
        self._callbacks: list[StateCallback] = []

    def register_callback(self, callback: StateCallback) -> None:
        self._callbacks.append(callback)

    @property
    def state(self) -> TabletState:
        return self._state

    async def set_led(self, *, on: bool, red: int, green: int, blue: int) -> TabletStatus:
        async with self._lock:
            LOGGER.info(
                "Setting LED for %s (on=%s rgb=%s)",
                self.config.id,
                on,
                (red, green, blue),
            )
            status = await asyncio.to_thread(
                self._client.set_led, on=on, red=red, green=green, blue=blue
            )
            confirmed = (
                status.led.on == on
                and status.led.red == red
                and status.led.green == green
                and status.led.blue == blue
            )
            if not confirmed:
                LOGGER.warning(
                    "LED confirmation mismatch for %s (expected on=%s rgb=%s, got on=%s rgb=%s)",
                    self.config.id,
                    on,
                    (red, green, blue),
                    status.led.on,
                    (status.led.red, status.led.green, status.led.blue),
                )
            await self._update_status(status)
            return status

    async def set_power(self, *, on: bool) -> TabletStatus:
        async with self._lock:
            LOGGER.info("Setting power for %s (on=%s)", self.config.id, on)
            status = await asyncio.to_thread(self._client.set_power, on=on)
            if status.power.on != on:
                LOGGER.warning(
                    "Power confirmation mismatch for %s (expected %s, got %s)",
                    self.config.id,
                    on,
                    status.power.on,
                )
            await self._update_status(status)
            return status

    async def refresh(self) -> Optional[TabletStatus]:
        LOGGER.debug("Refreshing state for %s", self.config.id)
        try:
            status = await asyncio.to_thread(self._client.get_status)
        except ConnectionError as exc:
            LOGGER.warning("Failed to refresh %s: %s", self.config.id, exc)
            self._state.last_error = str(exc)
            if self._callbacks and self._state.last_status is not None:
                await asyncio.gather(
                    *(callback(self, self._state.last_status) for callback in self._callbacks)
                )
            return None
        await self._update_status(status)
        return status

    async def _update_status(self, status: TabletStatus) -> None:
        self._state.last_status = status
        self._state.last_success = datetime.now(timezone.utc)
        self._state.last_error = None
        if self._callbacks:
            await asyncio.gather(*(callback(self, status) for callback in self._callbacks))


class TabletManager:
    def __init__(self, service_config: ServiceConfig):
        self._service_config = service_config
        self.controllers: Dict[str, TabletController] = {
            cfg.id: TabletController(cfg, service_config) for cfg in service_config.tablets
        }

    def __iter__(self):
        return iter(self.controllers.values())

    def get(self, tablet_id: str) -> TabletController:
        return self.controllers[tablet_id]

    async def poll_forever(self) -> None:
        async def worker(controller: TabletController) -> None:
            interval = max(5.0, controller.config.poll_interval)
            while True:
                await controller.refresh()
                await asyncio.sleep(interval)

        await asyncio.gather(*(worker(controller) for controller in self.controllers.values()))
