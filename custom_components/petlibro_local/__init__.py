"""The Petlibro Local integration."""

from __future__ import annotations

import datetime
import logging
import os
import time

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_CORE_CONFIG_UPDATE
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_FEEDING_PLANS,
    DOMAIN,
    PLAN_LOCAL_TIME,
    PLAN_RESYNC_INTERVAL_MIN,
    PLATFORMS,
)
from .coordinator import PetlibroCoordinator
from .protocol.codec import local_time_to_utc, timestamp_now_ms, utc_time_to_local

_LOGGER = logging.getLogger(__name__)

PetlibroConfigEntry = ConfigEntry


async def async_setup_entry(hass: HomeAssistant, entry: PetlibroConfigEntry) -> bool:
    """Set up Petlibro Local from a config entry."""
    coordinator = PetlibroCoordinator(hass, entry)
    await coordinator.async_setup()

    entry.runtime_data = coordinator

    # Restore persisted feeding plans
    stored_plans = entry.options.get(CONF_FEEDING_PLANS, [])
    if stored_plans:
        coordinator.device.feeding_plans = list(stored_plans)
        _LOGGER.info(
            "Restored %d feeding plan(s) for %s",
            len(stored_plans),
            coordinator.device.serial,
        )
        # Plans are stored with a UTC executionTime; make sure it still matches
        # the local time the user asked for (DST may have changed since).
        await _resync_plans_for_utc_offset(hass, coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(coordinator.async_shutdown)

    # Keep executionTime (UTC) in step with the local schedule across DST and
    # timezone changes: check periodically and whenever HA core config changes.
    async def _periodic_resync(_now: datetime.datetime) -> None:
        await _resync_plans_for_utc_offset(hass, coordinator)

    @callback
    def _core_config_updated(_event: Event) -> None:
        hass.async_create_task(_resync_plans_for_utc_offset(hass, coordinator))

    entry.async_on_unload(
        async_track_time_interval(
            hass,
            _periodic_resync,
            datetime.timedelta(minutes=PLAN_RESYNC_INTERVAL_MIN),
        )
    )
    entry.async_on_unload(
        hass.bus.async_listen(EVENT_CORE_CONFIG_UPDATE, _core_config_updated)
    )

    # Register services (once per integration, not per entry)
    if not hass.services.has_service(DOMAIN, "manual_feed"):
        _register_services(hass)

    # Register static path + auto-register Lovelace resource for the card (once)
    frontend_key = f"{DOMAIN}_frontend_registered"
    if frontend_key not in hass.data:
        hass.data[frontend_key] = True
        card_js = os.path.join(os.path.dirname(__file__), "www", "petlibro-feeding-card.js")
        card_url = f"/{DOMAIN}/petlibro-feeding-card.js"

        # Serve the JS file
        try:
            from homeassistant.components.http import StaticPathConfig
            await hass.http.async_register_static_paths([
                StaticPathConfig(card_url, card_js, False)
            ])
        except (ImportError, AttributeError):
            hass.http.register_static_path(card_url, card_js, cache_headers=False)

        # Auto-register as a Lovelace resource so the card is available
        # in the card picker without manual resource setup
        await _ensure_card_resource(hass, card_url)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: PetlibroConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _get_coordinator(hass: HomeAssistant, call: ServiceCall) -> PetlibroCoordinator:
    """Get coordinator for the target device in a service call."""
    device_ids = call.data.get("device_id", [])
    if not device_ids:
        # Fall back to first petlibro config entry
        for entry in hass.config_entries.async_entries(DOMAIN):
            if hasattr(entry, "runtime_data") and entry.runtime_data:
                return entry.runtime_data
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

        # Convert time to UTC HH:MM, keeping the local time so the UTC value
        # can be recomputed after a DST / timezone change.
        if isinstance(time_val, str):
            parts = time_val.split(":")
            h, m = int(parts[0]), int(parts[1])
        else:
            h, m = time_val.hour, time_val.minute

        local_time = f"{h:02}:{m:02}"
        execution_time = local_time_to_utc(local_time)

        # Build repeat_day array
        if days:
            repeat_day = [int(d) for d in days]
        else:
            repeat_day = [1, 2, 3, 4, 5, 6, 7]
        repeat_day.extend([0] * (7 - len(repeat_day)))

        plan = {
            "planId": plan_id,
            "executionTime": execution_time,
            PLAN_LOCAL_TIME: local_time,
            "repeatDay": repeat_day,
            "enableAudio": enable_audio,
            "audioTimes": 3,
            "grainNum": portions,
            "syncTime": timestamp_now_ms(),
        }

        # Store locally
        existing = [p for p in coordinator.device.feeding_plans if p.get("planId") != plan_id]
        existing.append(plan)
        existing.sort(key=lambda p: p.get("planId", 0))
        coordinator.device.feeding_plans = existing

        # Persist to config entry
        await _persist_feeding_plans(hass, coordinator, existing)

        # Send to device
        await coordinator.device.set_feeding_plans(existing)

        # Notify sensor of plan change
        coordinator.device.state["_feeding_plans_version"] = timestamp_now_ms()
        coordinator.device._notify_state_changed()

    async def handle_clear_feeding_plans(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call)
        coordinator.device.feeding_plans = []
        await coordinator.device.set_feeding_plans([])

        # Persist empty
        await _persist_feeding_plans(hass, coordinator, [])

        # Notify sensor of plan change
        coordinator.device.state["_feeding_plans_version"] = timestamp_now_ms()
        coordinator.device._notify_state_changed()

    async def handle_remove_feeding_plan(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call)
        plan_id = call.data["plan_id"]
        existing = [p for p in coordinator.device.feeding_plans if p.get("planId") != plan_id]
        coordinator.device.feeding_plans = existing

        # Persist
        await _persist_feeding_plans(hass, coordinator, existing)

        # Send to device
        await coordinator.device.set_feeding_plans(existing)

        # Notify sensor
        coordinator.device.state["_feeding_plans_version"] = timestamp_now_ms()
        coordinator.device._notify_state_changed()

    hass.services.async_register(DOMAIN, "manual_feed", handle_manual_feed)
    hass.services.async_register(DOMAIN, "set_feeding_plan", handle_set_feeding_plan)
    hass.services.async_register(DOMAIN, "clear_feeding_plans", handle_clear_feeding_plans)
    hass.services.async_register(DOMAIN, "remove_feeding_plan", handle_remove_feeding_plan)


async def _ensure_card_resource(hass: HomeAssistant, url: str) -> None:
    """Auto-register the feeding card as a Lovelace dashboard resource.

    Uses HA's lovelace ResourceStorageCollection so the card appears
    in the card picker immediately — no manual resource setup needed.
    """
    try:
        lovelace_data = hass.data.get("lovelace")
        if lovelace_data is None:
            return

        # Support both dict and object access across HA versions
        resources = getattr(lovelace_data, "resources", None)
        if resources is None and isinstance(lovelace_data, dict):
            resources = lovelace_data.get("resources")

        if resources is None:
            return

        # Already registered?
        for item in resources.async_items():
            if item.get("url") == url:
                return

        await resources.async_create_item({"res_type": "module", "url": url})
        _LOGGER.info("Auto-registered Petlibro feeding card as Lovelace resource")
    except Exception:
        _LOGGER.debug(
            "Could not auto-register card resource — "
            "add manually: Settings > Dashboards > Resources > %s",
            url,
        )


async def _resync_plans_for_utc_offset(
    hass: HomeAssistant, coordinator: PetlibroCoordinator
) -> None:
    """Recompute executionTime (UTC) from each plan's local time and re-push.

    The feeder executes plans by UTC time, so after a DST or timezone change
    the stored UTC values no longer match the local schedule. Plans saved
    before localTime existed are migrated by deriving it from executionTime
    using the current offset.
    """
    plans = coordinator.device.feeding_plans
    if not plans:
        return

    updated: list[dict] = []
    changed = False  # stored plans need persisting
    push = False  # device needs the new executionTime
    for plan in plans:
        plan = dict(plan)
        execution_time = plan.get("executionTime")
        if not execution_time:
            updated.append(plan)
            continue
        try:
            local_time = plan.get(PLAN_LOCAL_TIME)
            if not local_time:
                plan[PLAN_LOCAL_TIME] = utc_time_to_local(execution_time)
                changed = True
            else:
                new_execution_time = local_time_to_utc(local_time)
                if new_execution_time != execution_time:
                    _LOGGER.info(
                        "Plan %s for %s: local %s now maps to %s UTC (was %s), re-syncing",
                        plan.get("planId"),
                        coordinator.device.serial,
                        local_time,
                        new_execution_time,
                        execution_time,
                    )
                    plan["executionTime"] = new_execution_time
                    plan["syncTime"] = timestamp_now_ms()
                    changed = True
                    push = True
        except (ValueError, AttributeError):
            _LOGGER.warning(
                "Plan %s for %s has an invalid time, leaving it unchanged",
                plan.get("planId"),
                coordinator.device.serial,
            )
        updated.append(plan)

    if not changed:
        return

    coordinator.device.feeding_plans = updated
    await _persist_feeding_plans(hass, coordinator, updated)
    if push:
        await coordinator.device.set_feeding_plans(updated)
        coordinator.device.state["_feeding_plans_version"] = timestamp_now_ms()
        coordinator.device._notify_state_changed()


async def _persist_feeding_plans(
    hass: HomeAssistant,
    coordinator: PetlibroCoordinator,
    plans: list[dict],
) -> None:
    """Persist feeding plans to config entry options."""
    entry = coordinator.entry
    new_options = dict(entry.options)
    new_options[CONF_FEEDING_PLANS] = plans
    hass.config_entries.async_update_entry(entry, options=new_options)
