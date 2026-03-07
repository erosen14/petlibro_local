"""Sensor entities for Petlibro Local."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import PetlibroEntity
from .coordinator import PetlibroCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Petlibro sensors."""
    coordinator: PetlibroCoordinator = entry.runtime_data
    async_add_entities([
        PetlibroBatterySensor(coordinator),
        PetlibroWifiRssiSensor(coordinator),
        PetlibroMotorStateSensor(coordinator),
        PetlibroVolumeSensor(coordinator),
        PetlibroGrainOutputTypeSensor(coordinator),
        PetlibroActualGrainSensor(coordinator),
        PetlibroExpectedGrainSensor(coordinator),
        PetlibroGrainExecStepSensor(coordinator),
        PetlibroErrorCodeSensor(coordinator),
        PetlibroFirmwareVersionSensor(coordinator),
        PetlibroPowerModeSensor(coordinator),
        PetlibroPowerTypeSensor(coordinator),
        PetlibroSdCardCapacitySensor(coordinator),
        PetlibroSdCardUsedSensor(coordinator),
    ])


class PetlibroBatterySensor(PetlibroEntity, SensorEntity):
    _attr_name = "Battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    @property
    def unique_id(self) -> str:
        return f"{self._device.serial}_battery"

    @property
    def native_value(self):
        return self.coordinator.data.get("battery_percent")


class PetlibroWifiRssiSensor(PetlibroEntity, SensorEntity):
    _attr_name = "WiFi Signal"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return f"{self._device.serial}_wifi_rssi"

    @property
    def native_value(self):
        return self.coordinator.data.get("wifi_rssi")


class PetlibroMotorStateSensor(PetlibroEntity, SensorEntity):
    _attr_name = "Motor State"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return f"{self._device.serial}_motor_state"

    @property
    def native_value(self):
        return self.coordinator.data.get("motor_state")


class PetlibroVolumeSensor(PetlibroEntity, SensorEntity):
    _attr_name = "Volume"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return f"{self._device.serial}_volume"

    @property
    def native_value(self):
        return self.coordinator.data.get("volume")


class PetlibroGrainOutputTypeSensor(PetlibroEntity, SensorEntity):
    _attr_name = "Last Feed Type"

    @property
    def unique_id(self) -> str:
        return f"{self._device.serial}_grain_output_type"

    @property
    def native_value(self):
        val = self.coordinator.data.get("grain_output_type")
        if val is None:
            return None
        type_map = {0: "idle", 1: "scheduled", 2: "manual_app", 3: "manual_button"}
        return type_map.get(val, str(val))


class PetlibroActualGrainSensor(PetlibroEntity, SensorEntity):
    _attr_name = "Last Feed Portions"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        return f"{self._device.serial}_actual_grain"

    @property
    def native_value(self):
        return self.coordinator.data.get("actual_grain_num")


class PetlibroExpectedGrainSensor(PetlibroEntity, SensorEntity):
    _attr_name = "Expected Feed Portions"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        return f"{self._device.serial}_expected_grain"

    @property
    def native_value(self):
        return self.coordinator.data.get("expected_grain_num")


class PetlibroGrainExecStepSensor(PetlibroEntity, SensorEntity):
    _attr_name = "Feeding Status"

    @property
    def unique_id(self) -> str:
        return f"{self._device.serial}_grain_exec_step"

    @property
    def native_value(self):
        val = self.coordinator.data.get("grain_exec_step")
        if val is None:
            return None
        step_map = {"GRAIN_START": "dispensing", "GRAIN_END": "done", "GRAIN_BLOCKING": "blocked"}
        return step_map.get(val, str(val))


class PetlibroErrorCodeSensor(PetlibroEntity, SensorEntity):
    _attr_name = "Error Code"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return f"{self._device.serial}_error_code"

    @property
    def native_value(self):
        return self.coordinator.data.get("error_code")


class PetlibroFirmwareVersionSensor(PetlibroEntity, SensorEntity):
    _attr_name = "Firmware Version"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return f"{self._device.serial}_firmware"

    @property
    def native_value(self):
        return self._device.device_info.get("software_version")


class PetlibroPowerModeSensor(PetlibroEntity, SensorEntity):
    _attr_name = "Power Mode"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return f"{self._device.serial}_power_mode"

    @property
    def native_value(self):
        val = self.coordinator.data.get("power_mode")
        if val is None:
            return None
        return {1: "USB", 2: "Battery"}.get(val, str(val))


class PetlibroPowerTypeSensor(PetlibroEntity, SensorEntity):
    _attr_name = "Power Type"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return f"{self._device.serial}_power_type"

    @property
    def native_value(self):
        val = self.coordinator.data.get("power_type")
        if val is None:
            return None
        return {0: "Invalid", 1: "USB Only", 2: "Battery Only", 3: "USB + Battery"}.get(val, str(val))


class PetlibroSdCardCapacitySensor(PetlibroEntity, SensorEntity):
    _attr_name = "SD Card Total"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return f"{self._device.serial}_sd_total"

    @property
    def native_value(self):
        return self.coordinator.data.get("sd_card_total_capacity")


class PetlibroSdCardUsedSensor(PetlibroEntity, SensorEntity):
    _attr_name = "SD Card Used"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return f"{self._device.serial}_sd_used"

    @property
    def native_value(self):
        return self.coordinator.data.get("sd_card_used_capacity")
