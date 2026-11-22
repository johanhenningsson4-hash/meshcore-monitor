import struct
import unittest

from meshcore_monitor import protocol


class ProtocolTests(unittest.TestCase):
    def test_radio_contacts_and_channels(self):
        key = bytes(range(32))
        contact = bytes([3]) + key + bytes(3 + 64) + b"Alice\0" + bytes(26)
        self.assertEqual(protocol.parse_packet(contact),
                         {"type": "contact", "publicKey": key.hex(), "name": "Alice"})
        channel = bytes([0x12, 4]) + b"Local\0" + bytes(26) + b"secret-secret-00"
        self.assertEqual(protocol.parse_packet(channel), {"type": "channel", "index": 4, "name": "Local"})
        self.assertEqual(protocol.parse_packet(bytes([13, 3, 0, 40]))["maxChannels"], 40)
        self.assertIsNone(protocol.parse_packet(bytes([13, 3]))["maxChannels"])
        for data in (bytes([2]), bytes([3, 0]), bytes([4]), bytes([0x12, 0])):
            with self.subTest(data=data), self.assertRaises(ValueError):
                protocol.parse_packet(data)

    def test_build_channel_and_contact_messages(self):
        self.assertEqual(protocol.build_message("channel", 1, "Hello", 1234567890),
                         bytes.fromhex("03 00 01 d2 02 96 49") + b"Hello")
        self.assertEqual(protocol.build_message("contact", "010203040506", "Hi", 42),
                         bytes.fromhex("02 00 00 2a 00 00 00 01 02 03 04 05 06") + b"Hi")
        self.assertEqual(protocol.parse_packet(bytes([0])), {"type": "ok"})
        self.assertEqual(protocol.parse_packet(bytes.fromhex("06 01 78 56 34 12 e8 03 00 00")),
                         {"type": "sent", "route": 1, "ack": 0x12345678, "timeout": 1000})
        with self.assertRaises(ValueError):
            protocol.parse_packet(bytes([6]))

    def test_invalid_outgoing_messages(self):
        cases = [
            ("channel", -1, "Hello"), ("channel", 256, "Hello"),
            ("contact", "01020304050x", "Hello"), ("contact", "01 02 03 04 ", "Hello"),
            ("channel", 0, ""), ("channel", 0, "\0Hello"),
            ("channel", 0, "é" * 61),
        ]
        for destination_type, destination, message in cases:
            with self.subTest(destination=destination, message=message), self.assertRaises(ValueError):
                protocol.build_message(destination_type, destination, message, 1)
        self.assertEqual(len(protocol.build_message("channel", 0, "é" * 60, 1)), 127)

    def test_self_and_battery(self):
        data = bytearray(62)
        data[0] = 5
        struct.pack_into("<II", data, 48, 869525, 62500)
        data[56] = 8
        data[58:] = b"Node"
        packet = protocol.parse_packet(data)
        self.assertEqual((packet["name"], packet["frequency"], packet["bandwidth"]), ("Node", 869.525, 62.5))
        self.assertEqual(protocol.parse_packet(bytes([12, 0x74, 0x0E]))["millivolts"], 3700)

    def test_messages_and_datagram(self):
        channel = bytes([8, 2, 255, 0, 1, 0, 0, 0]) + b"Alice: hello"
        packet = protocol.parse_packet(channel)
        self.assertEqual((packet["sender"], packet["text"], packet["timestamp"]), ("Channel 2", "Alice: hello", 1))
        contact = bytes([0x10, 0xF6, 0, 0, 1, 2, 3, 4, 5, 6, 3, 2, 42, 0, 0, 0, 9, 8, 7, 6]) + b"hello"
        packet = protocol.parse_packet(contact)
        self.assertEqual((packet["sender"], packet["snr"], packet["text"]), ("010203040506", -2.5, "hello"))
        self.assertEqual(protocol.parse_packet(bytes([0x11, 4, 0, 0]) + channel[1:])["text"], "Alice: hello")
        self.assertEqual(protocol.parse_packet(bytes([0x1B, 0, 0, 0, 1, 0, 255, 255, 1, 5])),
                         {"type": "datagram", "sender": "Channel 1", "dataType": 65535, "length": 1})

    def test_truncated_packets(self):
        for data in (b"", bytes([8, 0]), bytes([0x1B, 0, 0, 0, 1, 0, 1, 0, 3, 5])):
            with self.subTest(data=data), self.assertRaises(ValueError):
                protocol.parse_packet(data)
