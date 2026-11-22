"""Asynchronous BLE connection, requests, queue draining, and reconnection."""

import asyncio

from bleak import BleakClient, BleakScanner

from . import protocol


async def scan_devices():
    devices = await BleakScanner.discover(timeout=8)
    return sorted(devices, key=lambda device: (device.name or "").lower())


class MeshConnection:
    def __init__(self, device, on_packet, on_status, on_error, *, client_factory=BleakClient,
                 timeout=5, poll_interval=30, retry_delay=1, max_retries=5):
        self.device = device
        self.on_packet = on_packet
        self.on_status = on_status
        self.on_error = on_error
        self.client_factory = client_factory
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.retry_delay = retry_delay
        self.max_retries = max_retries
        self.client = None
        self.pending = None
        self.expected = ()
        self.wakeup = asyncio.Event()
        self.disconnected = False
        self.loop = asyncio.get_running_loop()

    def _disconnected(self, client):
        self.loop.call_soon_threadsafe(self._handle_disconnect, client)

    def _handle_disconnect(self, client):
        if client is not self.client:
            return
        self.disconnected = True
        self.wakeup.set()
        if self.pending and not self.pending.done():
            self.pending.set_exception(ConnectionError("Device disconnected during a request."))

    def _notification(self, _sender, data):
        self.loop.call_soon_threadsafe(self._handle_notification, bytes(data))

    def _handle_notification(self, data):
        try:
            packet = protocol.parse_packet(data)
        except ValueError as error:
            if self.pending and not self.pending.done():
                self.pending.set_exception(error)
            else:
                self.notification_error = error
                self.wakeup.set()
            return
        if packet["type"] == "waiting":
            self.wakeup.set()
        elif self.pending and not self.pending.done() and (
            packet["type"] in self.expected or packet["type"] == "error"
        ):
            if packet["type"] == "error":
                code = packet["code"]
                suffix = f" (code {code})" if code is not None else ""
                self.pending.set_exception(RuntimeError(f"Device rejected the request{suffix}."))
            else:
                self.on_packet(packet)
                self.pending.set_result(packet)

    async def request(self, command, expected):
        if self.disconnected or not self.client or not self.client.is_connected:
            raise ConnectionError("Device is disconnected.")
        if self.pending:
            raise RuntimeError("A device request is already in progress.")
        self.pending = self.loop.create_future()
        self.expected = expected
        try:
            async def exchange():
                await self.client.write_gatt_char(protocol.RX, command, response=True)
                return await self.pending

            try:
                return await asyncio.wait_for(exchange(), self.timeout)
            except asyncio.TimeoutError as error:
                raise TimeoutError("Device did not respond. Reconnect and try again.") from error
        finally:
            if not self.pending.done():
                self.pending.cancel()
            elif not self.pending.cancelled():
                self.pending.exception()
            self.pending = None
            self.expected = ()

    async def refresh(self):
        await self.request(protocol.BATTERY, ("battery",))
        while True:
            if self.notification_error:
                raise self.notification_error
            self.wakeup.clear()
            while True:
                packet = await self.request(protocol.NEXT, ("message", "datagram", "empty"))
                if packet["type"] == "empty":
                    break
            if not self.wakeup.is_set():
                break

    async def run(self):
        retries = 0
        reconnecting = False
        self.on_status("connecting", "Connecting to companion radio...")
        try:
            while True:
                self.disconnected = False
                self.notification_error = None
                self.wakeup.clear()
                client = self.client_factory(self.device, disconnected_callback=self._disconnected)
                self.client = client
                try:
                    await client.connect()
                    await client.start_notify(protocol.TX, self._notification)
                    await self.request(protocol.START, ("self",))
                    await self.request(protocol.DEVICE, ("device",))
                    await self.request(protocol.BATTERY, ("battery",))
                    retries = 0
                    reconnecting = False
                    self.on_status("connected", self.device.name or "Companion radio connected")
                    await self.refresh()
                    while not self.disconnected:
                        try:
                            await asyncio.wait_for(self.wakeup.wait(), self.poll_interval)
                        except asyncio.TimeoutError:
                            pass
                        if self.notification_error:
                            raise self.notification_error
                        if not self.disconnected:
                            await self.refresh()
                    raise ConnectionError("Device disconnected.")
                except asyncio.CancelledError:
                    raise
                except Exception:
                    if not self.disconnected and not reconnecting:
                        raise
                    reconnecting = True
                finally:
                    if client.is_connected:
                        await client.disconnect()
                    self.client = None
                retries += 1
                if retries > self.max_retries:
                    raise ConnectionError(f"Could not reconnect after {self.max_retries} attempts.")
                self.on_status("connecting", f"Device disconnected. Reconnecting ({retries}/{self.max_retries})...")
                await asyncio.sleep(self.retry_delay * (2 ** (retries - 1)))
        except asyncio.CancelledError:
            pass
        except Exception as error:
            self.on_error(str(error))
        finally:
            self.on_status("disconnected", "Select a radio to connect.")
