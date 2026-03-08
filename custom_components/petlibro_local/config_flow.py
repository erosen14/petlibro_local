"""Config flow for Petlibro Local integration."""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithConfigEntry,
)
from homeassistant.components import mqtt

from .const import (
    CONF_FEEDING_PLANS,
    CONF_MQTT_USERNAME,
    CONF_MQTT_PASSWORD,
    CONF_SERIAL,
    DOMAIN,
    MAX_FEEDING_PLANS,
)
from .credential_sniffer import sniff_mqtt_credentials, CredentialSnifferError

_LOGGER = logging.getLogger(__name__)

# Topic pattern: dl/{model}/{serial}/device/heart/post
DISCOVERY_TOPIC = "dl/+/+/device/heart/post"
DISCOVERY_TIMEOUT = 60
SNIFFER_TIMEOUT = 120

SUPERVISOR_URL = "http://supervisor"
MOSQUITTO_SLUG = "core_mosquitto"


async def _supervisor_api(method: str, path: str, json_data: dict | None = None) -> dict | None:
    """Call a Supervisor API endpoint. Returns response JSON or None."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None

    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with aiohttp.ClientSession() as session:
            if method == "GET":
                async with session.get(f"{SUPERVISOR_URL}{path}", headers=headers) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.json()
            else:
                async with session.post(
                    f"{SUPERVISOR_URL}{path}",
                    headers=headers,
                    json=json_data or {},
                ) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.json()
    except Exception:
        _LOGGER.debug("Supervisor API call failed: %s %s", method, path, exc_info=True)
        return None


async def _get_mosquitto_options() -> dict | None:
    """Read current Mosquitto add-on options."""
    data = await _supervisor_api("GET", f"/addons/{MOSQUITTO_SLUG}/info")
    if data:
        return data.get("data", {}).get("options", {})
    return None


async def _set_mosquitto_options(options: dict) -> bool:
    """Write Mosquitto add-on options."""
    result = await _supervisor_api("POST", f"/addons/{MOSQUITTO_SLUG}/options", {"options": options})
    return result is not None


async def _stop_mosquitto() -> bool:
    """Stop the Mosquitto add-on."""
    result = await _supervisor_api("POST", f"/addons/{MOSQUITTO_SLUG}/stop")
    ok = result is not None
    if ok:
        _LOGGER.info("Stopped Mosquitto add-on")
        await asyncio.sleep(2)  # Let it fully stop
    return ok


async def _start_mosquitto() -> bool:
    """Start the Mosquitto add-on."""
    result = await _supervisor_api("POST", f"/addons/{MOSQUITTO_SLUG}/start")
    ok = result is not None
    if ok:
        _LOGGER.info("Started Mosquitto add-on")
    return ok


async def _restart_mosquitto() -> bool:
    """Restart the Mosquitto add-on."""
    result = await _supervisor_api("POST", f"/addons/{MOSQUITTO_SLUG}/restart")
    ok = result is not None
    if ok:
        _LOGGER.info("Restarted Mosquitto add-on")
    return ok


async def _add_mosquitto_login(username: str, password: str) -> bool:
    """Add feeder credentials to Mosquitto add-on logins if missing.

    Only writes the config — does NOT restart Mosquitto.
    Caller is responsible for restarting/starting Mosquitto afterward.
    Returns True if login was added or already exists.
    """
    options = await _get_mosquitto_options()
    if options is None:
        return False

    logins: list[dict] = options.get("logins", [])

    for login in logins:
        if login.get("username") == username:
            _LOGGER.debug("Mosquitto login for %s already exists", username)
            return True

    logins.append({"username": username, "password": password})
    options["logins"] = logins

    if not await _set_mosquitto_options(options):
        _LOGGER.warning("Failed to set Mosquitto options")
        return False

    _LOGGER.info("Added Mosquitto login for %s", username)
    return True


async def _ensure_mosquitto_login(username: str, password: str) -> bool:
    """Add login and restart Mosquitto. Use when Mosquitto is already running."""
    if not await _add_mosquitto_login(username, password):
        return False
    await _restart_mosquitto()
    return True


async def _read_mosquitto_credentials() -> tuple[str, str]:
    """Read feeder credentials from Mosquitto add-on logins.

    Returns (username, password) for the first non-HA login, or ("", "").
    """
    options = await _get_mosquitto_options()
    if options is None:
        return ("", "")

    ha_usernames = {"homeassistant", "addons"}
    for login in options.get("logins", []):
        username = login.get("username", "")
        if username and username not in ha_usernames:
            return (username, login.get("password", ""))

    return ("", "")


class PetlibroLocalConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Petlibro Local."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> PetlibroOptionsFlow:
        """Create the options flow."""
        return PetlibroOptionsFlow(config_entry)

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._serial: str = ""
        self._mqtt_username: str = ""
        self._mqtt_password: str = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step — choose setup method."""
        has_mqtt = await mqtt.async_wait_for_mqtt_client(self.hass)

        if has_mqtt:
            return self.async_show_menu(
                step_id="user",
                menu_options=["auto_detect", "manual"],
            )

        # No MQTT integration — go straight to manual
        return await self.async_step_manual()

    async def async_step_auto_detect(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Auto-detect: first try MQTT subscription, then fall back to sniffer."""
        if user_input is not None:
            # First, try discovering via existing MQTT broker (feeder already connected)
            result = await self._try_mqtt_discovery()
            if result is not None:
                return result

            # Feeder not found on broker — try the sniffer approach
            return await self._try_sniffer_discovery()

        return self.async_show_form(
            step_id="auto_detect",
            data_schema=vol.Schema({}),
        )

    async def _try_mqtt_discovery(self) -> ConfigFlowResult | None:
        """Try to discover a feeder on the existing MQTT broker.

        Returns a ConfigFlowResult if found, None if no feeder detected.
        """
        discovered: dict[str, str] | None = None
        event = asyncio.Event()

        def _on_message(msg) -> None:
            nonlocal discovered
            parts = msg.topic.split("/")
            if len(parts) >= 3:
                discovered = {"serial": parts[2].upper()}
                event.set()

        try:
            unsub = await mqtt.async_subscribe(
                self.hass, DISCOVERY_TOPIC, _on_message, qos=0
            )
        except Exception:
            _LOGGER.debug("MQTT subscribe failed, will try sniffer")
            return None

        try:
            # Short timeout — if feeder is already connected, heartbeat comes in <30s
            await asyncio.wait_for(event.wait(), timeout=35)
        except asyncio.TimeoutError:
            pass
        finally:
            unsub()

        if discovered is None:
            return None

        self._serial = discovered["serial"]

        # Read credentials from Mosquitto options (feeder is already connected)
        self._mqtt_username, self._mqtt_password = await _read_mosquitto_credentials()

        await self.async_set_unique_id(self._serial)
        self._abort_if_unique_id_configured()

        return await self.async_step_auto_detect_confirm()

    async def _try_sniffer_discovery(self) -> ConfigFlowResult:
        """Stop Mosquitto, run credential sniffer, capture feeder CONNECT packet.

        This captures the actual credentials from the wire — no hardcoded
        credential database needed.
        """
        # Stop Mosquitto to free port 1883
        stopped = await _stop_mosquitto()
        if not stopped:
            _LOGGER.warning("Could not stop Mosquitto — sniffer cannot bind to 1883")
            return self.async_show_form(
                step_id="auto_detect",
                data_schema=vol.Schema({}),
                errors={"base": "cannot_stop_mosquitto"},
            )

        try:
            # Run sniffer — waits for feeder to reconnect
            creds = await sniff_mqtt_credentials(
                host="0.0.0.0", port=1883, timeout=SNIFFER_TIMEOUT
            )

            self._serial = creds["client_id"].upper()
            self._mqtt_username = creds["username"]
            self._mqtt_password = creds["password"]

            _LOGGER.info(
                "Sniffer captured: serial=%s, username=%s",
                self._serial, self._mqtt_username,
            )

        except CredentialSnifferError as exc:
            _LOGGER.warning("Sniffer failed: %s", exc)
            # Restart Mosquitto before showing error
            await _start_mosquitto()
            return self.async_show_form(
                step_id="auto_detect",
                data_schema=vol.Schema({}),
                errors={"base": "no_devices_found"},
            )
        except Exception:
            _LOGGER.exception("Unexpected sniffer error")
            await _start_mosquitto()
            return self.async_show_form(
                step_id="auto_detect",
                data_schema=vol.Schema({}),
                errors={"base": "unknown"},
            )

        # Add credentials to Mosquitto config, then start it
        # (Mosquitto is currently stopped from the sniffer phase)
        await _add_mosquitto_login(self._mqtt_username, self._mqtt_password)
        await _start_mosquitto()

        await self.async_set_unique_id(self._serial)
        self._abort_if_unique_id_configured()

        return await self.async_step_auto_detect_confirm()

    async def async_step_auto_detect_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show discovered device for confirmation, then create entry."""
        if user_input is not None:
            self._serial = user_input["serial"]

            # Ensure login exists in Mosquitto
            if self._mqtt_username and self._mqtt_password:
                await _ensure_mosquitto_login(
                    self._mqtt_username, self._mqtt_password
                )

            await self.async_set_unique_id(self._serial)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"Petlibro {self._serial[-6:]}",
                data={
                    CONF_SERIAL: self._serial,
                    CONF_MQTT_USERNAME: self._mqtt_username,
                    CONF_MQTT_PASSWORD: self._mqtt_password,
                },
            )

        return self.async_show_form(
            step_id="auto_detect_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required("serial", default=self._serial): str,
                }
            ),
            description_placeholders={
                "serial": self._serial,
            },
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual serial + credential entry."""
        if user_input is not None:
            self._serial = user_input["serial"].strip().upper()
            self._mqtt_username = user_input["mqtt_username"].strip()
            self._mqtt_password = user_input["mqtt_password"].strip()

            # Auto-add login to Mosquitto
            await _ensure_mosquitto_login(
                self._mqtt_username, self._mqtt_password
            )

            await self.async_set_unique_id(self._serial)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"Petlibro {self._serial[-6:]}",
                data={
                    CONF_SERIAL: self._serial,
                    CONF_MQTT_USERNAME: self._mqtt_username,
                    CONF_MQTT_PASSWORD: self._mqtt_password,
                },
            )

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required("serial"): str,
                    vol.Required("mqtt_username"): str,
                    vol.Required("mqtt_password"): str,
                }
            ),
        )


# --- Helpers for feeding plan time conversion ---

DAY_NAMES = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}


def _utc_to_local_time(utc_time_str: str) -> str:
    """Convert UTC HH:MM to local HH:MM for display."""
    try:
        h, m = map(int, utc_time_str.split(":"))
        utc_dt = datetime.datetime.combine(
            datetime.date.today(),
            datetime.time(h, m),
            tzinfo=datetime.timezone.utc,
        )
        local_dt = utc_dt.astimezone()
        return local_dt.strftime("%-I:%M %p")
    except (ValueError, AttributeError):
        return utc_time_str


def _local_to_utc_time_str(local_time_str: str) -> str:
    """Convert local HH:MM:SS or HH:MM to UTC HH:MM string."""
    parts = local_time_str.split(":")
    h, m = int(parts[0]), int(parts[1])
    local_dt = datetime.datetime.combine(
        datetime.date.today(),
        datetime.time(h, m),
        tzinfo=datetime.datetime.now().astimezone().tzinfo,
    )
    utc_dt = local_dt.astimezone(datetime.timezone.utc)
    return f"{utc_dt.hour:02}:{utc_dt.minute:02}"


def _format_plan_summary(plan: dict) -> str:
    """Format a single plan as a human-readable summary."""
    local_time = _utc_to_local_time(plan.get("executionTime", "??:??"))
    portions = plan.get("grainNum", 1)
    repeat_day = plan.get("repeatDay", [])
    active_days = [d for d in repeat_day if d > 0]

    if not active_days or set(active_days) == {1, 2, 3, 4, 5, 6, 7}:
        days_str = "daily"
    elif set(active_days) == {1, 2, 3, 4, 5}:
        days_str = "weekdays"
    elif set(active_days) == {6, 7}:
        days_str = "weekends"
    else:
        days_str = ", ".join(DAY_NAMES.get(d, str(d)) for d in sorted(active_days))

    return f"{local_time} — {portions} portion(s), {days_str}"


class PetlibroOptionsFlow(OptionsFlowWithConfigEntry):
    """Handle options for Petlibro Local."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Main menu: show current plans and options."""
        plans: list[dict] = list(self.options.get(CONF_FEEDING_PLANS, []))
        plan_count = len(plans)

        if plan_count == 0:
            description = "No feeding plans configured."
        else:
            lines = [f"**{plan_count} feeding plan(s):**"]
            for plan in sorted(plans, key=lambda p: p.get("planId", 0)):
                slot = plan.get("planId", "?")
                lines.append(f"- Slot {slot}: {_format_plan_summary(plan)}")
            description = "\n".join(lines)

        menu_options = ["add_plan", "quick_setup"]
        if plan_count > 0:
            menu_options.append("remove_plan")
            menu_options.append("clear_plans")

        return self.async_show_menu(
            step_id="init",
            menu_options=menu_options,
            description_placeholders={"schedule_summary": description},
        )

    async def async_step_add_plan(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a feeding plan with time, portions, and days."""
        plans: list[dict] = list(self.options.get(CONF_FEEDING_PLANS, []))

        if user_input is not None:
            plan_id = user_input["plan_id"]
            time_val = user_input["time"]
            portions = user_input["portions"]
            days_input = user_input.get("days", [])
            enable_audio = user_input.get("enable_audio", True)

            # Convert local time to UTC
            execution_time = _local_to_utc_time_str(str(time_val))

            # Build repeat_day array
            if days_input:
                repeat_day = [int(d) for d in days_input]
            else:
                repeat_day = [1, 2, 3, 4, 5, 6, 7]
            repeat_day.extend([0] * (7 - len(repeat_day)))

            from .protocol.codec import timestamp_now_ms

            plan = {
                "planId": plan_id,
                "executionTime": execution_time,
                "repeatDay": repeat_day,
                "enableAudio": enable_audio,
                "audioTimes": 3,
                "grainNum": portions,
                "syncTime": timestamp_now_ms(),
            }

            # Replace or add
            plans = [p for p in plans if p.get("planId") != plan_id]
            plans.append(plan)
            plans.sort(key=lambda p: p.get("planId", 0))

            # Save and sync to device
            return await self._save_plans_and_finish(plans)

        # Find next available slot
        used_slots = {p.get("planId") for p in plans}
        next_slot = 1
        for i in range(1, MAX_FEEDING_PLANS + 1):
            if i not in used_slots:
                next_slot = i
                break

        data_schema = vol.Schema(
            {
                vol.Required("plan_id", default=next_slot): vol.All(
                    int, vol.Range(min=1, max=MAX_FEEDING_PLANS)
                ),
                vol.Required("time"): str,
                vol.Required("portions", default=1): vol.All(
                    int, vol.Range(min=1, max=20)
                ),
                vol.Optional("days", default=[]): vol.All(
                    vol.Coerce(list),
                    [vol.In(["1", "2", "3", "4", "5", "6", "7"])],
                ),
                vol.Optional("enable_audio", default=True): bool,
            }
        )

        return self.async_show_form(
            step_id="add_plan",
            data_schema=data_schema,
        )

    async def async_step_remove_plan(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove a specific plan."""
        plans: list[dict] = list(self.options.get(CONF_FEEDING_PLANS, []))

        if user_input is not None:
            plan_id = int(user_input["plan_to_remove"])
            plans = [p for p in plans if p.get("planId") != plan_id]
            return await self._save_plans_and_finish(plans)

        # Build options from current plans
        plan_options = {}
        for plan in sorted(plans, key=lambda p: p.get("planId", 0)):
            slot = plan.get("planId", 0)
            plan_options[str(slot)] = f"Slot {slot}: {_format_plan_summary(plan)}"

        if not plan_options:
            return self.async_abort(reason="no_plans")

        return self.async_show_form(
            step_id="remove_plan",
            data_schema=vol.Schema(
                {
                    vol.Required("plan_to_remove"): vol.In(plan_options),
                }
            ),
        )

    async def async_step_clear_plans(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Clear all feeding plans."""
        if user_input is not None:
            if user_input.get("confirm", False):
                return await self._save_plans_and_finish([])
            # Not confirmed — go back to menu
            return await self.async_step_init()

        return self.async_show_form(
            step_id="clear_plans",
            data_schema=vol.Schema(
                {
                    vol.Required("confirm", default=False): bool,
                }
            ),
        )

    async def async_step_quick_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Quick setup: feed every X hours with Y portions."""
        if user_input is not None:
            interval = int(user_input["interval"])
            portions = user_input["portions"]
            start_hour = int(user_input.get("start_hour", 8))
            enable_audio = user_input.get("enable_audio", True)

            from .protocol.codec import timestamp_now_ms

            plans = []
            plan_id = 1
            hour = start_hour
            while hour < 24 and plan_id <= MAX_FEEDING_PLANS:
                # Convert local hour to UTC
                execution_time = _local_to_utc_time_str(f"{hour:02}:00")

                plans.append({
                    "planId": plan_id,
                    "executionTime": execution_time,
                    "repeatDay": [1, 2, 3, 4, 5, 6, 7],
                    "enableAudio": enable_audio,
                    "audioTimes": 3,
                    "grainNum": portions,
                    "syncTime": timestamp_now_ms(),
                })
                plan_id += 1
                hour += interval

            return await self._save_plans_and_finish(plans)

        data_schema = vol.Schema(
            {
                vol.Required("interval", default="8"): vol.In(
                    {
                        "4": "Every 4 hours (6 feeds/day)",
                        "6": "Every 6 hours (3 feeds/day)",
                        "8": "Every 8 hours (2 feeds/day)",
                        "12": "Every 12 hours (2 feeds/day)",
                        "24": "Once a day",
                    }
                ),
                vol.Required("portions", default=1): vol.All(
                    int, vol.Range(min=1, max=20)
                ),
                vol.Required("start_hour", default="8"): vol.In(
                    {
                        "6": "6:00 AM",
                        "7": "7:00 AM",
                        "8": "8:00 AM",
                        "9": "9:00 AM",
                        "10": "10:00 AM",
                    }
                ),
                vol.Optional("enable_audio", default=True): bool,
            }
        )

        return self.async_show_form(
            step_id="quick_setup",
            data_schema=data_schema,
        )

    async def _save_plans_and_finish(
        self, plans: list[dict]
    ) -> ConfigFlowResult:
        """Save plans to options, sync to device, and close the flow."""
        # Sync to device if coordinator is available
        entry = self.config_entry
        if hasattr(entry, "runtime_data") and entry.runtime_data:
            coordinator = entry.runtime_data
            coordinator.device.feeding_plans = plans
            await coordinator.device.set_feeding_plans(plans)

            # Trigger sensor update
            from .protocol.codec import timestamp_now_ms

            coordinator.device.state["_feeding_plans_version"] = timestamp_now_ms()
            coordinator.device._notify_state_changed()

        return self.async_create_entry(
            title="",
            data={CONF_FEEDING_PLANS: plans},
        )
