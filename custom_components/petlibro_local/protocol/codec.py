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


def local_time_to_utc(local_time_str: str) -> str:
    """Convert a local "HH:MM" (or "HH:MM:SS") string to a UTC "HH:MM" string.

    Uses the current UTC offset, so the result changes across DST transitions;
    callers must keep the local time and re-run this after an offset change.
    """
    parts = local_time_str.split(":")
    h, m = int(parts[0]), int(parts[1])
    local_dt = datetime.datetime.combine(
        datetime.date.today(),
        datetime.time(h, m),
        tzinfo=datetime.datetime.now().astimezone().tzinfo,
    )
    utc_dt = local_dt.astimezone(datetime.timezone.utc)
    return f"{utc_dt.hour:02}:{utc_dt.minute:02}"


def utc_time_to_local(utc_time_str: str) -> str:
    """Convert a UTC "HH:MM" string to a local "HH:MM" string (current offset)."""
    h, m = map(int, utc_time_str.split(":"))
    utc_dt = datetime.datetime.combine(
        datetime.date.today(),
        datetime.time(h, m),
        tzinfo=datetime.timezone.utc,
    )
    local_dt = utc_dt.astimezone()
    return f"{local_dt.hour:02}:{local_dt.minute:02}"


def plan_for_device(plan: dict) -> dict:
    """Return a copy of a stored plan with integration-only keys removed."""
    return {k: v for k, v in plan.items() if k != "localTime"}


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
    Integration-only keys (localTime) are stripped before sending.
    """
    return build_command(
        "FEEDING_PLAN_SERVICE", plans=[plan_for_device(p) for p in plans]
    )


def parse_payload(raw: str | bytes) -> dict[str, Any]:
    """Parse an MQTT message payload from JSON."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    return json.loads(raw)
