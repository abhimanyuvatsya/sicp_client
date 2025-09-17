"""MQTT bridge between the SICP manager and Home Assistant."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Tuple

import paho.mqtt.client as mqtt

from .config import MQTTConfig
from .tablet import TabletController, TabletManager

LOGGER = logging.getLogger(__name__)


class MQTTBridge:
    def __init__(self, manager: TabletManager, config: MQTTConfig):
        self._manager = manager
        self._config = config
        self._client = mqtt.Client(client_id=config.client_id, clean_session=True)
        if config.username:
            self._client.username_pw_set(config.username, config.password)
        status_topic = f"{config.base_topic}/status"
        self._client.will_set(status_topic, payload="offline", retain=True)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._command_queue: asyncio.Queue[Tuple[str, bytes]] = asyncio.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None

        for controller in manager:
            controller.register_callback(self._handle_tablet_update)

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        await asyncio.to_thread(
            self._client.connect,
            self._config.host,
            self._config.port,
            self._config.keepalive,
        )
        self._client.loop_start()
        await self._publish_status("online")
        await self._publish_discovery()

    async def stop(self) -> None:
        await self._publish_status("offline")
        await asyncio.to_thread(self._client.disconnect)
        self._client.loop_stop()

    async def _publish_status(self, status: str) -> None:
        await self._publish(f"{self._config.base_topic}/status", status, retain=True)

    async def _publish(self, topic: str, payload: Any, retain: bool = False) -> None:
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload)
        result = await asyncio.to_thread(
            self._client.publish, topic, payload=payload, qos=1, retain=retain
        )
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            LOGGER.warning("Failed to publish to %s: rc=%s", topic, result.rc)

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Dict[str, Any], rc: int):
        if rc != 0:
            LOGGER.error("MQTT connection failed with code %s", rc)
            return
        LOGGER.info("Connected to MQTT broker")
        base = self._config.base_topic
        client.subscribe(f"{base}/+/light/set")
        client.subscribe(f"{base}/+/power/set")

    def _on_message(self, client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage):
        LOGGER.debug("Received MQTT message on %s", message.topic)
        if self._loop:
            self._loop.call_soon_threadsafe(
                self._command_queue.put_nowait, (message.topic, message.payload)
            )

    async def run(self) -> None:
        while True:
            topic, payload = await self._command_queue.get()
            try:
                await self._handle_command(topic, payload)
            except Exception:  # pragma: no cover - defensive
                LOGGER.exception("Failed to handle MQTT command for %s", topic)

    async def _handle_command(self, topic: str, payload: bytes) -> None:
        base = f"{self._config.base_topic}/"
        if not topic.startswith(base):
            LOGGER.warning("Unexpected MQTT topic: %s", topic)
            return
        parts = topic[len(base) :].split("/")
        if len(parts) != 3:
            LOGGER.warning("Invalid command topic: %s", topic)
            return
        tablet_id, domain, action = parts
        try:
            controller = self._manager.get(tablet_id)
        except KeyError:
            LOGGER.warning("Command for unknown tablet %s", tablet_id)
            return
        if domain == "light" and action == "set":
            await self._handle_light_command(controller, payload)
        elif domain == "power" and action == "set":
            await self._handle_power_command(controller, payload)
        else:
            LOGGER.warning("Unsupported command topic: %s", topic)

    async def _handle_light_command(self, controller: TabletController, payload: bytes) -> None:
        try:
            data = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError:
            text = payload.decode("utf-8", errors="ignore").strip()
            LOGGER.warning("Invalid JSON payload for light command: %s", text)
            return
        state = data.get("state", "ON").upper()
        color = data.get("color") or {}
        red = color.get("r")
        green = color.get("g")
        blue = color.get("b")
        if red is None or green is None or blue is None:
            last = controller.state.last_status.led if controller.state.last_status else None
            if last is None:
                LOGGER.warning("Light command missing colour payload and no prior state")
                return
            red, green, blue = last.red, last.green, last.blue
        await controller.set_led(on=state != "OFF", red=int(red), green=int(green), blue=int(blue))

    async def _handle_power_command(self, controller: TabletController, payload: bytes) -> None:
        text = payload.decode("utf-8", errors="ignore").strip().upper()
        if text not in {"ON", "OFF"}:
            try:
                data = json.loads(payload.decode("utf-8"))
                text = str(data.get("state", "")).upper()
            except json.JSONDecodeError:
                LOGGER.warning("Invalid payload for power command: %s", payload)
                return
        await controller.set_power(on=text == "ON")

    async def _publish_discovery(self) -> None:
        tasks = []
        for controller in self._manager:
            tablet = controller.config
            discovery_base = self._config.ha_discovery_prefix
            light_topic = f"{discovery_base}/light/{tablet.id}/config"
            power_topic = f"{discovery_base}/switch/{tablet.id}/config"
            light_payload = {
                "name": f"{tablet.name} LED",
                "unique_id": f"sicp_{tablet.id}_light",
                "command_topic": f"{self._config.base_topic}/{tablet.id}/light/set",
                "state_topic": f"{self._config.base_topic}/{tablet.id}/light/state",
                "json_attributes_topic": f"{self._config.base_topic}/{tablet.id}/attributes",
                "schema": "json",
                "supported_color_modes": ["rgb"],
                "availability_topic": f"{self._config.base_topic}/status",
                "payload_available": "online",
                "payload_not_available": "offline",
            }
            power_payload = {
                "name": f"{tablet.name} Power",
                "unique_id": f"sicp_{tablet.id}_power",
                "command_topic": f"{self._config.base_topic}/{tablet.id}/power/set",
                "state_topic": f"{self._config.base_topic}/{tablet.id}/power/state",
                "availability_topic": f"{self._config.base_topic}/status",
                "payload_available": "online",
                "payload_not_available": "offline",
                "device": {
                    "identifiers": [f"sicp_{tablet.id}"],
                    "name": tablet.name,
                    "manufacturer": "Philips",
                    "model": "Signage Tablet",
                },
            }
            light_payload["device"] = power_payload["device"]
            tasks.append(self._publish(light_topic, light_payload, retain=True))
            tasks.append(self._publish(power_topic, power_payload, retain=True))
        await asyncio.gather(*tasks)

    async def _handle_tablet_update(self, controller: TabletController, status: Any) -> None:
        await self.publish_state(controller)

    async def publish_state(self, controller: TabletController) -> None:
        status = controller.state.last_status
        if not status:
            return
        tablet = controller.config
        light_state = {
            "state": "ON" if status.led.on else "OFF",
            "color": {"r": status.led.red, "g": status.led.green, "b": status.led.blue},
        }
        attributes = {
            "last_success": controller.state.last_success.isoformat()
            if controller.state.last_success
            else None,
            "last_error": controller.state.last_error,
            "ip": tablet.host,
        }
        await asyncio.gather(
            self._publish(
                f"{self._config.base_topic}/{tablet.id}/light/state", light_state, retain=True
            ),
            self._publish(
                f"{self._config.base_topic}/{tablet.id}/power/state",
                "ON" if status.power.on else "OFF",
                retain=True,
            ),
            self._publish(
                f"{self._config.base_topic}/{tablet.id}/attributes", attributes, retain=True
            ),
        )
