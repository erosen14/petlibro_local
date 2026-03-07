"""Base entity for Petlibro Local integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PetlibroCoordinator


class PetlibroEntity(CoordinatorEntity[PetlibroCoordinator]):
    """Base entity for Petlibro devices."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PetlibroCoordinator) -> None:
        super().__init__(coordinator)
        self._device = coordinator.device

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for device registry."""
        info = self._device.device_info
        return DeviceInfo(
            identifiers={(DOMAIN, self._device.serial)},
            name=self._device.name,
            manufacturer="Petlibro",
            model=info.get("product_id", "PLAF203"),
            sw_version=info.get("software_version"),
            hw_version=info.get("hardware_version"),
        )

    @property
    def available(self) -> bool:
        """Return True if device is online."""
        return self._device.online
