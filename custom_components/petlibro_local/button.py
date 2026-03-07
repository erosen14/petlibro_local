"""Button entities for Petlibro Local."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import PetlibroEntity
from .coordinator import PetlibroCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Petlibro buttons."""
    coordinator: PetlibroCoordinator = entry.runtime_data
    async_add_entities([
        PetlibroDispenseButton(coordinator),
        PetlibroRebootButton(coordinator),
        PetlibroFactoryResetButton(coordinator),
    ])


class PetlibroDispenseButton(PetlibroEntity, ButtonEntity):
    _attr_name = "Dispense Food"
    _attr_icon = "mdi:food"

    @property
    def unique_id(self) -> str:
        return f"{self._device.serial}_dispense"

    async def async_press(self) -> None:
        await self._device.manual_feed(portions=1)


class PetlibroRebootButton(PetlibroEntity, ButtonEntity):
    _attr_name = "Reboot"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:restart"

    @property
    def unique_id(self) -> str:
        return f"{self._device.serial}_reboot"

    async def async_press(self) -> None:
        await self._device.reboot()


class PetlibroFactoryResetButton(PetlibroEntity, ButtonEntity):
    _attr_name = "Factory Reset"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:factory"

    @property
    def unique_id(self) -> str:
        return f"{self._device.serial}_factory_reset"

    async def async_press(self) -> None:
        await self._device.factory_restore()
