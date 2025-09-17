"""Management layer that coordinates multiple tablets."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, Dict, List, Optional

from .client import ClientSettings, TabletClient
from .config import Config, TabletConfig
from .protocol import LedState, PowerState, TabletState

LOGGER = logging.getLogger(__name__)

StateListener = Callable[[TabletConfig, "TabletStatus"], Awaitable[None] | None]


@dataclass
class TabletStatus:
    identifier: str
    led: Optional[LedState] = None
    power: Optional[PowerState] = None
    last_error: Optional[str] = None
    available: bool = False
    last_update: Optional[datetime] = None

    def as_dict(self) -> Dict:
        return {
            "id": self.identifier,
            "available": self.available,
            "led": {
                "on": self.led.on if self.led else None,
                "hex": self.led.hex_color if self.led else None,
                "red": self.led.red if self.led else None,
                "green": self.led.green if self.led else None,
                "blue": self.led.blue if self.led else None,
            },
            "power": {
                "on": self.power.on if self.power else None,
            },
            "last_error": self.last_error,
            "last_update": self.last_update.isoformat() if self.last_update else None,
        }


@dataclass
class TabletContext:
    config: TabletConfig
    client: TabletClient
    status: TabletStatus = field(init=False)
    poll_task: Optional[asyncio.Task] = None

    def __post_init__(self) -> None:
        self.status = TabletStatus(identifier=self.config.identifier)


class TabletManager:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._contexts: Dict[str, TabletContext] = {}
        self._listeners: List[StateListener] = []
        self._stop_event = asyncio.Event()
        for tablet in config.tablets:
            settings = ClientSettings(
                host=tablet.host,
                port=tablet.port,
                timeout=tablet.timeout,
                retries=tablet.retries,
                retry_delay=tablet.retry_delay,
            )
            context = TabletContext(config=tablet, client=TabletClient(settings))
            self._contexts[tablet.identifier] = context

    def get_tablets(self) -> List[TabletConfig]:
        return list(self._config.tablets)

    def get_status(self, identifier: str) -> TabletStatus:
        return self._require_context(identifier).status

    def get_all_statuses(self) -> Dict[str, TabletStatus]:
        return {identifier: ctx.status for identifier, ctx in self._contexts.items()}

    def register_listener(self, listener: StateListener) -> None:
        self._listeners.append(listener)

    async def start(self) -> None:
        LOGGER.info("Starting tablet manager")
        self._stop_event.clear()
        for context in self._contexts.values():
            if context.poll_task is None or context.poll_task.done():
                context.poll_task = asyncio.create_task(self._poll_loop(context))
        if self._config.poll_on_startup:
            await asyncio.gather(*(self.poll_once(ctx.config.identifier) for ctx in self._contexts.values()))

    async def stop(self) -> None:
        LOGGER.info("Stopping tablet manager")
        self._stop_event.set()
        for context in self._contexts.values():
            if context.poll_task:
                context.poll_task.cancel()
        await asyncio.gather(
            *(ctx.poll_task for ctx in self._contexts.values() if ctx.poll_task),
            return_exceptions=True,
        )

    async def poll_once(self, identifier: str) -> TabletStatus:
        context = self._require_context(identifier)
        return await self._poll_tablet(context)

    async def set_led(self, identifier: str, *, on: bool, color: Optional[str]) -> TabletStatus:
        context = self._require_context(identifier)
        if on and not color and context.status.led:
            color = context.status.led.hex_color
        try:
            led_state = await context.client.set_led_state(on=on, color=color)
            power_state = context.status.power
            if power_state is None:
                try:
                    power_state = await context.client.get_power_state()
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning("Failed to query power state after LED update: %s", exc)
            await self._update_status(context, led=led_state, power=power_state, error=None)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("LED command failed for %s", identifier)
            await self._update_status(context, error=str(exc))
            raise
        return context.status

    async def set_power(self, identifier: str, *, on: bool) -> TabletStatus:
        context = self._require_context(identifier)
        try:
            power_state = await context.client.set_power_state(on=on)
            led_state = context.status.led
            if led_state is None:
                try:
                    led_state = await context.client.get_led_state()
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning("Failed to query LED state after power update: %s", exc)
            await self._update_status(context, led=led_state, power=power_state, error=None)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Power command failed for %s", identifier)
            await self._update_status(context, error=str(exc))
            raise
        return context.status

    async def _poll_loop(self, context: TabletContext) -> None:
        LOGGER.info("Starting poll loop for %s", context.config.identifier)
        try:
            while not self._stop_event.is_set():
                await self._poll_tablet(context)
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=context.config.poll_interval
                    )
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            LOGGER.info("Poll loop cancelled for %s", context.config.identifier)
        except Exception:  # noqa: BLE001
            LOGGER.exception("Unexpected error in poll loop for %s", context.config.identifier)
            await asyncio.sleep(context.config.poll_interval)
            if not self._stop_event.is_set():
                asyncio.create_task(self._poll_loop(context))

    async def _poll_tablet(self, context: TabletContext) -> TabletStatus:
        identifier = context.config.identifier
        LOGGER.debug("Polling tablet %s", identifier)
        try:
            state: TabletState = await context.client.get_tablet_state()
            await self._update_status(context, led=state.led, power=state.power, error=None)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Failed to poll tablet %s: %s", identifier, exc)
            await self._update_status(context, error=str(exc))
        return context.status

    async def _update_status(
        self,
        context: TabletContext,
        *,
        led: Optional[LedState] = None,
        power: Optional[PowerState] = None,
        error: Optional[str],
    ) -> None:
        status = context.status
        if led is not None:
            status.led = led
        if power is not None:
            status.power = power
        status.last_update = datetime.now(timezone.utc)
        status.available = error is None
        status.last_error = error
        await self._notify_listeners(context.config, status)

    async def _notify_listeners(self, config: TabletConfig, status: TabletStatus) -> None:
        for listener in self._listeners:
            try:
                result = listener(config, status)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # noqa: BLE001
                LOGGER.exception("State listener failed for %s", config.identifier)

    def _require_context(self, identifier: str) -> TabletContext:
        if identifier not in self._contexts:
            raise KeyError(f"Unknown tablet identifier: {identifier}")
        return self._contexts[identifier]
