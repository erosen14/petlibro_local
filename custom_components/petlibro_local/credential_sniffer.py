"""Lightweight MQTT CONNECT packet sniffer for auto-detecting Petlibro credentials.

When Mosquitto is temporarily stopped, this starts a TCP server on port 1883.
The Petlibro feeder reconnects and sends a CONNECT packet containing its
client_id (serial), username (product_key), and password (product_secret).
We capture these credentials and send CONNACK (refused) back.
"""

from __future__ import annotations

import asyncio
import logging
import struct

_LOGGER = logging.getLogger(__name__)

MQTT_CONNECT_PACKET_TYPE = 1
SNIFFER_TIMEOUT = 120  # seconds to wait for a connection

# HA internal MQTT clients to ignore
_HA_CLIENT_PREFIXES = ("homeassistant", "addons", "mqttjs_", "ha-")


class CredentialSnifferError(Exception):
    """Error during credential sniffing."""


def _parse_mqtt_connect(data: bytes) -> dict[str, str]:
    """Parse an MQTT CONNECT packet and extract credentials.

    Supports both MQTT 3.1 (MQIsdp) and 3.1.1 (MQTT) protocols.
    Returns dict with client_id, username, password.
    """
    if len(data) < 2:
        raise CredentialSnifferError("Packet too short")

    byte1 = data[0]
    packet_type = (byte1 >> 4) & 0x0F
    if packet_type != MQTT_CONNECT_PACKET_TYPE:
        raise CredentialSnifferError(f"Not a CONNECT packet (type={packet_type})")

    # Decode remaining length (variable-length encoding)
    pos = 1
    remaining_length = 0
    multiplier = 1
    while pos < len(data):
        encoded_byte = data[pos]
        remaining_length += (encoded_byte & 0x7F) * multiplier
        multiplier *= 128
        pos += 1
        if (encoded_byte & 0x80) == 0:
            break

    if len(data) < pos + remaining_length:
        raise CredentialSnifferError("Incomplete packet")

    def read_utf8_string(p: int) -> tuple[str, int]:
        if p + 2 > len(data):
            raise CredentialSnifferError("String length truncated")
        str_len = struct.unpack("!H", data[p : p + 2])[0]
        p += 2
        if p + str_len > len(data):
            raise CredentialSnifferError("String data truncated")
        return data[p : p + str_len].decode("utf-8", errors="replace"), p + str_len

    # Protocol name
    protocol_name, pos = read_utf8_string(pos)
    if protocol_name not in ("MQTT", "MQIsdp"):
        raise CredentialSnifferError(f"Unknown protocol: {protocol_name}")

    # Protocol level
    if pos >= len(data):
        raise CredentialSnifferError("Missing protocol level")
    pos += 1  # skip protocol level

    # Connect flags
    if pos >= len(data):
        raise CredentialSnifferError("Missing connect flags")
    connect_flags = data[pos]
    pos += 1

    has_username = bool(connect_flags & 0x80)
    has_password = bool(connect_flags & 0x40)
    has_will = bool(connect_flags & 0x04)

    # Keep alive
    if pos + 2 > len(data):
        raise CredentialSnifferError("Missing keep alive")
    pos += 2

    # Payload: Client ID
    client_id, pos = read_utf8_string(pos)

    # Will Topic + Will Message (if present)
    if has_will:
        _will_topic, pos = read_utf8_string(pos)
        if pos + 2 > len(data):
            raise CredentialSnifferError("Will payload truncated")
        will_len = struct.unpack("!H", data[pos : pos + 2])[0]
        pos += 2 + will_len

    # Username
    username = ""
    if has_username:
        username, pos = read_utf8_string(pos)

    # Password
    password = ""
    if has_password:
        password, pos = read_utf8_string(pos)

    return {
        "client_id": client_id,
        "username": username,
        "password": password,
    }


def _make_connack_refused() -> bytes:
    """Build MQTT CONNACK with 'not authorized' return code."""
    return bytes([0x20, 0x02, 0x00, 0x05])


def _is_ha_client(client_id: str) -> bool:
    """Check if this is a Home Assistant internal MQTT client."""
    lower = client_id.lower()
    return any(lower.startswith(p) for p in _HA_CLIENT_PREFIXES)


async def sniff_mqtt_credentials(
    host: str = "0.0.0.0",
    port: int = 1883,
    timeout: int = SNIFFER_TIMEOUT,
) -> dict[str, str]:
    """Start a temporary MQTT listener and capture the first device CONNECT.

    Ignores HA internal clients (homeassistant, addons, etc).
    Returns dict with client_id, username, password.
    Raises CredentialSnifferError on timeout or parse failure.
    """
    result: dict[str, str] | None = None
    event = asyncio.Event()

    async def handle_client(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        nonlocal result
        peer = writer.get_extra_info("peername")
        _LOGGER.debug("Sniffer: connection from %s", peer)

        try:
            data = await asyncio.wait_for(reader.read(4096), timeout=10)
            if not data:
                return

            creds = _parse_mqtt_connect(data)
            _LOGGER.info(
                "Sniffer: CONNECT from client_id=%s, username=%s",
                creds["client_id"],
                creds["username"],
            )

            # Skip HA internal clients
            if _is_ha_client(creds["client_id"]):
                _LOGGER.debug("Sniffer: ignoring HA client %s", creds["client_id"])
                writer.write(_make_connack_refused())
                await writer.drain()
                return

            # This is a device — capture credentials
            result = creds
            event.set()

            writer.write(_make_connack_refused())
            await writer.drain()
        except Exception as exc:
            _LOGGER.debug("Sniffer: error handling connection: %s", exc)
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle_client, host, port)
    _LOGGER.info("Sniffer: listening on %s:%d (timeout %ds)", host, port, timeout)

    try:
        async with server:
            await asyncio.wait_for(event.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    finally:
        server.close()
        await server.wait_closed()

    if result is None:
        raise CredentialSnifferError(
            f"No device CONNECT received within {timeout}s"
        )

    return result
