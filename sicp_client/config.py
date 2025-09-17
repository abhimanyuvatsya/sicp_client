"""Configuration loading utilities for the SICP control service."""

from __future__ import annotations

import ipaddress
import pathlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

from .protocol import DEFAULT_PORT, DEFAULT_RETRIES, DEFAULT_RETRY_DELAY, DEFAULT_TIMEOUT


class ConfigurationError(RuntimeError):
    """Raised when the provided configuration file is invalid."""


@dataclass(slots=True)
class TabletConfig:
    name: str
    host: str
    port: int = DEFAULT_PORT
    timeout: float = DEFAULT_TIMEOUT
    retries: int = DEFAULT_RETRIES
    retry_delay: float = DEFAULT_RETRY_DELAY
    poll_interval: float = 30.0
    ha_light: bool = True
    ha_power_switch: bool = True

    def __post_init__(self) -> None:
        if not self.name:
            raise ConfigurationError("Tablet name must not be empty")
        try:
            ipaddress.ip_address(self.host)
        except ValueError:
            if not self.host:
                raise ConfigurationError("Tablet host must be provided")
        if not (0 < self.port < 65536):
            raise ConfigurationError(f"Tablet {self.name}: invalid port {self.port}")
        if self.timeout <= 0:
            raise ConfigurationError(f"Tablet {self.name}: timeout must be > 0")
        if self.retries < 0:
            raise ConfigurationError(f"Tablet {self.name}: retries must be >= 0")
        if self.retry_delay < 0:
            raise ConfigurationError(f"Tablet {self.name}: retry_delay must be >= 0")
        if self.poll_interval <= 0:
            raise ConfigurationError(f"Tablet {self.name}: poll_interval must be > 0")


@dataclass(slots=True)
class MqttConfig:
    host: str
    port: int = 1883
    username: Optional[str] = None
    password: Optional[str] = None
    base_topic: str = "sicp"
    discovery_prefix: str = "homeassistant"
    client_id: str = "sicp-bridge"
    keepalive: int = 60
    reconnect_interval: int = 5
    enable_tls: bool = False

    def __post_init__(self) -> None:
        if not self.host:
            raise ConfigurationError("MQTT host must be provided")
        if not (0 < self.port < 65536):
            raise ConfigurationError(f"Invalid MQTT port {self.port}")
        if self.keepalive <= 0:
            raise ConfigurationError("MQTT keepalive must be > 0")
        if self.reconnect_interval <= 0:
            raise ConfigurationError("MQTT reconnect interval must be > 0")
        base = self.base_topic.strip()
        if not base:
            raise ConfigurationError("MQTT base_topic must not be empty")
        if base.endswith("/"):
            raise ConfigurationError("MQTT base_topic must not end with /")
        self.base_topic = base
        prefix = self.discovery_prefix.strip()
        if not prefix:
            raise ConfigurationError("MQTT discovery_prefix must not be empty")
        if prefix.endswith("/"):
            raise ConfigurationError("MQTT discovery_prefix must not end with /")
        self.discovery_prefix = prefix


@dataclass(slots=True)
class WebConfig:
    bind_host: str = "0.0.0.0"
    bind_port: int = 8080
    log_history: int = 2000

    def __post_init__(self) -> None:
        if not (0 < self.bind_port < 65536):
            raise ConfigurationError(f"Invalid web bind_port {self.bind_port}")
        if self.log_history <= 0:
            raise ConfigurationError("log_history must be > 0")


@dataclass(slots=True)
class ServiceConfig:
    tablets: List[TabletConfig]
    mqtt: Optional[MqttConfig] = None
    web: WebConfig = field(default_factory=WebConfig)
    default_poll_interval: float = 60.0

    def __post_init__(self) -> None:
        if not self.tablets:
            raise ConfigurationError("At least one tablet must be configured")
        if self.default_poll_interval <= 0:
            raise ConfigurationError("default_poll_interval must be > 0")


def _load_yaml(path: pathlib.Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Configuration file {path} does not exist") from exc
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Unable to parse YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigurationError("Top level of configuration must be a mapping")
    return data


def _build_tablet(config: Dict[str, Any], defaults: Dict[str, Any]) -> TabletConfig:
    merged: Dict[str, Any] = {**defaults, **config}
    return TabletConfig(**merged)


def load_service_config(path: pathlib.Path) -> ServiceConfig:
    raw = _load_yaml(path)
    defaults: Dict[str, Any] = {}
    tablets_raw = raw.get("tablets")
    if not isinstance(tablets_raw, list):
        raise ConfigurationError("The 'tablets' section must be a list")

    tablet_defaults = raw.get("tablet_defaults", {})
    if not isinstance(tablet_defaults, dict):
        raise ConfigurationError("tablet_defaults must be a mapping when provided")

    defaults = {
        "port": tablet_defaults.get("port", DEFAULT_PORT),
        "timeout": tablet_defaults.get("timeout", DEFAULT_TIMEOUT),
        "retries": tablet_defaults.get("retries", DEFAULT_RETRIES),
        "retry_delay": tablet_defaults.get("retry_delay", DEFAULT_RETRY_DELAY),
        "poll_interval": tablet_defaults.get("poll_interval"),
        "ha_light": tablet_defaults.get("ha_light", True),
        "ha_power_switch": tablet_defaults.get("ha_power_switch", True),
    }
    defaults = {k: v for k, v in defaults.items() if v is not None}

    tablets = [_build_tablet(entry, defaults) for entry in tablets_raw]

    mqtt_section = raw.get("mqtt")
    mqtt_config = MqttConfig(**mqtt_section) if isinstance(mqtt_section, dict) else None

    web_section = raw.get("web", {})
    if not isinstance(web_section, dict):
        raise ConfigurationError("web section must be a mapping when provided")
    web_config = WebConfig(**web_section)

    default_poll = raw.get("default_poll_interval", 60.0)
    config = ServiceConfig(
        tablets=tablets,
        mqtt=mqtt_config,
        web=web_config,
        default_poll_interval=float(default_poll),
    )
    return config
