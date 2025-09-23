"""Configuration models and helpers for the SICP service."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import yaml


@dataclass(frozen=True)
class MQTTConfig:
    """Configuration for MQTT connectivity."""

    host: str
    port: int = 1883
    username: Optional[str] = None
    password: Optional[str] = None
    base_topic: str = "sicp_tablets"
    client_id_prefix: str = "sicp"
    keepalive: int = 60
    tls_enabled: bool = False
    tls_ca_cert: Optional[str] = None


@dataclass(frozen=True)
class HomeAssistantConfig:
    """Configuration for Home Assistant auto-discovery."""

    enabled: bool = True
    discovery_prefix: str = "homeassistant"


@dataclass(frozen=True)
class TabletConfig:
    """Description of a Philips tablet running the SICP protocol."""

    identifier: str
    host: str
    port: int = 5000
    name: Optional[str] = None

    def display_name(self) -> str:
        return self.name or self.identifier


@dataclass(frozen=True)
class WebConfig:
    """Configuration for the embedded web interface."""

    host: str = "0.0.0.0"
    port: int = 8080


@dataclass(frozen=True)
class PollingConfig:
    """Polling-related configuration."""

    interval_seconds: float = 30.0
    timeout_seconds: float = 3.0
    retry_attempts: int = 2
    retry_delay_seconds: float = 1.0
    verification_delay_seconds: float = 0.0


@dataclass(frozen=True)
class ServiceConfig:
    """Top-level configuration for the SICP management service."""

    mqtt: MQTTConfig
    home_assistant: HomeAssistantConfig
    tablets: List[TabletConfig]
    polling: PollingConfig = field(default_factory=PollingConfig)
    web: WebConfig = field(default_factory=WebConfig)
    log_directory: Optional[str] = None


def _validate_unique_identifiers(tablets: Iterable[TabletConfig]) -> None:
    seen = set()
    for tablet in tablets:
        if tablet.identifier in seen:
            raise ValueError(f"Duplicate tablet identifier: {tablet.identifier}")
        seen.add(tablet.identifier)


def load_config(path: Path) -> ServiceConfig:
    """Load configuration from a YAML file."""

    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("Configuration root must be a mapping")

    mqtt_raw = raw.get("mqtt", {})
    ha_raw = raw.get("home_assistant", {})
    polling_raw = raw.get("polling", {})
    web_raw = raw.get("web", {})
    tablets_raw = raw.get("tablets")

    if not isinstance(tablets_raw, list) or not tablets_raw:
        raise ValueError("At least one tablet must be configured")

    tablets: List[TabletConfig] = []
    for entry in tablets_raw:
        if not isinstance(entry, dict):
            raise ValueError("Tablet entries must be mappings")
        identifier = entry.get("id") or entry.get("identifier")
        host = entry.get("host")
        if not identifier:
            raise ValueError("Tablet identifier is required")
        if not host:
            raise ValueError(f"Tablet {identifier} host is required")
        tablet = TabletConfig(
            identifier=identifier,
            host=host,
            port=int(entry.get("port", 5000)),
            name=entry.get("name"),
        )
        tablets.append(tablet)

    _validate_unique_identifiers(tablets)

    mqtt = MQTTConfig(
        host=mqtt_raw.get("host", "localhost"),
        port=int(mqtt_raw.get("port", 1883)),
        username=mqtt_raw.get("username"),
        password=mqtt_raw.get("password"),
        base_topic=mqtt_raw.get("base_topic", "sicp_tablets"),
        client_id_prefix=mqtt_raw.get("client_id_prefix", "sicp"),
        keepalive=int(mqtt_raw.get("keepalive", 60)),
        tls_enabled=bool(mqtt_raw.get("tls_enabled", False)),
        tls_ca_cert=mqtt_raw.get("tls_ca_cert"),
    )

    home_assistant = HomeAssistantConfig(
        enabled=bool(ha_raw.get("enabled", True)),
        discovery_prefix=ha_raw.get("discovery_prefix", "homeassistant"),
    )

    polling = PollingConfig(
        interval_seconds=float(polling_raw.get("interval_seconds", 30.0)),
        timeout_seconds=float(polling_raw.get("timeout_seconds", 3.0)),
        retry_attempts=int(polling_raw.get("retry_attempts", 2)),
        retry_delay_seconds=float(polling_raw.get("retry_delay_seconds", 1.0)),
        verification_delay_seconds=float(polling_raw.get("verification_delay_seconds", 0.0)),
    )

    web = WebConfig(
        host=web_raw.get("host", "0.0.0.0"),
        port=int(web_raw.get("port", 8080)),
    )

    return ServiceConfig(
        mqtt=mqtt,
        home_assistant=home_assistant,
        tablets=tablets,
        polling=polling,
        web=web,
        log_directory=raw.get("log_directory"),
    )


def load_default_config() -> ServiceConfig:
    """Load configuration from the default location."""

    default_path = Path("/etc/sicp_service/config.yaml")
    return load_config(default_path)
