"""Configuration loader for the SICP service."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml


@dataclass
class TabletConfig:
    id: str
    name: str
    host: str
    port: int = 5000
    poll_interval: float = 30.0


@dataclass
class MQTTConfig:
    host: str
    port: int = 1883
    username: Optional[str] = None
    password: Optional[str] = None
    client_id: str = "sicp-controller"
    keepalive: int = 60
    base_topic: str = "sicp"
    ha_discovery_prefix: str = "homeassistant"


@dataclass
class ServiceConfig:
    mqtt: MQTTConfig
    tablets: List[TabletConfig] = field(default_factory=list)
    socket_timeout: float = 5.0
    socket_retries: int = 2
    socket_retry_delay: float = 1.0
    web_host: str = "0.0.0.0"
    web_port: int = 8080
    log_buffer: int = 2000


class ConfigError(RuntimeError):
    pass


def load_config(path: Path) -> ServiceConfig:
    if not path.exists():
        raise ConfigError(f"Configuration file not found: {path}")
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ConfigError("Configuration root must be a mapping")

    mqtt_data = data.get("mqtt")
    if not isinstance(mqtt_data, dict):
        raise ConfigError("'mqtt' section is required")
    mqtt = MQTTConfig(**mqtt_data)

    tablet_entries = data.get("tablets")
    if not isinstance(tablet_entries, list) or not tablet_entries:
        raise ConfigError("At least one tablet must be defined in 'tablets'")
    seen_ids: Dict[str, None] = {}
    tablets: List[TabletConfig] = []
    for entry in tablet_entries:
        if not isinstance(entry, dict):
            raise ConfigError("Tablet entries must be mappings")
        tablet = TabletConfig(**entry)
        if tablet.id in seen_ids:
            raise ConfigError(f"Duplicate tablet id: {tablet.id}")
        seen_ids[tablet.id] = None
        tablets.append(tablet)

    service_kwargs = {k: v for k, v in data.items() if k not in {"mqtt", "tablets"}}
    return ServiceConfig(mqtt=mqtt, tablets=tablets, **service_kwargs)


__all__ = [
    "ConfigError",
    "MQTTConfig",
    "ServiceConfig",
    "TabletConfig",
    "load_config",
]
