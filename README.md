# Petlibro Local

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/erosen14/petlibro_local)](https://github.com/erosen14/petlibro_local/releases)
[![License: Unlicense](https://img.shields.io/badge/license-Unlicense-blue.svg)](LICENSE)

Fully local [Home Assistant](https://www.home-assistant.io/) integration for [Petlibro](https://petlibro.com/) automatic pet feeders over MQTT. No cloud, no Petlibro app, no internet required after initial Wi-Fi setup.

## How It Works

Petlibro feeders communicate with `mqtt.us.petlibro.com` over unencrypted MQTT (port 1883). By redirecting that hostname to a local MQTT broker via DNS, the feeder talks directly to your Home Assistant instance instead of the cloud.

This integration:

1. Connects to your local MQTT broker
2. Speaks the Petlibro MQTT protocol to your feeder
3. Exposes all feeder controls and sensors as Home Assistant entities

## Supported Devices

| Model | Status | Credentials |
|-------|--------|-------------|
| PLAF203 / PLAF203S | Supported | Built-in (no sniffing needed) |
| Other models | Should work | Auto-detect via built-in sniffer |

> The MQTT credentials (product key and secret) are identical across all devices of the same model, hard-coded in the firmware. If your model isn't in the known credentials database yet, the setup flow can automatically capture them from your device. Please consider submitting a PR to add your model's credentials so others don't need to sniff.

## Features

### Sensors
- Battery level, Wi-Fi signal strength (RSSI)
- Motor state, feeding status, error codes
- Last feed type and portions dispensed
- Firmware version, power mode/type
- SD card capacity and usage

### Controls
- **Buttons** — Dispense food, reboot, factory reset
- **Switches** — LED light, sound, camera, audio, video recording, cloud recording, motion/sound detection, auto button lock
- **Numbers** — Dispense portion count (1-20), volume (0-100%)
- **Selects** — Night vision mode, camera resolution, video record mode, motion detection range/sensitivity, sound detection sensitivity

### Monitoring
- **Binary sensors** — Online status, food level, grain outlet blocked
- **Events** — Feeding lifecycle (started, complete, blocked), device errors

### Services
- `petlibro_local.manual_feed` — Dispense a specific number of portions
- `petlibro_local.set_feeding_plan` — Create/update a feeding schedule (time, portions, days, audio)
- `petlibro_local.clear_feeding_plans` — Remove all feeding schedules

## Prerequisites

1. **Local MQTT broker** — [Mosquitto add-on](https://github.com/home-assistant/addons/blob/master/mosquitto/DOCS.md) or any MQTT broker on your network
2. **DNS redirect** — Point `mqtt.us.petlibro.com` to your MQTT broker's IP

### DNS Redirect Options

The feeder resolves `mqtt.us.petlibro.com` to find its MQTT server. You need to override this to point to your local broker.

| Method | Difficulty | Notes |
|--------|-----------|-------|
| **Router/firewall DNS override** | Easy | OPNsense, pfSense, UniFi, OpenWrt — add a host override entry |
| **[AdGuard Home add-on](https://github.com/hassio-addons/addon-adguard-home)** | Easy | Filters > DNS Rewrites > add `mqtt.us.petlibro.com` > broker IP |
| **[Dnsmasq add-on](https://github.com/home-assistant/addons/blob/master/dnsmasq/DOCS.md)** | Medium | Official HA add-on — add a `hosts` entry in the add-on config |
| **Pi-hole** | Medium | Local DNS Records > add hostname > IP mapping |

> **Note**: If using a DNS add-on on HA (AdGuard, Dnsmasq), your router's DHCP settings must hand out HA's IP as the DNS server so the feeder resolves through it.

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu > **Custom repositories**
3. Add `https://github.com/erosen14/petlibro_local` as an **Integration**
4. Search for "Petlibro Local" and install
5. Restart Home Assistant

### Manual

1. Download the [latest release](https://github.com/erosen14/petlibro_local/releases)
2. Copy the `custom_components/petlibro_local` folder to your `config/custom_components/` directory
3. Restart Home Assistant

## Setup

Add the integration via **Settings > Devices & Services > Add Integration > Petlibro Local**.

The config flow offers two paths:

### Auto-detect (recommended)

1. Select **Auto-detect from device**
2. Set up the DNS redirect as prompted (the UI shows your HA IP)
3. Click Submit — the integration starts a temporary MQTT listener on port 1883
4. Wait ~30-90 seconds for the feeder to reconnect
5. Serial number, model, and credentials are captured automatically
6. Confirm the detected values and enter your MQTT broker details

### Manual entry

1. Select **Enter serial number manually**
2. Enter your device serial number and model (e.g. `PLAF203`)
3. If the model has known credentials, you'll skip straight to broker config
4. Otherwise, choose auto-detect or enter MQTT credentials manually
5. Enter your MQTT broker details

### Finding Your Serial Number

The serial number (DL_DEVICE_ID) can be found:
- On the device label (bottom of feeder)
- In the Petlibro app under device settings
- Automatically via the auto-detect setup flow

## Debug Logging

Add to your `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.petlibro_local: debug
```

## Known Limitations

- **Camera/audio streaming** is not supported — the device uses ThroughTek's Kalay SDK (proprietary cloud video platform) which cannot be easily replicated locally
- **OTA firmware updates** are not implemented
- **Feeding audio** may cause a device reboot if the audio file URL is unreachable — disable feeding audio via the sound switch if your feeder has no internet access

## Acknowledgments

This integration builds on the protocol reverse engineering work from the [plaf203](https://github.com/icex2/plaf203) project by [@icex2](https://github.com/icex2). That project documented the full Petlibro MQTT protocol, message formats, and topic structure as an AppDaemon prototype. The protocol layer in this integration is derived from that research.

Security research by [Kaspersky Securelist](https://securelist.com/) confirmed that MQTT credentials are hard-coded per device model in the firmware, enabling the known credentials database that makes setup instant for supported models.

## Contributing

Contributions are welcome. The most impactful way to help:

- **Add your device's credentials** — Use the auto-detect flow to capture credentials for your model, then submit a PR adding them to `known_credentials.py`
- **Report issues** — File bugs or feature requests on the [issue tracker](https://github.com/erosen14/petlibro_local/issues)
- **Test on different models** — The protocol should work across Petlibro's MQTT-based product line

## License

[Unlicense](LICENSE) — public domain.
