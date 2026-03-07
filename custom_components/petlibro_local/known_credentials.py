"""Known MQTT credentials for Petlibro devices.

The DL_PRODUCT_KEY and DL_PRODUCT_SECRET are hard-coded in the device firmware
and are identical across all devices of the same model (confirmed by Kaspersky
Securelist research). Only the DL_DEVICE_ID is unique per device.

When a user's model/firmware is in this map, setup requires only the device
serial number — no sniffing needed. If the model isn't here, the credential
sniffer can capture them automatically.

To contribute: if you have a Petlibro device not listed here, use the
auto-detect setup flow to capture your credentials, then submit a PR
adding your model to this map.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceCredentials:
    """MQTT credentials for a Petlibro device model."""

    product_key: str
    product_secret: str
    mqtt_protocol: str  # "MQIsdp" (v3.1) or "MQTT" (v3.1.1)
    keepalive: int


# Map of model_id -> DeviceCredentials
# These are shared across ALL devices of the same model
KNOWN_CREDENTIALS: dict[str, DeviceCredentials] = {
    "PLAF203": DeviceCredentials(
        product_key="90EGT61TO38V1978",
        product_secret="4NWD5SBFBBNSKS6C70YFVJ8HZH87IO5E",
        mqtt_protocol="MQIsdp",
        keepalive=90,
    ),
}


def get_credentials(model: str) -> DeviceCredentials | None:
    """Look up known credentials for a device model."""
    return KNOWN_CREDENTIALS.get(model.upper())


def is_model_known(model: str) -> bool:
    """Check if credentials are known for this model."""
    return model.upper() in KNOWN_CREDENTIALS


def reverse_lookup_model(product_key: str) -> str | None:
    """Find the model for a given product_key (from sniffed credentials)."""
    for model, creds in KNOWN_CREDENTIALS.items():
        if creds.product_key == product_key:
            return model
    return None
