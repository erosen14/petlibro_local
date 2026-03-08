"""PetlibroDevice — MQTT state management and command layer.

Replaces plaf203's Client+Backend monolith. Subscribes to all device
topics, maintains consolidated state dict, handles heartbeat and NTP,
and fires callbacks on state changes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable

from .const import (
    CMD_ATTR_GET_SERVICE,
    CMD_ATTR_PUSH_EVENT,
    CMD_ATTR_SET_SERVICE,
    CMD_BINDING,
    CMD_DETECTION_EVENT,
    CMD_DEVICE_START_EVENT,
    CMD_ERROR_EVENT,
    CMD_FEEDING_PLAN_SERVICE,
    CMD_GET_CONFIG,
    CMD_GET_FEEDING_PLAN_EVENT,
    CMD_GRAIN_OUTPUT_EVENT,
    CMD_HEARTBEAT,
    CMD_MANUAL_FEEDING_SERVICE,
    CMD_NTP,
    CMD_NTP_SYNC,
    CMD_RESET,
    CODE_OK,
    HEARTBEAT_INTERVAL_SEC,
    HEARTBEAT_WATCHDOG_SEC,
    NTP_DRIFT_THRESHOLD_SEC,
)
from .protocol.codec import (
    build_attr_get,
    build_command,
    build_manual_feed,
    build_ntp_response,
    build_ntp_sync,
    build_response,
    parse_payload,
    timestamp_now_ms,
    timezone_offset_hours,
)
from .protocol.messages import normalize_payload
from .protocol.topics import PetlibroTopics

_LOGGER = logging.getLogger(__name__)

StateCallback = Callable[["PetlibroDevice"], None]


class PetlibroDevice:
    """Manages MQTT communication with a single Petlibro feeder."""

    def __init__(
        self,
        serial: str,
        mqtt_publish: Callable[[str, str], asyncio.coroutines],
        on_state_changed: StateCallback | None = None,
    ) -> None:
        self.serial = serial
        self.topics = PetlibroTopics(serial)
        self._mqtt_publish = mqtt_publish
        self._on_state_changed = on_state_changed

        # Consolidated device state
        self.state: dict[str, Any] = {}
        self.feeding_plans: list[dict[str, Any]] = []
        self.device_info: dict[str, Any] = {}

        # Online tracking
        self.online = False
        self._last_heartbeat: float = 0
        self._heartbeat_count: int | None = None
        self._heartbeat_task: asyncio.Task | None = None

    @property
    def name(self) -> str:
        return f"Petlibro {self.serial[-6:]}"

    async def start(self) -> None:
        """Start the heartbeat watchdog."""
        self._heartbeat_task = asyncio.ensure_future(self._heartbeat_watchdog())

    async def stop(self) -> None:
        """Stop background tasks."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

    async def handle_message(self, topic: str, payload_raw: str | bytes) -> None:
        """Dispatch an incoming MQTT message from the device."""
        try:
            payload = parse_payload(payload_raw)
        except (json.JSONDecodeError, ValueError):
            _LOGGER.warning("Invalid JSON from %s on %s", self.serial, topic)
            return

        cmd = payload.get("cmd")
        if not cmd:
            _LOGGER.debug("Message without cmd on %s: %s", topic, payload)
            return

        _LOGGER.debug("Device %s cmd=%s", self.serial, cmd)

        handler = self._HANDLERS.get(cmd)
        if handler:
            await handler(self, payload)
        else:
            _LOGGER.debug("Unhandled cmd %s from %s", cmd, self.serial)

    # --- Command methods (server → device) ---

    async def request_full_state(self) -> None:
        """Request full attribute snapshot from device."""
        await self._publish(self.topics.service_sub, build_attr_get())

    async def manual_feed(self, portions: int = 1) -> None:
        """Dispense food manually."""
        await self._publish(self.topics.service_sub, build_manual_feed(portions))

    async def set_attributes(self, **attrs: Any) -> None:
        """Set device attributes (sparse). Use camelCase MQTT keys."""
        from .protocol.messages import denormalize_attrs
        mqtt_attrs = denormalize_attrs(**attrs)
        from .protocol.codec import build_attr_set
        await self._publish(self.topics.service_sub, build_attr_set(**mqtt_attrs))

    async def reboot(self) -> None:
        """Reboot the device."""
        from .protocol.codec import build_device_reboot
        await self._publish(self.topics.system_sub, build_device_reboot())

    async def factory_restore(self) -> None:
        """Factory restore the device."""
        from .protocol.codec import build_restore
        await self._publish(self.topics.system_sub, build_restore())

    async def set_feeding_plans(self, plans: list[dict]) -> None:
        """Set feeding plans on the device."""
        from .protocol.codec import build_feeding_plan
        await self._publish(self.topics.service_sub, build_feeding_plan(plans))

    # --- Internal message handlers ---

    async def _handle_heartbeat(self, payload: dict) -> None:
        """Process heartbeat — update online status and check for reboot."""
        self._last_heartbeat = time.monotonic()
        was_online = self.online
        self.online = True

        count = payload.get("count")
        rssi = payload.get("rssi")

        # Detect device reboot (counter resets)
        if self._heartbeat_count is not None and count is not None:
            if count < self._heartbeat_count:
                _LOGGER.info("Device %s rebooted (count reset)", self.serial)
                await self._on_device_online()

        self._heartbeat_count = count

        # Update state with heartbeat data
        state_update = normalize_payload(payload)
        if state_update:
            self.state.update(state_update)

        if not was_online:
            await self._on_device_online()

        self._notify_state_changed()

    async def _handle_ntp(self, payload: dict) -> None:
        """Respond to NTP time check from device."""
        device_ts = payload.get("ts", 0)
        server_ts = timestamp_now_ms()
        drift_sec = abs(server_ts - device_ts) / 1000

        calibrate = drift_sec > NTP_DRIFT_THRESHOLD_SEC
        if calibrate:
            _LOGGER.info(
                "Device %s clock drift %.1fs, recalibrating", self.serial, drift_sec
            )

        await self._publish(self.topics.ntp_sub, build_ntp_response(calibrate))

    async def _handle_ntp_sync(self, payload: dict) -> None:
        """Handle NTP_SYNC response from device after calibration."""
        device_ts = payload.get("ts", 0)
        server_ts = timestamp_now_ms()
        drift_sec = abs(server_ts - device_ts) / 1000

        if drift_sec > NTP_DRIFT_THRESHOLD_SEC:
            _LOGGER.warning(
                "Device %s still drifted %.1fs after NTP sync", self.serial, drift_sec
            )

    async def _handle_device_start(self, payload: dict) -> None:
        """Device just started up — respond and request full state."""
        msg_id = payload.get("msgId")
        self.device_info = normalize_payload(payload)
        self.online = True
        self._last_heartbeat = time.monotonic()

        # Acknowledge device start
        await self._publish(
            self.topics.event_sub,
            build_response(CMD_DEVICE_START_EVENT, msg_id),
        )

        # Request full state
        await self._on_device_online()
        self._notify_state_changed()

    async def _handle_attr_push(self, payload: dict) -> None:
        """Sparse attribute update from device."""
        msg_id = payload.get("msgId")

        # Acknowledge
        await self._publish(
            self.topics.event_sub,
            build_response(CMD_ATTR_PUSH_EVENT, msg_id),
        )

        # Update state
        state_update = normalize_payload(payload)
        self.state.update(state_update)
        self._notify_state_changed()

    async def _handle_attr_get_response(self, payload: dict) -> None:
        """Full attribute snapshot from device (response to our request)."""
        state_update = normalize_payload(payload)
        self.state.update(state_update)
        self._notify_state_changed()

    async def _handle_attr_set_response(self, payload: dict) -> None:
        """Device acknowledged our attribute change."""
        code = payload.get("code", -1)
        if code != CODE_OK:
            _LOGGER.warning(
                "Device %s ATTR_SET_SERVICE failed: code=%s", self.serial, code
            )

    async def _handle_grain_output(self, payload: dict) -> None:
        """Grain dispensing event from device."""
        msg_id = payload.get("msgId")
        exec_step = payload.get("execStep", "")

        # Acknowledge
        await self._publish(
            self.topics.service_sub,
            build_response(CMD_GRAIN_OUTPUT_EVENT, msg_id, execStep=exec_step),
        )

        # Update state with grain output info
        state_update = normalize_payload(payload)
        self.state.update(state_update)
        self._notify_state_changed()

    async def _handle_get_feeding_plan(self, payload: dict) -> None:
        """Device requesting current feeding plans — respond with stored plans."""
        msg_id = payload.get("msgId")

        # Build plan response
        plans_payload = []
        for plan in self.feeding_plans:
            plan_data = dict(plan)
            plans_payload.append(plan_data)

        await self._publish(
            self.topics.service_sub,
            build_response(
                CMD_GET_FEEDING_PLAN_EVENT, msg_id, plans=plans_payload
            ),
        )

    async def _handle_feeding_plan_response(self, payload: dict) -> None:
        """Device acknowledged feeding plan update."""
        code = payload.get("code", -1)
        if code != CODE_OK:
            msg = payload.get("msg", "unknown")
            _LOGGER.warning(
                "Device %s FEEDING_PLAN_SERVICE failed: code=%s msg=%s",
                self.serial, code, msg,
            )

    async def _handle_manual_feeding_response(self, payload: dict) -> None:
        """Device acknowledged manual feeding."""
        code = payload.get("code", -1)
        if code != CODE_OK:
            _LOGGER.warning(
                "Device %s MANUAL_FEEDING_SERVICE failed: code=%s", self.serial, code
            )

    async def _handle_error_event(self, payload: dict) -> None:
        """Device reported an error."""
        msg_id = payload.get("msgId")
        error_code = payload.get("errorCode", "unknown")
        _LOGGER.warning("Device %s error: %s", self.serial, error_code)

        # Acknowledge
        await self._publish(
            self.topics.event_sub,
            build_response(CMD_ERROR_EVENT, msg_id),
        )

        state_update = normalize_payload(payload)
        self.state.update(state_update)
        self._notify_state_changed()

    async def _handle_get_config(self, payload: dict) -> None:
        """Device requesting config — acknowledge."""
        msg_id = payload.get("msgId")
        await self._publish(
            self.topics.config_sub,
            build_response(CMD_GET_CONFIG, msg_id),
        )

    async def _handle_binding(self, payload: dict) -> None:
        """Device binding request — acknowledge."""
        msg_id = payload.get("msgId")
        await self._publish(
            self.topics.system_sub,
            build_response(CMD_BINDING, msg_id),
        )

    async def _handle_reset(self, payload: dict) -> None:
        """Device is being factory reset."""
        msg_id = payload.get("msgId")
        _LOGGER.info("Device %s factory reset", self.serial)
        await self._publish(
            self.topics.system_sub,
            build_response(CMD_RESET, msg_id),
        )

    async def _handle_detection_event(self, payload: dict) -> None:
        """Motion or sound detection event from device camera."""
        msg_id = payload.get("msgId")
        detection_type = payload.get("type", "UNKNOWN")
        ts = payload.get("ts")
        _LOGGER.debug(
            "Device %s detection: type=%s ts=%s", self.serial, detection_type, ts
        )

        # Acknowledge
        await self._publish(
            self.topics.event_sub,
            build_response(CMD_DETECTION_EVENT, msg_id),
        )

        # Store in state for the event entity to pick up
        self.state["detection_type"] = detection_type
        self.state["detection_ts"] = ts
        self._notify_state_changed()

    # --- Handler dispatch table ---

    _HANDLERS: dict[str, Callable] = {
        CMD_HEARTBEAT: _handle_heartbeat,
        CMD_NTP: _handle_ntp,
        CMD_NTP_SYNC: _handle_ntp_sync,
        CMD_DEVICE_START_EVENT: _handle_device_start,
        CMD_ATTR_PUSH_EVENT: _handle_attr_push,
        CMD_ATTR_GET_SERVICE: _handle_attr_get_response,
        CMD_ATTR_SET_SERVICE: _handle_attr_set_response,
        CMD_GRAIN_OUTPUT_EVENT: _handle_grain_output,
        CMD_GET_FEEDING_PLAN_EVENT: _handle_get_feeding_plan,
        CMD_FEEDING_PLAN_SERVICE: _handle_feeding_plan_response,
        CMD_MANUAL_FEEDING_SERVICE: _handle_manual_feeding_response,
        CMD_ERROR_EVENT: _handle_error_event,
        CMD_DETECTION_EVENT: _handle_detection_event,
        CMD_GET_CONFIG: _handle_get_config,
        CMD_BINDING: _handle_binding,
        CMD_RESET: _handle_reset,
    }

    # --- Internal helpers ---

    async def _on_device_online(self) -> None:
        """Called when device first comes online or reboots."""
        _LOGGER.info("Device %s online, requesting state", self.serial)
        # Send NTP sync first
        await self._publish(self.topics.ntp_sub, build_ntp_sync())
        # Then request full state
        await asyncio.sleep(0.5)
        await self.request_full_state()

    async def _heartbeat_watchdog(self) -> None:
        """Periodically check if device is still sending heartbeats."""
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)
            if self._last_heartbeat > 0:
                elapsed = time.monotonic() - self._last_heartbeat
                if elapsed > HEARTBEAT_WATCHDOG_SEC and self.online:
                    _LOGGER.warning(
                        "Device %s heartbeat timeout (%.0fs)", self.serial, elapsed
                    )
                    self.online = False
                    self._notify_state_changed()

    async def _publish(self, topic: str, payload: str) -> None:
        """Publish an MQTT message."""
        await self._mqtt_publish(topic, payload)

    def _notify_state_changed(self) -> None:
        """Notify coordinator of state change."""
        if self._on_state_changed:
            self._on_state_changed(self)
