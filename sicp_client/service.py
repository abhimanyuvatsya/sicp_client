"""High-level orchestration for tablets, MQTT and the web UI."""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional

from .config import ServiceConfig, TabletConfig
from .logbuffer import MemoryLogHandler
from .mqtt import MqttBridge
from .tablet import TabletController, TabletState
from .utils import slugify

_LOGGER = logging.getLogger(__name__)


class TabletService:
    def __init__(self, config: ServiceConfig) -> None:
        self._config = config
        self._controllers: Dict[str, TabletController] = {}
        self._tablet_configs: Dict[str, TabletConfig] = {}
        self._stop_event = asyncio.Event()
        self._poll_tasks: List[asyncio.Task[None]] = []
        self._mqtt: Optional[MqttBridge] = None
        self.log_handler = MemoryLogHandler(max_entries=config.web.log_history)
        self._register_log_handler()
        self._build_controllers()

    def _register_log_handler(self) -> None:
        root = logging.getLogger()
        root.addHandler(self.log_handler)

    def _build_controllers(self) -> None:
        seen_slugs: Dict[str, int] = {}
        for tablet in self._config.tablets:
            base_slug = slugify(tablet.name or tablet.host)
            counter = seen_slugs.get(base_slug, 0)
            if counter:
                slug = f"{base_slug}-{counter+1}"
            else:
                slug = base_slug
            seen_slugs[base_slug] = counter + 1
            self._controllers[slug] = TabletController(tablet)
            self._tablet_configs[slug] = tablet
        _LOGGER.info("Loaded %s tablet configurations", len(self._controllers))

    async def start(self) -> None:
        _LOGGER.info("Starting tablet service")
        for slug, controller in self._controllers.items():
            interval = self._tablet_configs[slug].poll_interval or self._config.default_poll_interval
            task = asyncio.create_task(self._poll_loop(slug, controller, interval), name=f"poll-{slug}")
            self._poll_tasks.append(task)

        if self._config.mqtt:
            self._mqtt = MqttBridge(
                self._config.mqtt,
                self._tablet_configs,
                on_led_command=self._handle_led_command,
                on_power_command=self._handle_power_command,
                on_refresh=self._handle_refresh_command,
            )
            await self._mqtt.start()

    async def stop(self) -> None:
        _LOGGER.info("Stopping tablet service")
        self._stop_event.set()
        for task in self._poll_tasks:
            task.cancel()
        for task in self._poll_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._poll_tasks.clear()
        if self._mqtt:
            await self._mqtt.stop()

    async def _poll_loop(self, slug: str, controller: TabletController, interval: float) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    state = await controller.refresh_state()
                    if self._mqtt:
                        await self._mqtt.publish_state(slug, state)
                except Exception as exc:  # pragma: no cover - defensive
                    _LOGGER.exception("Error refreshing %s: %s", slug, exc)
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            _LOGGER.debug("Poll loop for %s cancelled", slug)

    async def _handle_led_command(self, slug: str, turn_on: bool, color_hex: Optional[str]) -> TabletState:
        controller = self._controllers[slug]
        _LOGGER.info("Setting LED on %s to %s (%s)", slug, "ON" if turn_on else "OFF", color_hex or "no color")
        state = await controller.set_led(color_hex=color_hex, turn_on=turn_on)
        if self._mqtt:
            await self._mqtt.publish_state(slug, state)
        return state

    async def _handle_power_command(self, slug: str, turn_on: bool) -> TabletState:
        controller = self._controllers[slug]
        _LOGGER.info("Setting power on %s to %s", slug, "ON" if turn_on else "OFF")
        state = await controller.set_power(turn_on=turn_on)
        if self._mqtt:
            await self._mqtt.publish_state(slug, state)
        return state

    async def _handle_refresh_command(self, slug: str) -> TabletState:
        controller = self._controllers[slug]
        _LOGGER.debug("Manual refresh requested for %s", slug)
        state = await controller.refresh_state()
        if self._mqtt:
            await self._mqtt.publish_state(slug, state)
        return state

    def states(self) -> Dict[str, TabletState]:
        return {slug: controller.get_state() for slug, controller in self._controllers.items()}

    def tablet_configs(self) -> Dict[str, TabletConfig]:
        return dict(self._tablet_configs)

    def get_state(self, slug: str) -> TabletState:
        return self._controllers[slug].get_state()

    async def refresh(self, slug: str) -> TabletState:
        return await self._handle_refresh_command(slug)

    async def set_led(self, slug: str, turn_on: bool, color_hex: Optional[str]) -> TabletState:
        return await self._handle_led_command(slug, turn_on, color_hex)

    async def set_power(self, slug: str, turn_on: bool) -> TabletState:
        return await self._handle_power_command(slug, turn_on)

    def logs(self) -> List[str]:
        return [entry for _, entry in self.log_handler.entries()]
