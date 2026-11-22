import asyncio
import unittest
from types import SimpleNamespace

from meshcore_monitor.connection import MeshConnection


SELF = bytes([5] + [0] * 57)
BATTERY = bytes([12, 0x74, 0x0E])
EMPTY = bytes([10])
MESSAGE = bytes([8, 1, 255, 0, 1, 0, 0, 0]) + b"Hi"


class FakeClient:
    def __init__(self, _device, disconnected_callback, replies, writes, fail_connect=False):
        self.disconnected_callback = disconnected_callback
        self.replies = replies
        self.writes = writes
        self.fail_connect = fail_connect
        self.is_connected = False

    async def connect(self):
        if self.fail_connect:
            raise OSError("Radio unavailable")
        self.is_connected = True

    async def start_notify(self, _uuid, callback):
        self.callback = callback

    async def write_gatt_char(self, _uuid, data, response):
        self.writes.append(data[0])
        reply = self.replies.pop(0)
        if reply is not None:
            self.callback(None, reply)

    async def disconnect(self):
        self.is_connected = False

    def drop(self):
        self.is_connected = False
        self.disconnected_callback(self)


class ConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_initialization_drain_and_waiting(self):
        replies = [SELF, bytes([13, 3]), BATTERY, BATTERY, MESSAGE, EMPTY, BATTERY, EMPTY]
        writes, packets, statuses, errors, clients = [], [], [], [], []

        def factory(device, disconnected_callback):
            client = FakeClient(device, disconnected_callback, replies, writes)
            clients.append(client)
            return client

        connection = MeshConnection(SimpleNamespace(name="Radio"), packets.append,
                                    lambda *status: statuses.append(status), errors.append,
                                    client_factory=factory, poll_interval=60)
        task = asyncio.create_task(connection.run())
        for _ in range(100):
            if len(writes) >= 6 and connection.pending is None:
                break
            await asyncio.sleep(0.001)
        self.assertEqual(writes, [1, 0x16, 0x14, 0x14, 0x0A, 0x0A])
        self.assertEqual([p["text"] for p in packets if p["type"] == "message"], ["Hi"])
        clients[0].callback(None, bytes([0x83]))
        for _ in range(100):
            if len(writes) >= 8:
                break
            await asyncio.sleep(0.001)
        self.assertEqual(writes[-2:], [0x14, 0x0A])
        task.cancel()
        await task
        self.assertEqual([status[0] for status in statuses], ["connecting", "connected", "disconnected"])
        self.assertFalse(errors)
        self.assertFalse(clients[0].is_connected)

    async def test_timeout_and_malformed_response_stop_monitoring(self):
        for reply, expected in ((None, "did not respond"), (bytes([5]), "Incomplete")):
            with self.subTest(reply=reply):
                errors, statuses, writes = [], [], []
                factory = lambda device, disconnected_callback: FakeClient(
                    device, disconnected_callback, [reply], writes
                )
                connection = MeshConnection(SimpleNamespace(name="Radio"), lambda p: None,
                                            lambda *s: statuses.append(s), errors.append,
                                            client_factory=factory, timeout=0.01)
                await connection.run()
                self.assertIn(expected, errors[0])
                self.assertEqual(statuses[-1][0], "disconnected")

    async def test_write_timeout_stops_monitoring(self):
        class HangingClient(FakeClient):
            async def write_gatt_char(self, _uuid, data, response):
                await asyncio.Event().wait()

        errors = []
        factory = lambda device, disconnected_callback: HangingClient(
            device, disconnected_callback, [], []
        )
        connection = MeshConnection(SimpleNamespace(name="Radio"), lambda p: None,
                                    lambda *s: None, errors.append,
                                    client_factory=factory, timeout=0.01)
        await connection.run()
        self.assertIn("did not respond", errors[0])

    async def test_reconnect_retries_failed_connection(self):
        writes, statuses, errors, clients = [], [], [], []
        replies = [SELF, bytes([13, 3]), BATTERY, BATTERY, EMPTY,
                   SELF, bytes([13, 3]), BATTERY, BATTERY, EMPTY]

        def factory(device, disconnected_callback):
            client = FakeClient(device, disconnected_callback, replies, writes, fail_connect=len(clients) == 1)
            clients.append(client)
            return client

        connection = MeshConnection(SimpleNamespace(name="Radio"), lambda p: None,
                                    lambda *s: statuses.append(s), errors.append,
                                    client_factory=factory, retry_delay=0.001, poll_interval=60)
        task = asyncio.create_task(connection.run())
        for _ in range(100):
            if len(writes) >= 5:
                break
            await asyncio.sleep(0.001)
        clients[0].drop()
        for _ in range(200):
            if len(writes) >= 10:
                break
            await asyncio.sleep(0.001)
        self.assertEqual(len(clients), 3)
        self.assertEqual([s[0] for s in statuses].count("connected"), 2)
        self.assertFalse(errors)
        task.cancel()
        await task
