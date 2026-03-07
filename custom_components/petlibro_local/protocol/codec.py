"""JSON codec helpers for Petlibro MQTT messages."""

from __future__ import annotations

import datetime
import hashlib
import json
import time
import uuid
from typing import Any


def generate_msg_id() -> str:
    """Generate a 32-char message ID (SHA256 of random UUID)."""
    return hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest()[:32]


def timestamp_now_ms() -> int:
    """Current time as milliseconds since epoch."""
    return int(time.time() * 1000)


def timezone_offset_hours() -> float:
    """Local timezone offset from UTC in hours."""
    now = datetime.datetime.now().astimezone()
    return now.utcoffset().total_seconds() / 3600


def build_response(cmd: str, msg_id: str | None = None, code: int = 0, **extra) -> str:
    """Build a JSON response payload to send to the device."""
    payload: dict[str, Any] = {
        "cmd": cmd,
        "ts": timestamp_now_ms(),
        "code": code,
    }
    if msg_id is not None:
        payload["msgId"] = msg_id
    else:
        payload["msgId"] = generate_msg_id()
    payload.update(extra)
    return json.dumps(payload)


def build_command(cmd: str, **kwargs) -> str:
    """Build a JSON command payload (server → device)."""
    payload: dict[str, Any] = {
        "cmd": cmd,
        "msgId": generate_msg_id(),
        "ts": timestamp_now_ms(),
    }
    payload.update(kwargs)
    return json.dumps(payload)


def build_ntp_response(calibrate: bool = False) -> str:
    """Build NTP response with current time and timezone."""
    now_ms = timestamp_now_ms()
    tz_hours = timezone_offset_hours()
    return json.dumps({
        "cmd": "NTP",
        "ts": now_ms,
        "code": 0,
        "calibrationTag": calibrate,
        "timezone": tz_hours,
    })


def build_ntp_sync() -> str:
    """Build NTP_SYNC command to force device time recalibration."""
    return json.dumps({
        "cmd": "NTP_SYNC",
        "msgId": generate_msg_id(),
        "ts": timestamp_now_ms(),
        "timezone": timezone_offset_hours(),
    })


def build_manual_feed(portions: int) -> str:
    """Build manual feeding command."""
    return build_command("MANUAL_FEEDING_SERVICE", grainNum=portions)


def build_attr_get() -> str:
    """Build request for full device attribute snapshot."""
    return build_command("ATTR_GET_SERVICE")


def build_attr_set(**attrs) -> str:
    """Build attribute set command with sparse key-value pairs.

    Keys should be camelCase MQTT field names, e.g.:
        build_attr_set(lightSwitch=True, volume=50)
    """
    return build_command("ATTR_SET_SERVICE", **attrs)


def build_device_reboot() -> str:
    """Build device reboot command."""
    return build_command("DEVICE_REBOOT")


def build_restore() -> str:
    """Build factory restore command."""
    return build_command("RESTORE")


def build_feeding_plan(plans: list[dict]) -> str:
    """Build feeding plan service command.

    Each plan dict should have keys:
        planId, executionTime, repeatDay, enableAudio, audioTimes, grainNum, syncTime
    """
    return build_command("FEEDING_PLAN_SERVICE", plans=plans)


def parse_payload(raw: str | bytes) -> dict[str, Any]:
    """Parse an MQTT message payload from JSON."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    return json.loads(raw)
