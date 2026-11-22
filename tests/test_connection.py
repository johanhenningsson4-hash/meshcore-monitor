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


class MonitorEvent(asyncio.Event):
    def __init__(self):
        super().__init__()
        self.waiting = asyncio.Event()

    async def wait(self):
        self.waiting.set()
        return await super().wait()


class ConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_next_message_waits_until_activity_is_saved(self):
        release = asyncio.Event()
        saved = asyncio.Event()
        writes = []
        client = FakeClient(None, None, [MESSAGE, EMPTY], writes)
        client.is_connected = True

        async def persist(packet):
            if packet["type"] == "message":
                saved.set()
                await release.wait()

        connection = MeshConnection(SimpleNamespace(name="Radio"), persist,
                                    lambda *s: None, lambda e: None)
        connection.client = client
        client.callback = connection._notification

        async def drain():
            await connection.request(bytes([10]), ("message", "empty"))
            await connection.request(bytes([10]), ("message", "empty"))

        task = asyncio.create_task(drain())
        await saved.wait()
        self.assertEqual(writes, [10])
        release.set()
        await task
        self.assertEqual(writes, [10, 10])

    async def test_failed_activity_save_stops_drain(self):
        writes = []
        client = FakeClient(None, None, [BATTERY, MESSAGE, EMPTY], writes)
        client.is_connected = True

        async def persist(packet):
            if packet["type"] == "message":
                raise OSError("disk full")

        connection = MeshConnection(SimpleNamespace(name="Radio"), persist, lambda *s: None, lambda e: None)
        connection.client = client
        client.callback = connection._notification
        with self.assertRaisesRegex(OSError, "disk full"):
            await connection.refresh()
        self.assertEqual(writes, [0x14, 0x0A])

    async def test_reads_streamed_contacts_and_all_reported_channels(self):
        prefix = bytes.fromhex("010203040506")

        def contact(key, name):
            return bytes([3]) + key + bytes(3 + 64) + name.encode().ljust(32, b"\0")

        class NamesClient(FakeClient):
            async def write_gatt_char(self, _uuid, data, response):
                self.writes.append(data)
                if data == bytes([4]):
                    frames = [bytes([2, 3, 0, 0, 0]), contact(prefix + bytes(26), "Alice"),
                              contact(bytes.fromhex("111213141516") + bytes(26), "Bob"),
                              contact(bytes.fromhex("111213141516") + bytes([1]) * 26, "Other Bob"),
                              bytes([4, 0, 0, 0, 0])]
                else:
                    name = b"Public" if data[1] == 0 else b""
                    frames = [bytes([0x12, data[1]]) + name.ljust(32, b"\0") + bytes(16)]
                for frame in frames:
                    self.callback(None, frame)

        writes = []
        client = NamesClient(None, None, [], writes)
        client.is_connected = True
        connection = MeshConnection(SimpleNamespace(name="Radio"), lambda p: None,
                                    lambda *s: None, lambda e: None)
        connection.client = client
        connection.ready = True
        connection.radio_id = "radio"
        connection.max_channels = 2
        client.callback = connection._notification
        names = await connection.read_radio_names()
        self.assertEqual(names, {"radioId": "radio", "contacts": {"010203040506": "Alice"},
                                 "channels": {"0": "Public"}})
        self.assertEqual(writes, [bytes([4]), bytes([0x1F, 0]), bytes([0x1F, 1])])
        connection.max_channels = None
        names = await connection.read_radio_names()
        self.assertEqual(names["contacts"], {"010203040506": "Alice"})
        self.assertIn("channel names are unavailable", names["warning"])

    async def test_name_query_timeout_stops_using_ambiguous_transport(self):
        client = FakeClient(None, None, [None], [])
        client.is_connected = True
        connection = MeshConnection(SimpleNamespace(name="Radio"), lambda p: None,
                                    lambda *s: None, lambda e: None, timeout=0.01)
        connection.client = client
        connection.ready = True
        connection.radio_id = "radio"
        connection.max_channels = 1
        client.callback = connection._notification
        client.replies = [bytes([2, 0, 0, 0, 0])]
        original_write = client.write_gatt_char

        async def write(_uuid, data, response):
            if data[0] == 4:
                client.callback(None, bytes([2, 0, 0, 0, 0]))
                client.callback(None, bytes([4, 0, 0, 0, 0]))
            else:
                client.replies = [None]
                await original_write(_uuid, data, response)

        client.write_gatt_char = write
        with self.assertRaises(TimeoutError):
            await connection.read_radio_names()
        self.assertIsInstance(connection.notification_error, TimeoutError)

    async def test_send_waits_for_monitoring_request_and_handles_both_responses(self):
        class ControlledClient(FakeClient):
            async def write_gatt_char(self, _uuid, data, response):
                self.writes.append(data)
                if data == bytes([0x14]):
                    self.started.set()
                elif data[0] == 3:
                    self.callback(None, bytes([0]))
                else:
                    self.callback(None, bytes([6, 0]) + bytes(8))

        writes = []
        client = ControlledClient(None, None, [], writes)
        client.started = asyncio.Event()
        client.is_connected = True
        connection = MeshConnection(SimpleNamespace(name="Radio"), lambda p: None,
                                    lambda *s: None, lambda e: None)
        connection.client = client
        connection.ready = True
        client.callback = connection._notification
        battery = asyncio.create_task(connection.request(bytes([0x14]), ("battery",)))
        await client.started.wait()
        channel = asyncio.create_task(connection.send_message("channel", 1, "Hello"))
        await asyncio.sleep(0.01)
        self.assertEqual([frame[0] for frame in writes], [0x14])
        client.callback(None, BATTERY)
        await battery
        first_timestamp = await channel
        second_timestamp = await connection.send_message("contact", "010203040506", "Hi")
        self.assertEqual([frame[0] for frame in writes], [0x14, 3, 2])
        self.assertEqual(writes[-1][7:13], bytes.fromhex("010203040506"))
        self.assertGreater(second_timestamp, first_timestamp)

    async def test_rejected_send_and_timeout_are_reported(self):
        for response, error_type in ((bytes([1, 2]), RuntimeError), (None, TimeoutError)):
            with self.subTest(response=response):
                errors = []
                client = FakeClient(None, None, [response], [])
                client.is_connected = True
                connection = MeshConnection(SimpleNamespace(name="Radio"), lambda p: None,
                                            lambda *s: None, errors.append, timeout=1)
                connection.client = client
                connection.ready = True
                client.callback = connection._notification
                with self.assertRaises(error_type):
                    await connection.send_message("channel", 0, "Hello")
                if response is None:
                    self.assertIsInstance(connection.notification_error, TimeoutError)
                else:
                    self.assertIsNone(connection.notification_error)

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
        connection.wakeup = MonitorEvent()
        task = asyncio.create_task(connection.run())
        await asyncio.wait_for(connection.wakeup.waiting.wait(), 5)
        self.assertEqual(writes, [1, 0x16, 0x14, 0x14, 0x0A, 0x0A])
        self.assertEqual([p["text"] for p in packets if p["type"] == "message"], ["Hi"])
        connection.wakeup.waiting.clear()
        clients[0].callback(None, bytes([0x83]))
        await asyncio.wait_for(connection.wakeup.waiting.wait(), 5)
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
                                            client_factory=factory, timeout=1)
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
        connection.wakeup = MonitorEvent()
        task = asyncio.create_task(connection.run())
        await asyncio.wait_for(connection.wakeup.waiting.wait(), 5)
        connection.wakeup.waiting.clear()
        clients[0].drop()
        await asyncio.wait_for(connection.wakeup.waiting.wait(), 5)
        self.assertEqual(len(writes), 10)
        self.assertEqual(len(clients), 3)
        self.assertEqual([s[0] for s in statuses].count("connected"), 2)
        self.assertFalse(errors)
        task.cancel()
        await task
