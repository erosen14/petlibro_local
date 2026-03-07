"""MQTT topic construction for Petlibro devices."""

from __future__ import annotations

from ..const import DEVICE_PRODUCT_ID


class PetlibroTopics:
    """Build MQTT topics for a specific device."""

    def __init__(self, serial: str, product_id: str = DEVICE_PRODUCT_ID) -> None:
        self._base = f"dl/{product_id}/{serial}/device"

    @property
    def subscribe_all(self) -> str:
        """Wildcard topic to receive all messages from the device."""
        return f"{self._base}/+/post"

    # Device → Server (we subscribe to these)
    @property
    def heart_post(self) -> str:
        return f"{self._base}/heart/post"

    @property
    def ntp_post(self) -> str:
        return f"{self._base}/ntp/post"

    @property
    def ota_post(self) -> str:
        return f"{self._base}/ota/post"

    @property
    def config_post(self) -> str:
        return f"{self._base}/config/post"

    @property
    def event_post(self) -> str:
        return f"{self._base}/event/post"

    @property
    def service_post(self) -> str:
        return f"{self._base}/service/post"

    @property
    def system_post(self) -> str:
        return f"{self._base}/system/post"

    # Server → Device (we publish to these)
    @property
    def ntp_sub(self) -> str:
        return f"{self._base}/ntp/sub"

    @property
    def ota_sub(self) -> str:
        return f"{self._base}/ota/sub"

    @property
    def config_sub(self) -> str:
        return f"{self._base}/config/sub"

    @property
    def event_sub(self) -> str:
        return f"{self._base}/event/sub"

    @property
    def service_sub(self) -> str:
        return f"{self._base}/service/sub"

    @property
    def system_sub(self) -> str:
        return f"{self._base}/system/sub"

    @property
    def broadcast_sub(self) -> str:
        return f"{self._base}/broadcast/sub"
