"""Lightweight MQTT CONNECT packet sniffer for auto-detecting Petlibro credentials.

Starts a temporary TCP server on port 1883. When the Petlibro device connects
(after DNS redirect), we parse the MQTT CONNECT packet to extract client_id,
username, and password. Then we send CONNACK (refused) and close.
"""

from __future__ import annotations

import asyncio
import logging
import struct

_LOGGER = logging.getLogger(__name__)

MQTT_CONNECT_PACKET_TYPE = 1
SNIFFER_TIMEOUT = 120  # seconds to wait for a connection


class CredentialSnifferError(Exception):
    """Error during credential sniffing."""


def _parse_mqtt_connect(data: bytes) -> dict[str, str]:
    """Parse an MQTT 3.1.1 CONNECT packet and extract credentials.

    MQTT CONNECT format (after fixed header):
      - Protocol Name (length-prefixed string): "MQTT" or "MQIsdp"
      - Protocol Level: 4 (for 3.1.1)
      - Connect Flags: 1 byte
      - Keep Alive: 2 bytes
      - Payload (length-prefixed strings in order):
        - Client ID (always present)
        - Will Topic (if will flag set)
        - Will Message (if will flag set)
        - Username (if username flag set)
        - Password (if password flag set)
    """
    pos = 0

    # Fixed header: packet type + remaining length
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

    payload_start = pos
    if len(data) < payload_start + remaining_length:
        raise CredentialSnifferError("Incomplete packet")

    # Variable header starts at pos
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
    protocol_level = data[pos]
    pos += 1

    # Connect flags
    if pos >= len(data):
        raise CredentialSnifferError("Missing connect flags")
    connect_flags = data[pos]
    pos += 1

    has_username = bool(connect_flags & 0x80)
    has_password = bool(connect_flags & 0x40)
    has_will_retain = bool(connect_flags & 0x20)
    will_qos = (connect_flags >> 3) & 0x03
    has_will = bool(connect_flags & 0x04)

    # Keep alive
    if pos + 2 > len(data):
        raise CredentialSnifferError("Missing keep alive")
    pos += 2  # skip keep alive

    # Payload: Client ID
    client_id, pos = read_utf8_string(pos)

    # Will Topic + Will Message (if present)
    if has_will:
        _will_topic, pos = read_utf8_string(pos)
        # Will payload is length-prefixed binary
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
    """Build an MQTT CONNACK packet with 'connection refused' return code.

    This tells the device to back off without fully connecting.
    Return code 5 = "not authorized" — device will retry later.
    """
    # Fixed header: CONNACK (type 2), remaining length 2
    # Variable header: session present = 0, return code = 5 (not authorized)
    return bytes([0x20, 0x02, 0x00, 0x05])


async def sniff_mqtt_credentials(
    host: str = "0.0.0.0",
    port: int = 1883,
    timeout: int = SNIFFER_TIMEOUT,
) -> dict[str, str]:
    """Start a temporary MQTT listener and capture the first CONNECT packet.

    Returns dict with client_id, username, password.
    Raises CredentialSnifferError on timeout or parse failure.
    """
    result: dict[str, str] | None = None
    error: Exception | None = None

    async def handle_client(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        nonlocal result, error
        peer = writer.get_extra_info("peername")
        _LOGGER.info("Sniffer: connection from %s", peer)

        try:
            # Read enough data for a CONNECT packet (usually < 200 bytes)
            data = await asyncio.wait_for(reader.read(4096), timeout=10)
            if not data:
                return

            result = _parse_mqtt_connect(data)
            _LOGGER.info(
                "Sniffer: captured credentials — client_id=%s, username=%s",
                result["client_id"],
                result["username"],
            )

            # Send CONNACK refused so device retries later
            writer.write(_make_connack_refused())
            await writer.drain()
        except Exception as exc:
            _LOGGER.debug("Sniffer: parse error: %s", exc)
            error = exc
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle_client, host, port)
    _LOGGER.info("Sniffer: listening on %s:%d (timeout %ds)", host, port, timeout)

    try:
        deadline = asyncio.get_event_loop().time() + timeout
        async with server:
            while result is None:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    raise CredentialSnifferError(
                        f"No MQTT CONNECT received within {timeout}s"
                    )
                # Serve connections until we get a valid CONNECT
                await asyncio.wait_for(server.start_serving(), timeout=1)
                await asyncio.sleep(0.5)
                if result is not None:
                    break
    except asyncio.TimeoutError:
        pass
    finally:
        server.close()
        await server.wait_closed()

    if result is None:
        raise CredentialSnifferError(
            f"No MQTT CONNECT received within {timeout}s"
        )

    return result
