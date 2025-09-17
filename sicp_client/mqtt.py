"""MQTT integration and Home Assistant discovery."""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Optional

from asyncio_mqtt import Client, MqttError

from .config import MqttConfig, TabletConfig
from .tablet import TabletState
from .utils import slugify

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PublishMessage:
    topic: str
    payload: str
    retain: bool = False


LedCommandHandler = Callable[[str, bool, Optional[str]], Awaitable[TabletState]]
PowerCommandHandler = Callable[[str, bool], Awaitable[TabletState]]
RefreshHandler = Callable[[str], Awaitable[TabletState]]


class MqttBridge:
    """Bridges tablet state with MQTT and Home Assistant."""

    def __init__(
        self,
        config: MqttConfig,
        tablets: Dict[str, TabletConfig],
        *,
        on_led_command: LedCommandHandler,
        on_power_command: PowerCommandHandler,
        on_refresh: RefreshHandler,
    ) -> None:
        self._config = config
        self._tablets = tablets
        self._on_led_command = on_led_command
        self._on_power_command = on_power_command
        self._on_refresh = on_refresh
        self._publish_queue: "asyncio.Queue[PublishMessage]" = asyncio.Queue()
        self._connected = asyncio.Event()
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []
        self._client: Optional[Client] = None

    async def start(self) -> None:
        _LOGGER.info("Starting MQTT bridge to %s:%s", self._config.host, self._config.port)
        self._tasks = [
            asyncio.create_task(self._mqtt_loop(), name="mqtt-loop"),
            asyncio.create_task(self._publisher_loop(), name="mqtt-publisher"),
        ]

    async def stop(self) -> None:
        self._stop.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()

    async def publish_state(self, tablet_id: str, state: TabletState) -> None:
        slug = slugify(tablet_id)
        availability_topic = f"{self._config.base_topic}/{slug}/availability"
        availability = "online" if state.online else "offline"
        await self._publish_queue.put(PublishMessage(availability_topic, availability, retain=True))

        tablet_cfg = self._tablets.get(slug)

        if not tablet_cfg or tablet_cfg.ha_light:
            led_state_topic = f"{self._config.base_topic}/{slug}/led/state"
            led_payload = {
                "state": "ON" if state.led_on else "OFF",
                "color": None,
            }
            if state.led_hex and state.led_on:
                led_payload["color"] = {
                    "r": int(state.led_hex[1:3], 16),
                    "g": int(state.led_hex[3:5], 16),
                    "b": int(state.led_hex[5:7], 16),
                }
            await self._publish_queue.put(
                PublishMessage(led_state_topic, json.dumps(led_payload), retain=True)
            )

            attributes_topic = f"{self._config.base_topic}/{slug}/led/attributes"
            attributes_payload = {
                "led_hex": state.led_hex,
                "power_on": state.power_on,
                "last_success": state.last_success.isoformat() if state.last_success else None,
                "last_error": state.last_error,
            }
            await self._publish_queue.put(
                PublishMessage(attributes_topic, json.dumps(attributes_payload), retain=True)
            )

        if not tablet_cfg or tablet_cfg.ha_power_switch:
            power_topic = f"{self._config.base_topic}/{slug}/power/state"
            if state.power_on is None:
                power_state = "unknown"
            else:
                power_state = "ON" if state.power_on else "OFF"
            await self._publish_queue.put(PublishMessage(power_topic, power_state, retain=True))

    async def publish_discovery(self) -> None:
        for slug, tablet in self._tablets.items():
            availability_topic = f"{self._config.base_topic}/{slug}/availability"
            device_info = {
                "identifiers": [f"sicp:{slug}"],
                "name": tablet.name,
                "manufacturer": "Philips",
                "model": "Signage",
            }
            if tablet.ha_light:
                light_config_topic = (
                    f"{self._config.discovery_prefix}/light/{slug}_led/config"
                )
                light_config_payload = {
                    "name": f"{tablet.name} Accent LED",
                    "unique_id": f"sicp-{slug}-led",
                    "schema": "json",
                    "supported_color_modes": ["rgb"],
                    "command_topic": f"{self._config.base_topic}/{slug}/led/set",
                    "state_topic": f"{self._config.base_topic}/{slug}/led/state",
                    "json_attributes_topic": f"{self._config.base_topic}/{slug}/led/attributes",
                    "availability_topic": availability_topic,
                    "device": device_info,
                }
                await self._publish_queue.put(
                    PublishMessage(light_config_topic, json.dumps(light_config_payload), retain=True)
                )

            if tablet.ha_power_switch:
                switch_config_topic = (
                    f"{self._config.discovery_prefix}/switch/{slug}_power/config"
                )
                switch_payload = {
                    "name": f"{tablet.name} Power",
                    "unique_id": f"sicp-{slug}-power",
                    "command_topic": f"{self._config.base_topic}/{slug}/power/set",
                    "state_topic": f"{self._config.base_topic}/{slug}/power/state",
                    "availability_topic": availability_topic,
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "device": device_info,
                }
                await self._publish_queue.put(
                    PublishMessage(switch_config_topic, json.dumps(switch_payload), retain=True)
                )

    async def _publisher_loop(self) -> None:
        while not self._stop.is_set():
            message = await self._publish_queue.get()
            try:
                await self._connected.wait()
                if not self._client:
                    continue
                await self._client.publish(message.topic, message.payload, qos=1, retain=message.retain)
            except MqttError as exc:
                _LOGGER.warning("Publish to %s failed: %s", message.topic, exc)
                await asyncio.sleep(self._config.reconnect_interval)
                await self._publish_queue.put(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - safety net
                _LOGGER.exception("Unexpected error publishing MQTT message: %s", exc)

    async def _mqtt_loop(self) -> None:
        while not self._stop.is_set():
            tls_context = None
            if self._config.enable_tls:
                tls_context = ssl.create_default_context()
            try:
                async with Client(
                    self._config.host,
                    port=self._config.port,
                    username=self._config.username,
                    password=self._config.password,
                    client_id=self._config.client_id,
                    keepalive=self._config.keepalive,
                    tls_context=tls_context,
                ) as client:
                    self._client = client
                    self._connected.set()
                    await self.publish_discovery()
                    await self._subscribe(client)
                    async with client.unfiltered_messages() as messages:
                        async for message in messages:
                            await self._handle_message(message.topic, message.payload.decode())
            except MqttError as exc:
                _LOGGER.warning("MQTT connection error: %s", exc)
                await asyncio.sleep(self._config.reconnect_interval)
            finally:
                self._connected.clear()
                self._client = None

    async def _subscribe(self, client: Client) -> None:
        topics = [
            (f"{self._config.base_topic}/+/led/set", 0),
            (f"{self._config.base_topic}/+/power/set", 0),
            (f"{self._config.base_topic}/+/refresh", 0),
        ]
        for topic, qos in topics:
            await client.subscribe((topic, qos))

    async def _handle_message(self, topic: str, payload: str) -> None:
        base = f"{self._config.base_topic}/"
        if not topic.startswith(base):
            return
        suffix = topic[len(base) :]
        parts = suffix.split("/")
        if len(parts) < 2:
            return
        slug = parts[0]
        action = "/".join(parts[1:])
        if slug not in self._tablets:
            _LOGGER.debug("Received MQTT command for unknown tablet %s", slug)
            return
        try:
            if action == "led/set":
                await self._handle_led(slug, payload)
            elif action == "power/set":
                await self._handle_power(slug, payload)
            elif action == "refresh":
                await self._handle_refresh(slug)
        except Exception as exc:
            _LOGGER.exception("Error handling MQTT message on %s: %s", topic, exc)

    async def _handle_led(self, slug: str, payload: str) -> None:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            _LOGGER.warning("Invalid LED payload for %s: %s", slug, exc)
            return
        state = data.get("state", "").upper()
        turn_on = state != "OFF"
        color_hex: Optional[str] = None
        color = data.get("color") or {}
        if isinstance(color, dict) and turn_on:
            try:
                red = int(color.get("r", color.get("red", 0)))
                green = int(color.get("g", color.get("green", 0)))
                blue = int(color.get("b", color.get("blue", 0)))
                color_hex = f"#{red:02X}{green:02X}{blue:02X}"
            except (TypeError, ValueError):
                _LOGGER.warning("Invalid color payload for %s: %s", slug, color)
                color_hex = None
        await self._on_led_command(slug, turn_on, color_hex)

    async def _handle_power(self, slug: str, payload: str) -> None:
        normalized = payload.strip().upper()
        if normalized not in {"ON", "OFF"}:
            _LOGGER.warning("Invalid power payload for %s: %s", slug, payload)
            return
        turn_on = normalized == "ON"
        await self._on_power_command(slug, turn_on)

    async def _handle_refresh(self, slug: str) -> None:
        await self._on_refresh(slug)
