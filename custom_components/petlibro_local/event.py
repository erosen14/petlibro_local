"""Event entities for Petlibro Local."""

from __future__ import annotations

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import PetlibroEntity
from .coordinator import PetlibroCoordinator


EVENT_FEEDING_COMPLETE = "feeding_complete"
EVENT_FEEDING_STARTED = "feeding_started"
EVENT_FEEDING_BLOCKED = "feeding_blocked"
EVENT_ERROR = "error"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Petlibro event entities."""
    coordinator: PetlibroCoordinator = entry.runtime_data
    async_add_entities([
        PetlibroFeedingEvent(coordinator),
        PetlibroErrorEvent(coordinator),
    ])


class PetlibroFeedingEvent(PetlibroEntity, EventEntity):
    _attr_name = "Feeding"
    _attr_event_types = [EVENT_FEEDING_COMPLETE, EVENT_FEEDING_STARTED, EVENT_FEEDING_BLOCKED]
    _attr_icon = "mdi:food"

    def __init__(self, coordinator: PetlibroCoordinator) -> None:
        super().__init__(coordinator)
        self._last_exec_step: str | None = None

    @property
    def unique_id(self) -> str:
        return f"{self._device.serial}_feeding_event"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Check for grain output state changes and fire events."""
        exec_step = self.coordinator.data.get("grain_exec_step")

        if exec_step and exec_step != self._last_exec_step:
            if exec_step == "GRAIN_END":
                self._trigger_event(
                    EVENT_FEEDING_COMPLETE,
                    {
                        "actual_portions": self.coordinator.data.get("actual_grain_num"),
                        "expected_portions": self.coordinator.data.get("expected_grain_num"),
                        "type": self.coordinator.data.get("grain_output_type"),
                    },
                )
            elif exec_step == "GRAIN_START":
                self._trigger_event(EVENT_FEEDING_STARTED)
            elif exec_step == "GRAIN_BLOCKING":
                self._trigger_event(EVENT_FEEDING_BLOCKED)

            self._last_exec_step = exec_step

        self.async_write_ha_state()


class PetlibroErrorEvent(PetlibroEntity, EventEntity):
    _attr_name = "Error"
    _attr_event_types = [EVENT_ERROR]
    _attr_icon = "mdi:alert-circle"

    def __init__(self, coordinator: PetlibroCoordinator) -> None:
        super().__init__(coordinator)
        self._last_error: str | None = None

    @property
    def unique_id(self) -> str:
        return f"{self._device.serial}_error_event"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Check for new errors and fire events."""
        error = self.coordinator.data.get("error_code")

        if error and error != self._last_error:
            self._trigger_event(EVENT_ERROR, {"error_code": error})
            self._last_error = error

        self.async_write_ha_state()
