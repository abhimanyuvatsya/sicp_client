"""MQTT integration for bridging with Home Assistant."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import paho.mqtt.client as mqtt

from .config import MqttConfig, TabletConfig
from .manager import TabletManager, TabletStatus

LOGGER = logging.getLogger(__name__)


class MqttBridge:
    def __init__(self, config: MqttConfig, manager: TabletManager) -> None:
        self._config = config
        self._manager = manager
        self._client = mqtt.Client()
        if config.username:
            self._client.username_pw_set(config.username, config.password)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._connected = asyncio.Event()

    def start(self) -> None:
        if not self._config.enabled:
            LOGGER.info("MQTT bridge disabled by configuration")
            return
        LOGGER.info("Starting MQTT bridge -> %s:%s", self._config.host, self._config.port)
        self._loop = asyncio.get_running_loop()
        self._client.will_set(self._availability_topic("bridge"), payload="offline", retain=True)
        self._client.connect_async(self._config.host, self._config.port, keepalive=self._config.keepalive)
        self._client.loop_start()

    async def stop(self) -> None:
        if not self._config.enabled:
            return
        LOGGER.info("Stopping MQTT bridge")
        self._client.publish(self._availability_topic("bridge"), payload="offline", retain=True)
        self._client.loop_stop()
        self._client.disconnect()

    def publish_status(self, tablet: TabletConfig, status: TabletStatus) -> None:
        if not self._config.enabled:
            return
        if not self._connected.is_set():
            LOGGER.debug("MQTT bridge not yet connected; skipping publish")
            return
        attributes = {
            "last_error": status.last_error,
            "last_update": status.last_update.isoformat() if status.last_update else None,
        }
        availability = "online" if status.available else "offline"
        self._client.publish(
            self._availability_topic(tablet.identifier), payload=availability, retain=True
        )
        led_payload = {
            "state": "ON" if (status.led and status.led.on) else "OFF",
        }
        if status.led:
            led_payload["color"] = {
                "r": status.led.red,
                "g": status.led.green,
                "b": status.led.blue,
            }
            led_payload["hex"] = status.led.hex_color
        self._client.publish(
            self._led_state_topic(tablet.identifier),
            payload=json.dumps(led_payload),
            retain=True,
        )
        self._client.publish(
            self._power_state_topic(tablet.identifier),
            payload="ON" if (status.power and status.power.on) else "OFF",
            retain=True,
        )
        self._client.publish(
            self._attributes_topic(tablet.identifier),
            payload=json.dumps(attributes),
            retain=True,
        )

    def publish_discovery(self, tablet: TabletConfig) -> None:
        if not self._config.enabled:
            return
        device = {
            "name": tablet.name,
            "identifiers": [f"sicp_{tablet.identifier}"],
            "manufacturer": "Philips",
            "model": "Signage Tablet",
        }
        light_payload = {
            "name": f"{tablet.name} LED",
            "uniq_id": f"sicp_{tablet.identifier}_led",
            "cmd_t": self._led_command_topic(tablet.identifier),
            "stat_t": self._led_state_topic(tablet.identifier),
            "json_attr_t": self._attributes_topic(tablet.identifier),
            "schema": "json",
            "rgb": True,
            "availability_topic": self._availability_topic(tablet.identifier),
            "device": device,
        }
        switch_payload = {
            "name": f"{tablet.name} Power",
            "uniq_id": f"sicp_{tablet.identifier}_power",
            "cmd_t": self._power_command_topic(tablet.identifier),
            "stat_t": self._power_state_topic(tablet.identifier),
            "pl_on": "ON",
            "pl_off": "OFF",
            "availability_topic": self._availability_topic(tablet.identifier),
            "device": device,
        }
        self._client.publish(
            f"{self._config.discovery_prefix}/light/{tablet.identifier}/config",
            payload=json.dumps(light_payload),
            retain=True,
        )
        self._client.publish(
            f"{self._config.discovery_prefix}/switch/{tablet.identifier}_power/config",
            payload=json.dumps(switch_payload),
            retain=True,
        )

    # MQTT callbacks -----------------------------------------------------------------

    def _on_connect(self, client: mqtt.Client, userdata, flags, rc):  # noqa: ANN001
        if rc != 0:
            LOGGER.error("MQTT connection failed with rc=%s", rc)
            return
        LOGGER.info("Connected to MQTT broker")
        self._connected.set()
        client.publish(self._availability_topic("bridge"), payload="online", retain=True)
        for tablet in self._manager.get_tablets():
            self.publish_discovery(tablet)
            self._subscribe_tablet(tablet.identifier)
            status = self._manager.get_status(tablet.identifier)
            self.publish_status(tablet, status)

    def _on_disconnect(self, client: mqtt.Client, userdata, rc):  # noqa: ANN001
        LOGGER.warning("Disconnected from MQTT broker rc=%s", rc)
        self._connected.clear()

    def _on_message(self, client: mqtt.Client, userdata, msg: mqtt.MQTTMessage):  # noqa: ANN001
        try:
            topic = msg.topic
            payload = msg.payload.decode()
        except UnicodeDecodeError:
            LOGGER.error("Received non-UTF8 MQTT payload on %s", msg.topic)
            return
        LOGGER.debug("MQTT message on %s: %s", topic, payload)
        if topic.endswith("/led/set"):
            identifier = topic.split("/")[-3]
            self._handle_led_command(identifier, payload)
        elif topic.endswith("/power/set"):
            identifier = topic.split("/")[-3]
            self._handle_power_command(identifier, payload)

    def _handle_led_command(self, identifier: str, payload: str) -> None:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            LOGGER.error("Invalid JSON payload for LED command: %s", payload)
            return
        state = data.get("state", "").upper()
        on = state != "OFF"
        color = None
        if "hex" in data:
            color = data["hex"]
        elif "color" in data and isinstance(data["color"], dict):
            color_dict = data["color"]
            try:
                color = "#{:02X}{:02X}{:02X}".format(
                    int(color_dict.get("r", 0)),
                    int(color_dict.get("g", 0)),
                    int(color_dict.get("b", 0)),
                )
            except (ValueError, TypeError):
                LOGGER.error("Invalid RGB values in LED command: %s", color_dict)
        if self._loop is None:
            LOGGER.error("No asyncio loop available for LED command")
            return
        asyncio.run_coroutine_threadsafe(
            self._manager.set_led(identifier, on=on, color=color), self._loop
        )

    def _handle_power_command(self, identifier: str, payload: str) -> None:
        state = payload.strip().upper()
        on = state != "OFF"
        if self._loop is None:
            LOGGER.error("No asyncio loop available for power command")
            return
        asyncio.run_coroutine_threadsafe(self._manager.set_power(identifier, on=on), self._loop)

    # Topic helpers ------------------------------------------------------------------

    def _base_topic(self, identifier: str) -> str:
        return f"{self._config.base_topic}/{identifier}"

    def _led_state_topic(self, identifier: str) -> str:
        return f"{self._base_topic(identifier)}/led/state"

    def _led_command_topic(self, identifier: str) -> str:
        return f"{self._base_topic(identifier)}/led/set"

    def _power_state_topic(self, identifier: str) -> str:
        return f"{self._base_topic(identifier)}/power/state"

    def _power_command_topic(self, identifier: str) -> str:
        return f"{self._base_topic(identifier)}/power/set"

    def _attributes_topic(self, identifier: str) -> str:
        return f"{self._base_topic(identifier)}/attributes"

    def _availability_topic(self, identifier: str) -> str:
        return f"{self._base_topic(identifier)}/availability"

    def _subscribe_tablet(self, identifier: str) -> None:
        self._client.subscribe(self._led_command_topic(identifier))
        self._client.subscribe(self._power_command_topic(identifier))
