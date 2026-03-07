"""MQTT JSON field name mappings for Petlibro device state.

The device uses camelCase field names in its JSON payloads. This module
defines the mapping between MQTT field names and our internal snake_case
keys, along with value conversion functions.

Rather than 40+ dataclasses (like plaf203), we use a flat dict approach.
The device state is a simple dict[str, Any] that gets updated sparsely
on each ATTR_PUSH_EVENT.
"""

from __future__ import annotations

from typing import Any

# camelCase MQTT key → snake_case internal key
# Used to normalize incoming payloads to consistent internal names
FIELD_MAP: dict[str, str] = {
    # Power
    "powerMode": "power_mode",
    "powerType": "power_type",
    "electricQuantity": "battery_percent",
    # Feeder state
    "surplusGrain": "surplus_grain",
    "motorState": "motor_state",
    "grainOutletState": "grain_outlet_state",
    # Audio
    "enableAudio": "enable_audio",
    "audioUrl": "audio_url",
    "volume": "volume",
    # Light
    "lightSwitch": "light_switch",
    "enableLight": "enable_light",
    "lightAgingType": "light_aging_type",
    "lightingStartTimeUtc": "lighting_start_time_utc",
    "lightingEndTimeUtc": "lighting_end_time_utc",
    "lightingTimes": "lighting_times",
    # Sound
    "soundSwitch": "sound_switch",
    "enableSound": "enable_sound",
    "soundAgingType": "sound_aging_type",
    "soundStartTimeUtc": "sound_start_time_utc",
    "soundEndTimeUtc": "sound_end_time_utc",
    "soundTimes": "sound_times",
    # Auto lock
    "autoChangeMode": "auto_change_mode",
    "autoThreshold": "auto_threshold",
    # Camera
    "cameraSwitch": "camera_switch",
    "enableCamera": "enable_camera",
    "cameraAgingType": "camera_aging_type",
    "nightVision": "night_vision",
    "resolution": "resolution",
    "cameraStartTimeUtc": "camera_start_time_utc",
    "cameraEndTimeUtc": "camera_end_time_utc",
    # Video recording
    "videoRecordSwitch": "video_record_switch",
    "enableVideoRecord": "enable_video_record",
    "sdCardState": "sd_card_state",
    "sdCardFileSystem": "sd_card_file_system",
    "sdCardTotalCapacity": "sd_card_total_capacity",
    "sdCardUsedCapacity": "sd_card_used_capacity",
    "videoRecordMode": "video_record_mode",
    "videoRecordAgingType": "video_record_aging_type",
    "videoRecordStartTimeUtc": "video_record_start_time_utc",
    "videoRecordEndTimeUtc": "video_record_end_time_utc",
    # Feeding video
    "feedingVideoSwitch": "feeding_video_switch",
    "enableVideoStartFeedingPlan": "enable_video_start_feeding_plan",
    "enableVideoAfterManualFeeding": "enable_video_after_manual_feeding",
    "beforeFeedingPlanTime": "before_feeding_plan_time",
    "automaticRecording": "automatic_recording",
    "afterManualFeedingTime": "after_manual_feeding_time",
    "videoWatermarkSwitch": "video_watermark_switch",
    # Cloud recording
    "cloudVideoRecordSwitch": "cloud_video_record_switch",
    # Motion detection
    "motionDetectionSwitch": "motion_detection_switch",
    "enableMotionDetection": "enable_motion_detection",
    "motionDetectionAgingType": "motion_detection_aging_type",
    "motionDetectionRange": "motion_detection_range",
    "motionDetectionSensitivity": "motion_detection_sensitivity",
    "motionDetectionStartTimeUtc": "motion_detection_start_time_utc",
    "motionDetectionEndTimeUtc": "motion_detection_end_time_utc",
    # Sound detection
    "soundDetectionSwitch": "sound_detection_switch",
    "enableSoundDetection": "enable_sound_detection",
    "soundDetectionAgingType": "sound_detection_aging_type",
    "soundDetectionSensitivity": "sound_detection_sensitivity",
    "soundDetectionStartTimeUtc": "sound_detection_start_time_utc",
    "soundDetectionEndTimeUtc": "sound_detection_end_time_utc",
    # WiFi
    "wifiSsid": "wifi_ssid",
    # Heartbeat
    "count": "heartbeat_count",
    "rssi": "wifi_rssi",
    "wifiType": "wifi_type",
}

# Reverse map for building outgoing commands
REVERSE_FIELD_MAP: dict[str, str] = {v: k for k, v in FIELD_MAP.items()}

# Fields that should not be included in state updates (metadata only)
META_FIELDS = {"cmd", "msgId", "ts", "code", "msg"}

# Heartbeat fields from device
HEARTBEAT_FIELDS = {"count", "rssi", "wifiType"}

# Device start event fields
DEVICE_START_FIELDS = {
    "pid": "product_id",
    "uuid": "device_uuid",
    "mac": "mac_address",
    "wpa3": "wpa3",
    "hardwareVersion": "hardware_version",
    "softwareVersion": "software_version",
    "success": "start_success",
}

# Grain output event fields
GRAIN_OUTPUT_FIELDS = {
    "finished": "grain_finished",
    "type": "grain_output_type",
    "actualGrainNum": "actual_grain_num",
    "expectedGrainNum": "expected_grain_num",
    "execTime": "grain_exec_time",
    "execStep": "grain_exec_step",
    "planId": "grain_plan_id",
    "retried": "grain_retried",
}

# Error event fields
ERROR_FIELDS = {
    "errorCode": "error_code",
    "triggerTime": "error_trigger_time",
}

# Feeding plan fields (within plan objects)
FEEDING_PLAN_FIELDS = {
    "planId": "plan_id",
    "executionTime": "execution_time",
    "repeatDay": "repeat_day",
    "enableAudio": "enable_audio",
    "audioTimes": "audio_times",
    "grainNum": "grain_num",
    "syncTime": "sync_time",
    "skipEndTime": "skip_end_time",
}


def normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert a camelCase MQTT payload to snake_case internal state dict.

    Only includes fields that are in the FIELD_MAP. Unknown fields are
    preserved with their original key for forward-compatibility.
    """
    result: dict[str, Any] = {}
    for mqtt_key, value in payload.items():
        if mqtt_key in META_FIELDS:
            continue
        if mqtt_key in FIELD_MAP:
            result[FIELD_MAP[mqtt_key]] = value
        elif mqtt_key in DEVICE_START_FIELDS:
            result[DEVICE_START_FIELDS[mqtt_key]] = value
        elif mqtt_key in GRAIN_OUTPUT_FIELDS:
            result[GRAIN_OUTPUT_FIELDS[mqtt_key]] = value
        elif mqtt_key in ERROR_FIELDS:
            result[ERROR_FIELDS[mqtt_key]] = value
    return result


def denormalize_attrs(**kwargs: Any) -> dict[str, Any]:
    """Convert snake_case internal keys back to camelCase for ATTR_SET_SERVICE."""
    result: dict[str, Any] = {}
    for key, value in kwargs.items():
        if key in REVERSE_FIELD_MAP:
            result[REVERSE_FIELD_MAP[key]] = value
        else:
            result[key] = value
    return result
