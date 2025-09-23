"""High-level tablet management and orchestration."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Dict, List, Optional

from . import config as config_module
from . import sicp
from . import presets

LOGGER = logging.getLogger(__name__)

StateListener = Callable[[str, "TabletState"], Awaitable[None] | None]


@dataclass
class TabletState:
    """In-memory state for a managed tablet."""

    available: bool = False
    led_on: bool = False
    red: int = 0
    green: int = 0
    blue: int = 0
    preset: Optional[str] = None
    power_on: Optional[bool] = None
    last_error: Optional[str] = None
    last_updated: Optional[datetime] = None

    @property
    def hex_color(self) -> str:
        return f"#{self.red:02X}{self.green:02X}{self.blue:02X}"

    def as_dict(self) -> Dict[str, object]:
        return {
            "available": self.available,
            "led_on": self.led_on,
            "red": self.red,
            "green": self.green,
            "blue": self.blue,
            "hex_color": self.hex_color,
            "preset": self.preset,
            "power_on": self.power_on,
            "last_error": self.last_error,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
        }

    def copy(self) -> "TabletState":
        return TabletState(
            available=self.available,
            led_on=self.led_on,
            red=self.red,
            green=self.green,
            blue=self.blue,
            preset=self.preset,
            power_on=self.power_on,
            last_error=self.last_error,
            last_updated=self.last_updated,
        )


class TabletController:
    """Encapsulates the lifecycle of a single tablet."""

    def __init__(
        self,
        cfg: config_module.TabletConfig,
        polling: config_module.PollingConfig,
        listener: Callable[[str, TabletState], None],
    ) -> None:
        self.cfg = cfg
        self.polling = polling
        self._listener = listener
        self._client = sicp.SICPClient(cfg.host, cfg.port)
        self._state = TabletState()
        self._lock = asyncio.Lock()

    @property
    def state(self) -> TabletState:
        return self._state

    async def refresh_state(self) -> None:
        async with self._lock:
            await self._refresh_state_locked()

    async def set_light(self, *, on: bool, red: int, green: int, blue: int) -> TabletState:
        async with self._lock:
            LOGGER.info("Setting LED on %s to %s #%02X%02X%02X", self.cfg.identifier, on, red, green, blue)
            try:
                status = await asyncio.to_thread(
                    self._client.set_led,
                    on=on,
                    red=red,
                    green=green,
                    blue=blue,
                    timeout=self.polling.timeout_seconds,
                    retries=self.polling.retry_attempts,
                    retry_delay=self.polling.retry_delay_seconds,
                )
                confirmed = await asyncio.to_thread(
                    self._client.get_led_status,
                    timeout=self.polling.timeout_seconds,
                    retries=self.polling.retry_attempts,
                    retry_delay=self.polling.retry_delay_seconds,
                )
                if on:
                    if (
                        confirmed.on != on
                        or confirmed.red != status.red
                        or confirmed.green != status.green
                        or confirmed.blue != status.blue
                    ):
                        raise sicp.SICPError(
                            "LED verification failed: expected %s #%02X%02X%02X, got %s #%02X%02X%02X"
                            % (
                                "ON" if on else "OFF",
                                status.red,
                                status.green,
                                status.blue,
                                "ON" if confirmed.on else "OFF",
                                confirmed.red,
                                confirmed.green,
                                confirmed.blue,
                            )
                        )
                else:
                    if confirmed.on:
                        raise sicp.SICPError(
                            "LED verification failed: expected OFF, got ON #%02X%02X%02X"
                            % (confirmed.red, confirmed.green, confirmed.blue)
                        )
                self._update_state(
                    available=True,
                    led_on=confirmed.on,
                    red=confirmed.red,
                    green=confirmed.green,
                    blue=confirmed.blue,
                    last_error=None,
                )
            except Exception as exc:  # pylint: disable=broad-except
                self._handle_failure(exc)
            return self._state

    async def set_power(self, *, on: bool) -> TabletState:
        async with self._lock:
            LOGGER.info("Setting power on %s to %s", self.cfg.identifier, on)
            try:
                reply = await asyncio.to_thread(
                    self._client.set_power,
                    on=on,
                    timeout=self.polling.timeout_seconds,
                    retries=self.polling.retry_attempts,
                    retry_delay=self.polling.retry_delay_seconds,
                )
                desired_state = reply if reply is not None else on
                self._update_state(
                    available=True,
                    power_on=desired_state,
                    last_error=None,
                )
            except Exception as exc:  # pylint: disable=broad-except
                self._handle_failure(exc)
            return self._state

    async def _refresh_state_locked(self) -> None:
        LOGGER.debug("Polling state for %s", self.cfg.identifier)
        try:
            led_status = await asyncio.to_thread(
                self._client.get_led_status,
                timeout=self.polling.timeout_seconds,
                retries=self.polling.retry_attempts,
                retry_delay=self.polling.retry_delay_seconds,
            )
            self._update_state(
                available=True,
                led_on=led_status.on,
                red=led_status.red,
                green=led_status.green,
                blue=led_status.blue,
                last_error=None,
            )
        except Exception as exc:  # pylint: disable=broad-except
            self._handle_failure(exc)

    def _update_state(
        self,
        *,
        available: Optional[bool] = None,
        led_on: Optional[bool] = None,
        red: Optional[int] = None,
        green: Optional[int] = None,
        blue: Optional[int] = None,
        power_on: Optional[bool] = None,
        last_error: Optional[str] = None,
    ) -> None:
        if available is not None:
            self._state.available = available
        if led_on is not None:
            self._state.led_on = led_on
        if red is not None:
            self._state.red = red
        if green is not None:
            self._state.green = green
        if blue is not None:
            self._state.blue = blue
        if red is not None or green is not None or blue is not None or led_on is not None:
            matched = presets.match_rgb(self._state.red, self._state.green, self._state.blue)
            if not self._state.led_on:
                self._state.preset = "off"
            else:
                self._state.preset = matched
        if power_on is not None:
            self._state.power_on = power_on
        if last_error is not None:
            self._state.last_error = last_error
        self._state.last_updated = datetime.now(timezone.utc)
        try:
            self._listener(self.cfg.identifier, self._state)
        except Exception:  # pylint: disable=broad-except
            LOGGER.exception("State listener failed for %s", self.cfg.identifier)

    def _handle_failure(self, exc: Exception) -> None:
        LOGGER.warning("Communication failure with %s: %s", self.cfg.identifier, exc)
        self._update_state(
            available=False,
            last_error=str(exc),
        )


class TabletManager:
    """Coordinates tablet controllers and polling tasks."""

    def __init__(self, cfg: config_module.ServiceConfig) -> None:
        self.cfg = cfg
        self._controllers: Dict[str, TabletController] = {}
        self._listeners: List[StateListener] = []
        self._polling_tasks: List[asyncio.Task[None]] = []
        self._stopping = asyncio.Event()
        for tablet_cfg in cfg.tablets:
            controller = TabletController(
                tablet_cfg,
                cfg.polling,
                listener=self._notify_listeners,
            )
            self._controllers[tablet_cfg.identifier] = controller

    def _notify_listeners(self, tablet_id: str, state: TabletState) -> None:
        snapshot = state.copy()
        for listener in list(self._listeners):
            try:
                result = listener(tablet_id, snapshot)
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)  # fire and forget
            except Exception:  # pylint: disable=broad-except
                LOGGER.exception("Listener raised while processing %s", tablet_id)

    def add_listener(self, listener: StateListener) -> None:
        self._listeners.append(listener)

    def get_state(self, tablet_id: str) -> TabletState:
        return self._controllers[tablet_id].state

    def all_states(self) -> Dict[str, TabletState]:
        return {tablet_id: controller.state for tablet_id, controller in self._controllers.items()}

    async def start(self) -> None:
        LOGGER.info("Starting tablet manager with %s tablets", len(self._controllers))
        for controller in self._controllers.values():
            task = asyncio.create_task(self._poll_tablet(controller))
            self._polling_tasks.append(task)

    async def stop(self) -> None:
        LOGGER.info("Stopping tablet manager")
        self._stopping.set()
        for task in self._polling_tasks:
            task.cancel()
        await asyncio.gather(*self._polling_tasks, return_exceptions=True)

    async def _poll_tablet(self, controller: TabletController) -> None:
        interval = max(1.0, self.cfg.polling.interval_seconds)
        while not self._stopping.is_set():
            try:
                await controller.refresh_state()
            except Exception:  # pylint: disable=broad-except
                LOGGER.exception("Unexpected error while polling %s", controller.cfg.identifier)
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=interval)
            except asyncio.TimeoutError:
                continue

    async def set_light(
        self,
        tablet_id: str,
        *,
        on: bool,
        red: int,
        green: int,
        blue: int,
    ) -> TabletState:
        controller = self._controllers[tablet_id]
        return await controller.set_light(on=on, red=red, green=green, blue=blue)

    async def set_power(self, tablet_id: str, *, on: bool) -> TabletState:
        controller = self._controllers[tablet_id]
        return await controller.set_power(on=on)
