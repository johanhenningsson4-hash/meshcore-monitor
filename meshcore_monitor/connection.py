"""Asynchronous BLE connection, requests, queue draining, and reconnection."""

import asyncio
import inspect
import time

from bleak import BleakClient, BleakScanner

from . import protocol


class DeviceRejectedError(RuntimeError):
    pass


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
        self.contacts = None
        self.contacts_started = False
        self.radio_id = None
        self.max_channels = None
        self.request_lock = asyncio.Lock()
        self.ready = False
        self.notification_error = None
        self.last_timestamp = 0
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
        elif self.pending and not self.pending.done() and self.contacts is not None and packet["type"] in (
            "contacts_start", "contact", "contacts_end"
        ):
            if packet["type"] == "contacts_start" and not self.contacts_started:
                self.contacts_started = True
            elif packet["type"] == "contact" and self.contacts_started:
                self.contacts.append(packet)
            elif packet["type"] == "contacts_end" and self.contacts_started:
                self.pending.set_result({"type": "contacts", "contacts": self.contacts})
            else:
                self.pending.set_exception(ValueError("Invalid contact list response from device."))
        elif self.pending and not self.pending.done() and (
            packet["type"] in self.expected or packet["type"] == "error"
        ):
            if packet["type"] == "error":
                code = packet["code"]
                suffix = f" (code {code})" if code is not None else ""
                self.pending.set_exception(DeviceRejectedError(f"Device rejected the request{suffix}."))
            else:
                if packet["type"] == "self":
                    self.radio_id = packet["publicKey"]
                elif packet["type"] == "device":
                    self.max_channels = packet["maxChannels"]
                elif packet["type"] in ("message", "datagram"):
                    packet["radioId"] = self.radio_id
                self.pending.set_result(packet)

    async def request(self, command, expected):
        client = self.client
        async with self.request_lock:
            if (self.disconnected or not client or client is not self.client
                    or not client.is_connected):
                raise ConnectionError("Device is disconnected.")
            if self.notification_error:
                raise self.notification_error
            return await self._request(command, expected)

    async def _request(self, command, expected, *, contacts=False, timeout=None):
        self.pending = self.loop.create_future()
        self.expected = expected
        self.contacts = [] if contacts else None
        self.contacts_started = False
        try:
            async def exchange():
                await self.client.write_gatt_char(protocol.RX, command, response=True)
                packet = await self.pending
                if packet["type"] != "contacts":
                    result = self.on_packet(packet)
                    if inspect.isawaitable(result):
                        await result
                return packet

            try:
                return await asyncio.wait_for(exchange(), timeout if timeout is not None else self.timeout)
            except asyncio.TimeoutError as error:
                raise TimeoutError("Device did not respond. Reconnect and try again.") from error
        finally:
            if not self.pending.done():
                self.pending.cancel()
            elif not self.pending.cancelled():
                self.pending.exception()
            self.pending = None
            self.expected = ()
            self.contacts = None

    async def read_radio_names(self):
        if not self.ready:
            raise ConnectionError("Connect to a radio before loading names.")
        client = self.client
        radio_id = self.radio_id
        try:
            async with self.request_lock:
                if not self.ready or self.client is not client or not client.is_connected:
                    raise ConnectionError("Device disconnected while loading names.")
                packet = await self._request(protocol.CONTACTS, (), contacts=True, timeout=60)
            contacts = {}
            ambiguous = set()
            for contact in packet["contacts"]:
                prefix = contact["publicKey"][:12]
                if prefix in contacts:
                    ambiguous.add(prefix)
                else:
                    contacts[prefix] = contact["name"]
            for prefix in ambiguous:
                del contacts[prefix]
            channels = {}
            if self.max_channels is None:
                return {"radioId": radio_id, "contacts": contacts, "channels": channels,
                        "warning": "Radio did not report its channel count; channel names are unavailable."}
            for index in range(self.max_channels):
                if not self.ready or self.client is not client:
                    raise ConnectionError("Device disconnected while loading names.")
                channel = await self.request(bytes([0x1F, index]), ("channel",))
                if channel["index"] != index:
                    raise ValueError("Radio returned a different channel than requested.")
                if channel["name"]:
                    channels[str(index)] = channel["name"]
            return {"radioId": radio_id, "contacts": contacts, "channels": channels}
        except DeviceRejectedError:
            raise
        except Exception as error:
            if self.client is client and not self.disconnected:
                self.notification_error = error
                self.wakeup.set()
            raise

    async def send_message(self, destination_type, destination, message):
        if not self.ready:
            raise ConnectionError("Connect to a radio before sending.")
        timestamp = max(int(time.time()), self.last_timestamp + 1)
        command = protocol.build_message(destination_type, destination, message, timestamp)
        self.last_timestamp = timestamp
        try:
            await self.request(command, ("ok",) if destination_type == "channel" else ("sent",))
        except DeviceRejectedError:
            raise
        except Exception as error:
            self.notification_error = error
            self.wakeup.set()
            raise
        return timestamp

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
                self.ready = False
                self.radio_id = None
                self.max_channels = None
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
                    self.ready = True
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
                    self.ready = False
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
