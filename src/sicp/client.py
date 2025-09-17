"""High level Philips SICP client abstraction."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from . import protocol
from .protocol import LedState, PowerState, TabletStatus
from .transport import ConnectionError, send_with_retries

LOGGER = logging.getLogger(__name__)


@dataclass
class ClientConfig:
    host: str
    port: int = 5000
    timeout: float = 5.0
    retries: int = 2
    retry_delay: float = 1.0


class SICPClient:
    def __init__(self, config: ClientConfig):
        self._config = config

    def set_led(self, *, on: bool, red: int, green: int, blue: int) -> TabletStatus:
        frame = protocol.build_set_frame(on=on, red=red, green=green, blue=blue)
        LOGGER.info(
            "Sending LED frame to %s:%s (on=%s rgb=%s)",
            self._config.host,
            self._config.port,
            on,
            (red, green, blue),
        )
        reply = send_with_retries(
            host=self._config.host,
            port=self._config.port,
            frame=frame,
            timeout=self._config.timeout,
            expect_reply=True,
            retries=self._config.retries,
            retry_delay=self._config.retry_delay,
        )
        LOGGER.debug("LED SET acknowledgement: %s", protocol.format_frame(reply))
        return self.get_status()

    def get_status(self) -> TabletStatus:
        frame = protocol.build_get_frame()
        LOGGER.debug("Sending GET frame to %s:%s", self._config.host, self._config.port)
        reply = send_with_retries(
            host=self._config.host,
            port=self._config.port,
            frame=frame,
            timeout=self._config.timeout,
            expect_reply=True,
            retries=self._config.retries,
            retry_delay=self._config.retry_delay,
        )
        LOGGER.debug("GET reply: %s", protocol.format_frame(reply))
        return protocol.parse_get_reply(reply)

    def set_power(self, *, on: bool) -> TabletStatus:
        frame = protocol.build_power_frame(on=on)
        LOGGER.info(
            "Sending POWER frame to %s:%s (on=%s)",
            self._config.host,
            self._config.port,
            on,
        )
        reply = send_with_retries(
            host=self._config.host,
            port=self._config.port,
            frame=frame,
            timeout=self._config.timeout,
            expect_reply=True,
            retries=self._config.retries,
            retry_delay=self._config.retry_delay,
        )
        LOGGER.debug("POWER acknowledgement: %s", protocol.format_frame(reply))
        return self.get_status()

    def ping(self) -> Optional[TabletStatus]:
        try:
            return self.get_status()
        except ConnectionError:
            LOGGER.warning("Unable to reach tablet %s", self._config.host, exc_info=True)
            return None


__all__ = [
    "ClientConfig",
    "LedState",
    "PowerState",
    "SICPClient",
    "TabletStatus",
    "ConnectionError",
]
