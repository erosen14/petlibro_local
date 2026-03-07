"""Config flow for Petlibro Local integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import network

from .const import (
    CONF_MQTT_HOST,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_PORT,
    CONF_MQTT_USERNAME,
    CONF_SERIAL,
    DEVICE_PRODUCT_ID,
    DOMAIN,
    MQTT_PORT,
)
from .credential_sniffer import CredentialSnifferError, sniff_mqtt_credentials
from .known_credentials import get_credentials, is_model_known

_LOGGER = logging.getLogger(__name__)


class PetlibroLocalConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Petlibro Local."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._serial: str = ""
        self._mqtt_username: str = ""
        self._mqtt_password: str = ""
        self._mqtt_host: str = ""
        self._mqtt_port: int = MQTT_PORT

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step — enter serial number."""
        errors: dict[str, str] = {}

        if user_input is not None:
            serial = user_input["serial"].strip().upper()
            model = user_input.get("model", DEVICE_PRODUCT_ID).strip().upper()
            self._serial = serial

            # Check if we have known credentials for this model
            creds = get_credentials(model)
            if creds:
                self._mqtt_username = creds.product_key
                self._mqtt_password = creds.product_secret
                _LOGGER.info(
                    "Using known credentials for model %s (serial %s)",
                    model, serial,
                )
                return await self.async_step_broker()

            # Unknown model — offer sniffer or manual entry
            return self.async_show_menu(
                step_id="unknown_model",
                menu_options=["auto_detect", "manual"],
                description_placeholders={"model": model},
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("serial"): str,
                    vol.Optional("model", default=DEVICE_PRODUCT_ID): str,
                }
            ),
            errors=errors,
        )

    async def async_step_unknown_model(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Menu for unknown models — auto-detect or manual."""
        return self.async_show_menu(
            step_id="unknown_model",
            menu_options=["auto_detect", "manual"],
        )

    async def async_step_auto_detect(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show DNS redirect instructions, then start sniffer."""
        if user_input is not None:
            return await self._run_sniffer(user_input.get("listen_port", MQTT_PORT))

        try:
            ha_ip = await network.async_get_source_ip(self.hass)
        except Exception:
            ha_ip = "your-ha-ip"

        return self.async_show_form(
            step_id="auto_detect",
            data_schema=vol.Schema(
                {
                    vol.Optional("listen_port", default=MQTT_PORT): int,
                }
            ),
            description_placeholders={"ha_ip": ha_ip},
        )

    async def _run_sniffer(self, port: int) -> ConfigFlowResult:
        """Run the credential sniffer and handle results."""
        errors: dict[str, str] = {}

        try:
            creds = await sniff_mqtt_credentials(
                host="0.0.0.0", port=port, timeout=120
            )
            self._serial = creds.get("client_id", self._serial)
            self._mqtt_username = creds.get("username", "")
            self._mqtt_password = creds.get("password", "")

            return await self.async_step_auto_detect_confirm()

        except CredentialSnifferError as err:
            error_str = str(err)
            if "in use" in error_str.lower() or "address already" in error_str.lower():
                errors["base"] = "sniffer_port_in_use"
            else:
                errors["base"] = "sniffer_timeout"
        except OSError as err:
            if err.errno == 48:
                errors["base"] = "sniffer_port_in_use"
            else:
                errors["base"] = "unknown"
                _LOGGER.exception("Sniffer OS error")
        except Exception:
            errors["base"] = "unknown"
            _LOGGER.exception("Unexpected sniffer error")

        try:
            ha_ip = await network.async_get_source_ip(self.hass)
        except Exception:
            ha_ip = "your-ha-ip"

        return self.async_show_form(
            step_id="auto_detect",
            data_schema=vol.Schema(
                {
                    vol.Optional("listen_port", default=port): int,
                }
            ),
            errors=errors,
            description_placeholders={"ha_ip": ha_ip},
        )

    async def async_step_auto_detect_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show captured credentials for confirmation."""
        if user_input is not None:
            self._serial = user_input["serial"]
            self._mqtt_username = user_input["mqtt_username"]
            self._mqtt_password = user_input["mqtt_password"]
            return await self.async_step_broker()

        return self.async_show_form(
            step_id="auto_detect_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required("serial", default=self._serial): str,
                    vol.Required("mqtt_username", default=self._mqtt_username): str,
                    vol.Required("mqtt_password", default=self._mqtt_password): str,
                }
            ),
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual credential entry."""
        if user_input is not None:
            self._serial = user_input.get("serial", self._serial)
            self._mqtt_username = user_input["mqtt_username"]
            self._mqtt_password = user_input["mqtt_password"]
            return await self.async_step_broker()

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required("serial", default=self._serial): str,
                    vol.Required("mqtt_username"): str,
                    vol.Required("mqtt_password"): str,
                }
            ),
        )

    async def async_step_broker(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure the MQTT broker connection."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._mqtt_host = user_input["mqtt_host"]
            self._mqtt_port = user_input["mqtt_port"]

            connected = await self._test_mqtt_connection()
            if connected:
                await self.async_set_unique_id(self._serial)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Petlibro {self._serial[-6:]}",
                    data={
                        CONF_SERIAL: self._serial,
                        CONF_MQTT_USERNAME: self._mqtt_username,
                        CONF_MQTT_PASSWORD: self._mqtt_password,
                        CONF_MQTT_HOST: self._mqtt_host,
                        CONF_MQTT_PORT: self._mqtt_port,
                    },
                )
            errors["base"] = "cannot_connect"

        default_host = self._mqtt_host
        if not default_host:
            try:
                default_host = await network.async_get_source_ip(self.hass)
            except Exception:
                default_host = "localhost"

        return self.async_show_form(
            step_id="broker",
            data_schema=vol.Schema(
                {
                    vol.Required("mqtt_host", default=default_host): str,
                    vol.Required("mqtt_port", default=MQTT_PORT): int,
                }
            ),
            errors=errors,
        )

    async def _test_mqtt_connection(self) -> bool:
        """Test connectivity to the MQTT broker."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._mqtt_host, self._mqtt_port),
                timeout=5,
            )
            writer.close()
            await writer.wait_closed()
            return True
        except Exception:
            _LOGGER.debug(
                "Cannot connect to MQTT broker at %s:%d",
                self._mqtt_host,
                self._mqtt_port,
            )
            return False
