"""PetlibroCoordinator — push-based coordinator using MQTT."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_MQTT_HOST,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_PORT,
    CONF_MQTT_USERNAME,
    CONF_SERIAL,
    DOMAIN,
)
from .device import PetlibroDevice

_LOGGER = logging.getLogger(__name__)


class PetlibroCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate Petlibro device state via MQTT.

    Uses push-based updates — no polling. State updates arrive via MQTT
    messages and are pushed to entities via async_set_updated_data().
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"petlibro_{entry.data[CONF_SERIAL][-6:]}",
            # No update_interval — we're push-based
        )
        self._entry = entry
        self._serial = entry.data[CONF_SERIAL]
        self._mqtt_host = entry.data[CONF_MQTT_HOST]
        self._mqtt_port = entry.data[CONF_MQTT_PORT]
        self._mqtt_username = entry.data[CONF_MQTT_USERNAME]
        self._mqtt_password = entry.data[CONF_MQTT_PASSWORD]

        self.device = PetlibroDevice(
            serial=self._serial,
            mqtt_publish=self._mqtt_publish,
            on_state_changed=self._on_device_state_changed,
        )

        self._mqtt_client: Any = None
        self._unsubscribe: list = []

    async def async_setup(self) -> None:
        """Set up MQTT connection and subscribe to device topics."""
        from homeassistant.components import mqtt

        # Subscribe to all device messages (wildcard)
        topic = self.device.topics.subscribe_all
        _LOGGER.info("Subscribing to %s", topic)

        unsub = await mqtt.async_subscribe(
            self.hass,
            topic,
            self._on_mqtt_message,
            qos=0,
        )
        self._unsubscribe.append(unsub)

        # Start device heartbeat watchdog
        await self.device.start()

        # Set initial data
        self.async_set_updated_data(self.device.state)

    @callback
    def _on_mqtt_message(self, msg) -> None:
        """Handle incoming MQTT message from HA's MQTT component."""
        self.hass.async_create_task(
            self.device.handle_message(msg.topic, msg.payload)
        )

    async def _mqtt_publish(self, topic: str, payload: str) -> None:
        """Publish an MQTT message via HA's MQTT component."""
        from homeassistant.components import mqtt

        await mqtt.async_publish(
            self.hass,
            topic,
            payload,
            qos=0,
            retain=False,
        )

    @callback
    def _on_device_state_changed(self, device: PetlibroDevice) -> None:
        """Called by PetlibroDevice when state changes."""
        self.async_set_updated_data(dict(device.state))

    async def _async_update_data(self) -> dict[str, Any]:
        """Not used — we're push-based. Return current state."""
        return dict(self.device.state)

    async def async_shutdown(self) -> None:
        """Clean up on unload."""
        await self.device.stop()
        for unsub in self._unsubscribe:
            unsub()
        self._unsubscribe.clear()
