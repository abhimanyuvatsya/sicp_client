"""MQTT bridge between Home Assistant and the tablet service."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass
from typing import Dict, Optional

from asyncio_mqtt import Client, MqttError, TLSParameters

from . import config as config_module
from .manager import TabletManager, TabletState

LOGGER = logging.getLogger(__name__)

AVAILABILITY_ONLINE = "online"
AVAILABILITY_OFFLINE = "offline"


@dataclass
class MQTTTopics:
    base: str
    availability: str
    light_state: str
    light_command: str
    power_state: str
    power_command: str

    @staticmethod
    def build(base_topic: str, tablet_id: str) -> "MQTTTopics":
        base = f"{base_topic}/{tablet_id}"
        return MQTTTopics(
            base=base,
            availability=f"{base}/availability",
            light_state=f"{base}/light/state",
            light_command=f"{base}/light/set",
            power_state=f"{base}/power/state",
            power_command=f"{base}/power/set",
        )


class MQTTManager:
    """Handles MQTT connectivity, discovery, and command bridging."""

    def __init__(self, cfg: config_module.ServiceConfig, tablets: TabletManager) -> None:
        self.cfg = cfg
        self.tablets = tablets
        self._topics: Dict[str, MQTTTopics] = {
            tablet_cfg.identifier: MQTTTopics.build(cfg.mqtt.base_topic, tablet_cfg.identifier)
            for tablet_cfg in cfg.tablets
        }
        self._client: Optional[Client] = None
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task[None]] = None
        self.tablets.add_listener(self._handle_state_update)

    async def start(self) -> None:
        LOGGER.info("Starting MQTT manager")
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        LOGGER.info("Stopping MQTT manager")
        self._stop_event.set()
        if self._task:
            await self._task
            self._task = None

    async def _run(self) -> None:
        backoff = 1
        while not self._stop_event.is_set():
            try:
                await self._connect_and_loop()
                backoff = 1
            except MqttError as exc:
                LOGGER.warning("MQTT connection lost: %s", exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _connect_and_loop(self) -> None:
        mqtt_cfg = self.cfg.mqtt
        LOGGER.info("Connecting to MQTT broker %s:%s", mqtt_cfg.host, mqtt_cfg.port)
        tls_params = None
        if mqtt_cfg.tls_enabled:
            tls_params = TLSParameters(ca_certs=mqtt_cfg.tls_ca_cert)
        client_id = f"{mqtt_cfg.client_id_prefix}-{id(self)}"
        async with Client(
            hostname=mqtt_cfg.host,
            port=mqtt_cfg.port,
            username=mqtt_cfg.username,
            password=mqtt_cfg.password,
            client_id=client_id,
            keepalive=mqtt_cfg.keepalive,
            tls_params=tls_params,
        ) as client:
            self._client = client
            LOGGER.info(
                "Connected to MQTT broker %s:%s as %s",
                mqtt_cfg.host,
                mqtt_cfg.port,
                client_id,
            )
            await self._publish_discovery()
            await self._publish_all_states()
            async with client.unfiltered_messages() as messages:
                await self._subscribe_topics()
                await self._publish_availability(AVAILABILITY_ONLINE)
                message_task = asyncio.create_task(self._message_loop(messages))
                stop_task = asyncio.create_task(self._stop_event.wait())
                done, _ = await asyncio.wait(
                    {message_task, stop_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if stop_task in done:
                    message_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await message_task
                else:
                    stop_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await stop_task
            await self._publish_availability(AVAILABILITY_OFFLINE)
            self._client = None
            LOGGER.info("Disconnected from MQTT broker %s:%s", mqtt_cfg.host, mqtt_cfg.port)

    async def _subscribe_topics(self) -> None:
        assert self._client is not None
        topics = [(value.light_command, 1) for value in self._topics.values()]
        topics += [(value.power_command, 1) for value in self._topics.values()]
        for topic, qos in topics:
            await self._client.subscribe((topic, qos))
            LOGGER.debug("Subscribed to %s", topic)

    async def _publish_discovery(self) -> None:
        if not self.cfg.home_assistant.enabled or not self._client:
            return
        for tablet_cfg in self.cfg.tablets:
            topics = self._topics[tablet_cfg.identifier]
            device_payload = {
                "identifiers": [f"sicp_tablet_{tablet_cfg.identifier}"],
                "name": tablet_cfg.display_name(),
                "manufacturer": "Philips",
                "model": "Android Tablet",
            }
            light_payload = {
                "name": f"{tablet_cfg.display_name()} LED",
                "unique_id": f"sicp_{tablet_cfg.identifier}_light",
                "state_topic": topics.light_state,
                "command_topic": topics.light_command,
                "availability_topic": topics.availability,
                "qos": 1,
                "schema": "json",
                "supported_color_modes": ["rgb"],
                "device": device_payload,
            }
            power_payload = {
                "name": f"{tablet_cfg.display_name()} Power",
                "unique_id": f"sicp_{tablet_cfg.identifier}_power",
                "state_topic": topics.power_state,
                "command_topic": topics.power_command,
                "availability_topic": topics.availability,
                "payload_on": "ON",
                "payload_off": "OFF",
                "qos": 1,
                "device": device_payload,
            }
            discovery_prefix = self.cfg.home_assistant.discovery_prefix
            await self._client.publish(
                f"{discovery_prefix}/light/{tablet_cfg.identifier}/config",
                json.dumps(light_payload),
                qos=1,
                retain=True,
            )
            await self._client.publish(
                f"{discovery_prefix}/switch/{tablet_cfg.identifier}/config",
                json.dumps(power_payload),
                qos=1,
                retain=True,
            )
            LOGGER.info("Published Home Assistant discovery for %s", tablet_cfg.identifier)

    async def _publish_availability(self, payload: str) -> None:
        if not self._client:
            return
        for topics in self._topics.values():
            await self._client.publish(topics.availability, payload, qos=1, retain=True)
            LOGGER.info("Published availability %s -> %s", topics.availability, payload)

    async def _publish_all_states(self) -> None:
        for tablet_id, state in self.tablets.all_states().items():
            await self._publish_state(tablet_id, state)

    async def _publish_state(self, tablet_id: str, state: TabletState) -> None:
        if not self._client:
            return
        topics = self._topics[tablet_id]
        availability = AVAILABILITY_ONLINE if state.available else AVAILABILITY_OFFLINE
        await self._client.publish(topics.availability, availability, qos=1, retain=True)
        light_state = {
            "state": "ON" if state.led_on else "OFF",
            "color": {
                "r": state.red,
                "g": state.green,
                "b": state.blue,
            },
            "color_mode": "rgb",
        }
        await self._client.publish(topics.light_state, json.dumps(light_state), qos=1, retain=True)
        LOGGER.debug("Published light state for %s: %s", tablet_id, light_state)
        if state.power_on is None:
            power_payload = "unknown"
        else:
            power_payload = "ON" if state.power_on else "OFF"
        await self._client.publish(topics.power_state, power_payload, qos=1, retain=True)
        LOGGER.debug("Published power state for %s: %s", tablet_id, power_payload)

    async def _handle_state_update(self, tablet_id: str, state: TabletState) -> None:
        if self._client:
            await self._publish_state(tablet_id, state)

    async def _message_loop(self, messages) -> None:
        async for message in messages:
            if self._stop_event.is_set():
                break
            try:
                payload = message.payload.decode()
            except UnicodeDecodeError:
                LOGGER.warning("Received non-text payload on %s", message.topic)
                continue
            await self._process_message(message.topic, payload)

    async def _process_message(self, topic: str, payload: str) -> None:
        LOGGER.debug("MQTT message on %s: %s", topic, payload)
        for tablet_id, topics in self._topics.items():
            if topic == topics.light_command:
                LOGGER.info("MQTT light command for %s: %s", tablet_id, payload)
                await self._handle_light_command(tablet_id, payload)
                return
            if topic == topics.power_command:
                LOGGER.info("MQTT power command for %s: %s", tablet_id, payload)
                await self._handle_power_command(tablet_id, payload)
                return
        LOGGER.warning("Received command for unknown topic %s", topic)

    async def _handle_light_command(self, tablet_id: str, payload: str) -> None:
        try:
            message = json.loads(payload)
        except json.JSONDecodeError as exc:
            LOGGER.warning("Invalid JSON on %s: %s", tablet_id, exc)
            return
        state_value = message.get("state")
        color = message.get("color", {})
        on = True
        if isinstance(state_value, str):
            on = state_value.upper() != "OFF"
        red = self._clamp_color(color.get("r", 0))
        green = self._clamp_color(color.get("g", 0))
        blue = self._clamp_color(color.get("b", 0))
        if not on:
            red = green = blue = 0
        LOGGER.debug(
            "Applying light command to %s -> on=%s rgb=(%s,%s,%s)",
            tablet_id,
            on,
            red,
            green,
            blue,
        )
        await self.tablets.set_light(tablet_id, on=on, red=red, green=green, blue=blue)

    async def _handle_power_command(self, tablet_id: str, payload: str) -> None:
        value = payload.strip().upper()
        on = value != "OFF"
        LOGGER.debug("Applying power command to %s -> %s", tablet_id, on)
        await self.tablets.set_power(tablet_id, on=on)

    @staticmethod
    def _clamp_color(raw: object) -> int:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return 0
        return max(0, min(255, value))
