"""Binary sensor entities for Petlibro Local."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import PetlibroEntity
from .coordinator import PetlibroCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Petlibro binary sensors."""
    coordinator: PetlibroCoordinator = entry.runtime_data
    async_add_entities([
        PetlibroOnlineSensor(coordinator),
        PetlibroFoodLevelSensor(coordinator),
        PetlibroGrainOutletSensor(coordinator),
    ])


class PetlibroOnlineSensor(PetlibroEntity, BinarySensorEntity):
    _attr_name = "Online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return f"{self._device.serial}_online"

    @property
    def is_on(self) -> bool:
        return self._device.online

    @property
    def available(self) -> bool:
        return True  # Always available — shows connectivity state


class PetlibroFoodLevelSensor(PetlibroEntity, BinarySensorEntity):
    _attr_name = "Food Level OK"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:food-drumstick"

    @property
    def unique_id(self) -> str:
        return f"{self._device.serial}_food_level"

    @property
    def is_on(self) -> bool | None:
        """Problem sensor: ON when food is low."""
        surplus = self.coordinator.data.get("surplus_grain")
        if surplus is None:
            return None
        return not surplus  # surplus_grain=True means food OK, invert for problem sensor


class PetlibroGrainOutletSensor(PetlibroEntity, BinarySensorEntity):
    _attr_name = "Grain Outlet Blocked"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def unique_id(self) -> str:
        return f"{self._device.serial}_grain_outlet"

    @property
    def is_on(self) -> bool | None:
        """Problem sensor: ON when outlet is blocked."""
        state = self.coordinator.data.get("grain_outlet_state")
        if state is None:
            return None
        return not state  # grain_outlet_state=True means not blocked
