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
from . import presets
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
    light_effect_state: str
    light_effect_command: str
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
            light_effect_state=f"{base}/light/effect/state",
            light_effect_command=f"{base}/light/effect/set",
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
        topics += [(value.light_effect_command, 1) for value in self._topics.values()]
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
                "manufacturer": "Philips SICP",
                "model": "Android Tablet",
            }
            # Expose presets as MQTT Light effects, but do not include "Off".
            effect_options = [label for label in presets.labels() if label.lower() != "off"]
            light_payload = {
                "name": f"LED Strip",
                "object_id": f"{tablet_cfg.identifier}_led_strip",
                "unique_id": f"sicp_{tablet_cfg.identifier}_light",
                "state_topic": topics.light_state,
                "command_topic": topics.light_command,
                "availability_topic": topics.availability,
                "payload_on": "ON",
                "payload_off": "OFF",
                "effect_state_topic": topics.light_effect_state,
                "effect_command_topic": topics.light_effect_command,
                "effect_list": effect_options,
                "qos": 1,
                "device": device_payload,
            }
            power_payload = {
                "name": f"Wake Device",
                "object_id": f"{tablet_cfg.identifier}_wake_device",
                "unique_id": f"sicp_{tablet_cfg.identifier}_wake",
                "command_topic": topics.power_command,
                "availability_topic": topics.availability,
                "payload_press": "WAKE",
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
                f"{discovery_prefix}/button/{tablet_cfg.identifier}/config",
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
        effect_label = None
        if state.preset:
            try:
                effect_label = presets.resolve(state.preset).label
                if effect_label.lower() == "off":
                    effect_label = None
            except ValueError:
                effect_label = None
        light_state_str = "ON" if state.led_on else "OFF"
        await self._client.publish(topics.light_state, light_state_str, qos=1, retain=True)
        await self._client.publish(
            topics.light_effect_state,
            effect_label or "",
            qos=1,
            retain=True,
        )
        LOGGER.debug("Published light state for %s: %s (effect=%s)", tablet_id, light_state_str, effect_label)
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
            if topic == topics.light_effect_command:
                LOGGER.info("MQTT effect command for %s: %s", tablet_id, payload)
                await self._handle_effect_command(tablet_id, payload)
                return
            if topic == topics.power_command:
                LOGGER.info("MQTT power command for %s: %s", tablet_id, payload)
                await self._handle_power_command(tablet_id, payload)
                return
        LOGGER.warning("Received command for unknown topic %s", topic)

    async def _handle_light_command(self, tablet_id: str, payload: str) -> None:
        value = payload.strip().upper()
        on = value != "OFF"
        if not on:
            LOGGER.debug("Applying light command to %s -> OFF", tablet_id)
            await self.tablets.set_light(tablet_id, on=False, red=0, green=0, blue=0)
            return
        state = self.tablets.get_state(tablet_id)
        preset_id = state.preset or presets.presets()[0].identifier
        if preset_id == "off":
            preset_id = presets.presets()[0].identifier
        preset = presets.resolve(preset_id)
        LOGGER.debug(
            "Applying light command to %s -> ON preset %s", tablet_id, preset.identifier
        )
        await self.tablets.set_light(
            tablet_id,
            on=True,
            red=preset.red,
            green=preset.green,
            blue=preset.blue,
        )

    async def _handle_effect_command(self, tablet_id: str, payload: str) -> None:
        label = payload.strip()
        try:
            preset = presets.resolve_label(label)
        except ValueError as exc:
            LOGGER.warning("Unknown preset label from MQTT for %s: %s", tablet_id, exc)
            return
        LOGGER.debug(
            "Applying effect command to %s -> %s", tablet_id, preset.identifier
        )
        if preset.identifier == "off":
            await self.tablets.set_light(
                tablet_id,
                on=False,
                red=0,
                green=0,
                blue=0,
            )
        else:
            await self.tablets.set_light(
                tablet_id,
                on=True,
                red=preset.red,
                green=preset.green,
                blue=preset.blue,
            )

    async def _handle_power_command(self, tablet_id: str, payload: str) -> None:
        value = payload.strip().upper()
        if value in {"WAKE", "ON"}:
            LOGGER.debug("Applying wake command to %s", tablet_id)
            await self.tablets.set_power(tablet_id, on=True)
            return
        LOGGER.info("Ignoring unsupported power payload for %s: %s", tablet_id, payload)
