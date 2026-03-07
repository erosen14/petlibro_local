"""Config flow for Petlibro Local integration."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.components import mqtt

from .const import (
    CONF_MQTT_USERNAME,
    CONF_MQTT_PASSWORD,
    CONF_SERIAL,
    DOMAIN,
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


async def _ensure_mosquitto_login(username: str, password: str) -> bool:
    """Add feeder credentials to Mosquitto add-on logins if missing.

    Uses the Supervisor API. Returns True if login was added or already exists.
    Returns False if Supervisor is unavailable (non-HA OS installs).
    """
    options = await _get_mosquitto_options()
    if options is None:
        return False

    logins: list[dict] = options.get("logins", [])

    # Check if login already exists
    for login in logins:
        if login.get("username") == username:
            _LOGGER.debug("Mosquitto login for %s already exists", username)
            return True

    # Add the new login
    logins.append({"username": username, "password": password})
    options["logins"] = logins

    if not await _set_mosquitto_options(options):
        _LOGGER.warning("Failed to set Mosquitto options")
        return False

    if not await _restart_mosquitto():
        _LOGGER.warning("Failed to restart Mosquitto")
        return False

    _LOGGER.info("Added Mosquitto login for %s and restarted", username)
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

        # Add credentials to Mosquitto and restart it
        await _ensure_mosquitto_login(self._mqtt_username, self._mqtt_password)

        # If _ensure_mosquitto_login already restarted, we're good.
        # If it failed (non-Supervisor), start Mosquitto manually.
        options = await _get_mosquitto_options()
        if options is None:
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
