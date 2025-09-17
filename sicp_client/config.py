"""Configuration loading for the SICP service."""

from __future__ import annotations

import ipaddress
import pathlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml

DEFAULT_CONFIG_PATH = pathlib.Path("/etc/sicp/config.yml")


@dataclass
class TabletConfig:
    identifier: str
    name: str
    host: str
    port: int = 5000
    timeout: float = 5.0
    retries: int = 2
    retry_delay: float = 1.0
    poll_interval: float = 30.0

    def validate(self) -> None:
        if not self.identifier:
            raise ValueError("Tablet identifier must be provided")
        if not self.name:
            raise ValueError("Tablet friendly name must be provided")
        try:
            ipaddress.ip_address(self.host)
        except ValueError as exc:
            raise ValueError(f"Tablet {self.identifier} has invalid host '{self.host}'") from exc
        if self.port <= 0 or self.port > 65535:
            raise ValueError(f"Tablet {self.identifier} port must be between 1-65535")
        if self.timeout <= 0:
            raise ValueError(f"Tablet {self.identifier} timeout must be positive")
        if self.retries < 0:
            raise ValueError(f"Tablet {self.identifier} retries cannot be negative")
        if self.retry_delay < 0:
            raise ValueError(f"Tablet {self.identifier} retry delay cannot be negative")
        if self.poll_interval <= 0:
            raise ValueError(f"Tablet {self.identifier} poll interval must be positive")


@dataclass
class MqttConfig:
    host: str = "localhost"
    port: int = 1883
    username: Optional[str] = None
    password: Optional[str] = None
    base_topic: str = "sicp"
    discovery_prefix: str = "homeassistant"
    keepalive: int = 60
    enabled: bool = True

    def validate(self) -> None:
        if not self.host:
            raise ValueError("MQTT host must be provided")
        if self.port <= 0 or self.port > 65535:
            raise ValueError("MQTT port must be between 1-65535")
        if not self.base_topic:
            raise ValueError("MQTT base_topic must be provided")
        if not self.discovery_prefix:
            raise ValueError("MQTT discovery_prefix must be provided")
        if self.keepalive <= 0:
            raise ValueError("MQTT keepalive must be positive")


@dataclass
class WebConfig:
    host: str = "0.0.0.0"
    port: int = 8000

    def validate(self) -> None:
        if self.port <= 0 or self.port > 65535:
            raise ValueError("Web port must be between 1-65535")


@dataclass
class LoggingConfig:
    level: str = "INFO"
    path: Optional[str] = None


@dataclass
class Config:
    tablets: List[TabletConfig] = field(default_factory=list)
    mqtt: MqttConfig = field(default_factory=MqttConfig)
    web: WebConfig = field(default_factory=WebConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    poll_on_startup: bool = True

    def validate(self) -> None:
        if not self.tablets:
            raise ValueError("At least one tablet must be configured")
        identifiers = set()
        for tablet in self.tablets:
            tablet.validate()
            if tablet.identifier in identifiers:
                raise ValueError(f"Duplicate tablet identifier: {tablet.identifier}")
            identifiers.add(tablet.identifier)
        self.mqtt.validate()
        self.web.validate()


def _load_tablets(raw: List[Dict]) -> List[TabletConfig]:
    tablets: List[TabletConfig] = []
    for item in raw:
        tablets.append(TabletConfig(**item))
    return tablets


def load_config(path: pathlib.Path) -> Config:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    config = Config()
    if "tablets" in data:
        config.tablets = _load_tablets(data["tablets"])
    if "mqtt" in data:
        config.mqtt = MqttConfig(**data["mqtt"])
    if "web" in data:
        config.web = WebConfig(**data["web"])
    if "logging" in data:
        config.logging = LoggingConfig(**data["logging"])
    if "poll_on_startup" in data:
        config.poll_on_startup = bool(data["poll_on_startup"])
    config.validate()
    return config
