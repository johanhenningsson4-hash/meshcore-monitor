"""MeshCore companion protocol commands and response decoding."""

import struct

SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

START = bytes([1, 0, 0, 0, 0, 0, 0, 0]) + b"Monitor"
DEVICE = bytes([0x16, 3])
BATTERY = bytes([0x14])
NEXT = bytes([0x0A])
CONTACTS = bytes([0x04])

MAX_MESSAGE_BYTES = 120


def build_message(destination_type, destination, message, timestamp):
    if not isinstance(message, str) or not message.strip() or "\0" in message:
        raise ValueError("Enter a non-empty message without NUL characters.")
    text = message.encode("utf-8")
    if len(text) > MAX_MESSAGE_BYTES:
        raise ValueError(f"Message must be at most {MAX_MESSAGE_BYTES} UTF-8 bytes.")
    if not isinstance(timestamp, int) or not 0 <= timestamp <= 0xFFFFFFFF:
        raise ValueError("Message timestamp is outside the supported range.")
    if destination_type == "channel":
        if not isinstance(destination, int) or not 0 <= destination <= 255:
            raise ValueError("Channel number must be between 0 and 255.")
        return bytes([3, 0, destination]) + struct.pack("<I", timestamp) + text
    if destination_type == "contact":
        if not isinstance(destination, str) or len(destination) != 12:
            raise ValueError("Contact key prefix must be exactly 12 hexadecimal characters.")
        try:
            key = bytes.fromhex(destination)
        except ValueError as error:
            raise ValueError("Contact key prefix must be exactly 12 hexadecimal characters.") from error
        if len(key) != 6:
            raise ValueError("Contact key prefix must be exactly 12 hexadecimal characters.")
        return bytes([2, 0, 0]) + struct.pack("<I", timestamp) + key + text
    raise ValueError("Choose a channel or contact destination.")


def _text(data):
    return data.decode("utf-8", errors="replace").split("\0", 1)[0].strip()


def parse_packet(data):
    data = bytes(data)
    if not data:
        raise ValueError("Empty response from device.")
    code = data[0]

    def require(length):
        if len(data) < length:
            raise ValueError(f"Incomplete device response (0x{code:x}).")

    if code == 0x05:
        require(58)
        frequency, bandwidth = struct.unpack_from("<II", data, 48)
        return {
            "type": "self", "name": _text(data[58:]),
            "publicKey": data[4:36].hex(),
            "frequency": frequency / 1000, "bandwidth": bandwidth / 1000,
            "spreadingFactor": data[56], "codingRate": data[57],
        }
    if code == 0x0D:
        require(2)
        return {
            "type": "device", "protocolVersion": data[1],
            "maxChannels": data[3] if data[1] >= 3 and len(data) >= 4 else None,
            "model": _text(data[20:60]) if len(data) >= 60 else "",
            "version": _text(data[60:80]) if len(data) >= 80 else "",
        }
    if code == 0x0C:
        require(3)
        return {"type": "battery", "millivolts": struct.unpack_from("<H", data, 1)[0]}
    if code == 0x00:
        return {"type": "ok"}
    if code == 0x02:
        require(5)
        return {"type": "contacts_start"}
    if code == 0x03:
        require(132)
        return {"type": "contact", "publicKey": data[1:33].hex(), "name": _text(data[100:132])}
    if code == 0x04:
        require(5)
        return {"type": "contacts_end"}
    if code == 0x12:
        require(34)
        return {"type": "channel", "index": data[1], "name": _text(data[2:34])}
    if code == 0x06:
        require(10)
        return {
            "type": "sent", "route": data[1],
            "ack": struct.unpack_from("<I", data, 2)[0],
            "timeout": struct.unpack_from("<I", data, 6)[0],
        }
    if code in (0x07, 0x08, 0x10, 0x11):
        v3 = code in (0x10, 0x11)
        contact = code in (0x07, 0x10)
        offset = 4 if v3 else 1
        require(offset + (12 if contact else 7))
        sender = data[offset:offset + 6].hex() if contact else f"Channel {data[offset]}"
        offset += 6 if contact else 1
        path, text_type = data[offset:offset + 2]
        offset += 2
        timestamp = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        if contact and text_type == 2:
            require(offset + 4)
            offset += 4
        return {
            "type": "message", "sender": sender, "kind": "Contact" if contact else "Channel",
            "path": path, "textType": text_type, "timestamp": timestamp,
            "text": _text(data[offset:]),
            "snr": struct.unpack_from("<b", data, 1)[0] / 4 if v3 else None,
        }
    if code == 0x1B:
        require(9)
        require(9 + data[8])
        return {
            "type": "datagram", "sender": f"Channel {data[4]}",
            "length": data[8], "dataType": struct.unpack_from("<H", data, 6)[0],
        }
    if code == 0x0A:
        return {"type": "empty"}
    if code == 0x83:
        return {"type": "waiting"}
    if code == 0x01:
        return {"type": "error", "code": data[1] if len(data) > 1 else None}
    return {"type": "other", "code": code}
