"""The Petlibro Local integration."""

from __future__ import annotations

import datetime
import logging
import time

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, PLATFORMS
from .coordinator import PetlibroCoordinator
from .protocol.codec import timestamp_now_ms

_LOGGER = logging.getLogger(__name__)

PetlibroConfigEntry = ConfigEntry


async def async_setup_entry(hass: HomeAssistant, entry: PetlibroConfigEntry) -> bool:
    """Set up Petlibro Local from a config entry."""
    coordinator = PetlibroCoordinator(hass, entry)
    await coordinator.async_setup()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(coordinator.async_shutdown)

    # Register services (once per integration, not per entry)
    if not hass.services.has_service(DOMAIN, "manual_feed"):
        _register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: PetlibroConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _get_coordinator(hass: HomeAssistant, call: ServiceCall) -> PetlibroCoordinator:
    """Get coordinator for the target device in a service call."""
    device_ids = call.data.get("device_id", [])
    if not device_ids:
        # Fall back to first entry
        for entry_id, entry_data in hass.data.get(DOMAIN, {}).items():
            if hasattr(entry_data, "runtime_data"):
                return entry_data.runtime_data
        raise ValueError("No Petlibro device found")

    dev_reg = dr.async_get(hass)
    device_id = device_ids[0] if isinstance(device_ids, list) else device_ids
    device = dev_reg.async_get(device_id)
    if not device:
        raise ValueError(f"Device {device_id} not found")

    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and entry.domain == DOMAIN:
            return entry.runtime_data

    raise ValueError(f"No Petlibro entry for device {device_id}")


def _register_services(hass: HomeAssistant) -> None:
    """Register custom services."""

    async def handle_manual_feed(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call)
        portions = call.data.get("portions", 1)
        await coordinator.device.manual_feed(portions=portions)

    async def handle_set_feeding_plan(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call)
        plan_id = call.data["plan_id"]
        time_val = call.data["time"]
        portions = call.data["portions"]
        days = call.data.get("days", [])
        enable_audio = call.data.get("enable_audio", True)

        # Convert time to UTC HH:MM
        if isinstance(time_val, str):
            h, m = map(int, time_val.split(":"))
        else:
            h, m = time_val.hour, time_val.minute

        local_dt = datetime.datetime.combine(
            datetime.date.today(),
            datetime.time(h, m),
            tzinfo=datetime.datetime.now().astimezone().tzinfo,
        )
        utc_dt = local_dt.astimezone(datetime.timezone.utc)
        execution_time = f"{utc_dt.hour:02}:{utc_dt.minute:02}"

        # Build repeat_day array
        if days:
            repeat_day = [int(d) for d in days]
        else:
            repeat_day = [1, 2, 3, 4, 5, 6, 7]
        repeat_day.extend([0] * (7 - len(repeat_day)))

        plan = {
            "planId": plan_id,
            "executionTime": execution_time,
            "repeatDay": repeat_day,
            "enableAudio": enable_audio,
            "audioTimes": 3,
            "grainNum": portions,
            "syncTime": timestamp_now_ms(),
        }

        # Store locally
        existing = [p for p in coordinator.device.feeding_plans if p.get("planId") != plan_id]
        existing.append(plan)
        coordinator.device.feeding_plans = existing

        # Send to device
        await coordinator.device.set_feeding_plans(existing)

    async def handle_clear_feeding_plans(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call)
        coordinator.device.feeding_plans = []
        await coordinator.device.set_feeding_plans([])

    hass.services.async_register(DOMAIN, "manual_feed", handle_manual_feed)
    hass.services.async_register(DOMAIN, "set_feeding_plan", handle_set_feeding_plan)
    hass.services.async_register(DOMAIN, "clear_feeding_plans", handle_clear_feeding_plans)
