import struct
import unittest

from meshcore_monitor import protocol


class ProtocolTests(unittest.TestCase):
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
