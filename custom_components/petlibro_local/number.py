"""Number entities for Petlibro Local."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import PetlibroEntity
from .coordinator import PetlibroCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Petlibro number entities."""
    coordinator: PetlibroCoordinator = entry.runtime_data
    async_add_entities([
        PetlibroDispensePortions(coordinator),
        PetlibroVolume(coordinator),
    ])


class PetlibroDispensePortions(PetlibroEntity, NumberEntity):
    _attr_name = "Dispense Portions"
    _attr_icon = "mdi:food-variant"
    _attr_native_min_value = 1
    _attr_native_max_value = 20
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: PetlibroCoordinator) -> None:
        super().__init__(coordinator)
        self._portions = 1

    @property
    def unique_id(self) -> str:
        return f"{self._device.serial}_dispense_portions"

    @property
    def native_value(self) -> float:
        return self._portions

    async def async_set_native_value(self, value: float) -> None:
        self._portions = int(value)
        await self._device.manual_feed(portions=self._portions)


class PetlibroVolume(PetlibroEntity, NumberEntity):
    _attr_name = "Volume"
    _attr_icon = "mdi:volume-medium"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 10
    _attr_mode = NumberMode.SLIDER
    _attr_native_unit_of_measurement = "%"

    @property
    def unique_id(self) -> str:
        return f"{self._device.serial}_volume_control"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.get("volume")

    async def async_set_native_value(self, value: float) -> None:
        await self._device.set_attributes(volume=int(value))
