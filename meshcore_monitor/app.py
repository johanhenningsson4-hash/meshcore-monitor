"""Tk desktop interface; Bluetooth operations run on a separate asyncio thread."""

import asyncio
import concurrent.futures
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from .connection import MeshConnection, scan_devices
from .protocol import MAX_MESSAGE_BYTES
from .storage import (
    MAX_MESSAGES, backup_before_clear, default_path, export_messages, load_messages,
    load_backup, load_names, save_messages, save_names,
)


class MonitorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("MeshCore Monitor")
        self.root.geometry("1020x680")
        self.root.minsize(720, 480)
        self.events = queue.Queue()
        self.path = default_path()
        self.names_path = self.path.with_name("radio-names.json")
        self.messages = []
        self.storage_ready = True
        self.names_ready = True
        self.names = {}
        self.radio_id = None
        self.devices = []
        self.connection = None
        self.radio_connection = None
        self.sending = False
        self.state = "disconnected"
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        self._build_ui()
        try:
            self.messages = load_messages(self.path)
        except (OSError, ValueError) as error:
            self.storage_ready = False
            self.notice.set(f"Saved activity could not be loaded: {error}. Clear history to enable saving.")
        try:
            self.names = load_names(self.names_path)
        except (OSError, ValueError) as error:
            self.names_ready = False
            self.notice.set(f"Saved radio names could not be loaded: {error}. Names will not be overwritten.")
        self.render()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.event_timer = self.root.after(100, self._process_events)

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()
        self.loop.close()

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="MeshCore Monitor", font=("TkDefaultFont", 20, "bold")).pack(anchor="w")
        self.notice = tk.StringVar(value=(
            "Connecting removes queued messages from the radio; another companion app may not receive them. "
            "History is stored locally."
        ))
        ttk.Label(outer, textvariable=self.notice, wraplength=950).pack(anchor="w", pady=(4, 12))

        controls = ttk.Frame(outer)
        controls.pack(fill="x")
        self.scan_button = ttk.Button(controls, text="Scan for radios", command=self.scan)
        self.scan_button.pack(side="left")
        self.device_choice = ttk.Combobox(controls, state="readonly", width=48)
        self.device_choice.pack(side="left", fill="x", expand=True, padx=8)
        self.connect_button = ttk.Button(controls, text="Connect", command=self.toggle_connection)
        self.connect_button.pack(side="left")
        self.status = tk.StringVar(value="Disconnected")
        ttk.Label(outer, textvariable=self.status).pack(anchor="w", pady=(8, 10))

        metrics = ttk.Frame(outer)
        metrics.pack(fill="x", pady=(0, 12))
        self.battery = tk.StringVar(value="Battery: --")
        self.radio = tk.StringVar(value="Radio: --")
        self.firmware = tk.StringVar(value="Firmware: --")
        for variable in (self.battery, self.radio, self.firmware):
            ttk.Label(metrics, textvariable=variable).pack(side="left", padx=(0, 24))

        composer = ttk.LabelFrame(outer, text="Send message", padding=8)
        composer.pack(fill="x", pady=(0, 12))
        destinations = ttk.Frame(composer)
        destinations.pack(fill="x")
        self.destination_type = ttk.Combobox(destinations, state="readonly", width=12,
                                             values=("Channel", "Contact"))
        self.destination_type.current(0)
        self.destination_type.pack(side="left")
        self.destination_type.bind("<<ComboboxSelected>>", lambda _event: self.update_destinations())
        self.destination = tk.StringVar(value="0")
        self.destination_choice = ttk.Combobox(destinations, textvariable=self.destination, width=36)
        self.destination_choice.pack(side="left", padx=8)
        ttk.Label(destinations, text="Channel number or 12-digit contact key prefix").pack(side="left")
        message_row = ttk.Frame(composer)
        message_row.pack(fill="x", pady=(6, 0))
        self.message_text = tk.StringVar()
        ttk.Entry(message_row, textvariable=self.message_text).pack(side="left", fill="x", expand=True)
        self.send_button = ttk.Button(message_row, text="Send", command=self.send_message, state="disabled")
        self.send_button.pack(side="left", padx=(8, 0))
        ttk.Label(composer, text=f"Up to {MAX_MESSAGE_BYTES} UTF-8 bytes. Radio acceptance does not confirm delivery.").pack(anchor="w")

        tools = ttk.Frame(outer)
        tools.pack(fill="x")
        ttk.Label(tools, text="Recent activity", font=("TkDefaultFont", 13, "bold")).pack(side="left")
        self.count = tk.StringVar()
        ttk.Label(tools, textvariable=self.count).pack(side="left", padx=8)
        ttk.Button(tools, text="Clear history", command=self.clear).pack(side="right")
        ttk.Button(tools, text="Restore backup", command=self.restore).pack(side="right", padx=(8, 0))
        ttk.Button(tools, text="Export JSON", command=self.export).pack(side="right", padx=8)
        filters = ttk.Frame(outer)
        filters.pack(fill="x", pady=8)
        ttk.Label(filters, text="Search:").pack(side="left")
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self.render())
        ttk.Entry(filters, textvariable=self.search).pack(side="left", fill="x", expand=True, padx=8)
        self.filter = ttk.Combobox(filters, state="readonly", width=18,
                                   values=("All activity", "Channel messages", "Contact messages", "Binary datagrams"))
        self.filter.current(0)
        self.filter.pack(side="left")
        self.filter.bind("<<ComboboxSelected>>", lambda _event: self.render())
        table_frame = ttk.Frame(outer)
        table_frame.pack(fill="both", expand=True)
        self.table = ttk.Treeview(table_frame, columns=("time", "sender", "message"), show="headings")
        for column, title, width in (("time", "Time", 150), ("sender", "Sender", 150), ("message", "Message", 500)):
            self.table.heading(column, text=title)
            self.table.column(column, width=width, minwidth=80)
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.table.bind("<<TreeviewSelect>>", self.select_message)

    def select_message(self, _event):
        selected = self.table.selection()
        if not selected:
            return
        index = int(selected[0])
        packet = self.messages[index]["packet"]
        if packet.get("type") == "message" and packet.get("kind") == "Contact" and not packet.get("outgoing"):
            self.destination_type.set("Contact")
            self.destination.set(packet["sender"])
            self.update_destinations()

    def send_message(self):
        if self.state != "connected" or self.sending:
            return
        destination_type = self.destination_type.get().lower()
        destination = self.destination.get().strip()
        destination = self.destination_values().get(destination, destination)
        message = self.message_text.get()
        if destination_type == "channel":
            try:
                destination = int(destination, 10)
            except ValueError:
                self.notice.set("Enter a channel number between 0 and 255.")
                return
        self.sending = True
        self.send_button.config(state="disabled")
        self.notice.set("Sending message to radio...")

        async def send():
            try:
                if self.radio_connection is None:
                    raise ConnectionError("Connect to a radio before sending.")
                radio = self.radio_connection
                radio_id = radio.radio_id
                timestamp = await radio.send_message(destination_type, destination, message)
            except Exception as error:
                if isinstance(error, TimeoutError):
                    self.events.put(("send_error", "Radio did not respond; delivery outcome is unknown."))
                else:
                    self.events.put(("send_error", str(error)))
            else:
                self.events.put(("send_success", (destination_type, destination, message, timestamp, radio_id)))

        asyncio.run_coroutine_threadsafe(send(), self.loop)

    def scan(self):
        self.scan_button.config(state="disabled")
        self.connect_button.config(state="disabled")
        self.status.set("Scanning for Bluetooth devices (8 seconds)...")

        async def run_scan():
            try:
                self.events.put(("scan", await scan_devices()))
            except Exception as error:
                self.events.put(("scan_error", str(error)))

        asyncio.run_coroutine_threadsafe(run_scan(), self.loop)

    def toggle_connection(self):
        if self.connection and not self.connection.done():
            self.connect_button.config(state="disabled")
            self.send_button.config(state="disabled")
            self.connection.cancel()
            return
        index = self.device_choice.current()
        if index < 0:
            self.notice.set("Scan and select a companion radio first.")
            return
        device = self.devices[index]
        self.battery.set("Battery: --")
        self.radio.set("Radio: --")
        self.firmware.set("Firmware: --")
        self.radio_id = None
        self.update_destinations()
        self.state = "connecting"
        self.scan_button.config(state="disabled")
        self.device_choice.config(state="disabled")
        self.connect_button.config(text="Connecting...", state="disabled")
        self.status.set("Connecting...")

        async def connect():
            def publish(packet):
                if packet["type"] in ("message", "datagram"):
                    saved = self.loop.create_future()
                    self.events.put(("packet", (packet, saved)))
                    return saved
                self.events.put(("packet", (packet, None)))
                return None

            connection = MeshConnection(
                device,
                publish,
                lambda status, detail: self.events.put(("status", (status, detail))),
                lambda error: self.events.put(("error", error)),
            )
            self.radio_connection = connection
            try:
                await connection.run()
            finally:
                self.radio_connection = None

        self.connection = asyncio.run_coroutine_threadsafe(connect(), self.loop)

    def refresh_radio_names(self):
        async def refresh():
            try:
                if self.radio_connection is None:
                    raise ConnectionError("Connect to a radio before loading names.")
                names = await self.radio_connection.read_radio_names()
            except Exception as error:
                self.events.put(("names_error", str(error)))
            else:
                self.events.put(("names", names))

        asyncio.run_coroutine_threadsafe(refresh(), self.loop)

    def destination_values(self):
        radio_names = self.names.get(self.radio_id, {})
        if self.destination_type.get() == "Contact":
            return {f"{name} [{prefix}]": prefix for prefix, name in radio_names.get("contacts", {}).items()
                    if name}
        return {f"{name} [{index}]": index for index, name in radio_names.get("channels", {}).items()
                if name}

    def update_destinations(self):
        self.destination_choice["values"] = list(self.destination_values())

    def _process_events(self):
        try:
            while True:
                event, value = self.events.get_nowait()
                if event == "scan":
                    self.devices = value
                    self.device_choice["values"] = [
                        f"{device.name or 'Unnamed device'} ({device.address})" for device in value
                    ]
                    self.device_choice.set("")
                    if value:
                        self.device_choice.current(0)
                    self.status.set(f"Found {len(value)} Bluetooth device(s). Select your companion radio.")
                    self.scan_button.config(state="normal")
                    self.connect_button.config(state="normal")
                elif event == "scan_error":
                    self.status.set("Scan failed.")
                    self.notice.set(f"Bluetooth scan failed: {value}")
                    self.scan_button.config(state="normal")
                    self.connect_button.config(state="normal")
                elif event == "status":
                    self.state, detail = value
                    self.status.set(f"{self.state.capitalize()}: {detail}")
                    if self.state == "disconnected":
                        self.scan_button.config(state="normal")
                        self.device_choice.config(state="readonly")
                        self.connect_button.config(text="Connect", state="normal")
                        self.send_button.config(state="disabled")
                    elif self.state == "connecting":
                        self.connect_button.config(text="Connecting...", state="disabled")
                        self.send_button.config(state="disabled")
                    elif self.state == "connected":
                        self.connect_button.config(text="Disconnect", state="normal")
                        self.send_button.config(state="disabled" if self.sending else "normal")
                        self.refresh_radio_names()
                elif event == "error":
                    self.notice.set(f"Bluetooth error: {value}")
                elif event == "packet":
                    packet, saved = value
                    error = self.on_packet(packet)
                    if saved is not None:
                        def finish_save(future=saved, failure=error):
                            if not future.done():
                                if failure is None:
                                    future.set_result(None)
                                else:
                                    future.set_exception(failure)
                        self.loop.call_soon_threadsafe(finish_save)
                elif event == "names_error":
                    self.notice.set(f"Could not load radio names: {value}")
                elif event == "names":
                    radio_id = value["radioId"]
                    self.names[radio_id] = {"contacts": value["contacts"], "channels": value["channels"]}
                    warning = value.get("warning", "")
                    if self.names_ready:
                        try:
                            save_names(self.names_path, self.names)
                        except OSError as error:
                            warning = f"Radio names could not be saved: {error}. {warning}"
                    if warning:
                        self.notice.set(warning)
                    self.update_destinations()
                    self.render()
                elif event == "send_error":
                    self.sending = False
                    self.send_button.config(state="normal" if self.state == "connected" else "disabled")
                    self.notice.set(f"Could not send message: {value}")
                elif event == "send_success":
                    self.sending = False
                    self.send_button.config(state="normal" if self.state == "connected" else "disabled")
                    destination_type, destination, message, timestamp, radio_id = value
                    if self.message_text.get() == message:
                        self.message_text.set("")
                    self.notice.set("Radio accepted the message; delivery is not confirmed.")
                    self.on_packet({
                        "type": "message", "sender": str(destination) if destination_type == "contact"
                        else f"Channel {destination}", "kind": destination_type.capitalize(),
                        "text": message, "timestamp": timestamp, "snr": None, "outgoing": True,
                        "radioId": radio_id,
                    })
        except queue.Empty:
            pass
        self.event_timer = self.root.after(100, self._process_events)

    def on_packet(self, packet):
        kind = packet["type"]
        if kind == "self":
            self.radio_id = packet.get("publicKey")
            self.update_destinations()
            self.radio.set(
                f"Radio: {packet['name'] or 'Companion'} | {packet['frequency']:.3f} MHz | "
                f"SF{packet['spreadingFactor']} / {packet['bandwidth']} kHz"
            )
        elif kind == "device":
            version = packet["version"] or f"Protocol v{packet['protocolVersion']}"
            self.firmware.set(f"Firmware: {version}")
        elif kind == "battery":
            volts = packet["millivolts"]
            self.battery.set(f"Battery: {volts / 1000:.2f} V" if volts else "Battery: unavailable")
        elif kind in ("message", "datagram"):
            self.messages.insert(0, {"receivedAt": int(time.time() * 1000), "packet": packet})
            del self.messages[MAX_MESSAGES:]
            error = None
            if self.storage_ready:
                try:
                    save_messages(self.path, self.messages)
                except OSError as failure:
                    error = failure
            else:
                error = RuntimeError("Saved history could not be loaded.")
            self.render()
            if error is not None:
                self.notice.set(f"Activity could not be saved: {error}")
                return error

    def render(self):
        self.table.delete(*self.table.get_children())
        query = self.search.get().strip().lower()
        selected = self.filter.current()
        visible = 0
        for index, entry in enumerate(self.messages):
            packet = entry["packet"]
            if selected == 1 and packet.get("kind") != "Channel":
                continue
            if selected == 2 and packet.get("kind") != "Contact":
                continue
            if selected == 3 and packet.get("type") != "datagram":
                continue
            sender = self.sender_label(packet)
            if query and query not in sender.lower() and not any(
                query in str(packet.get(key, "")).lower() for key in ("sender", "text", "kind", "type")
            ):
                continue
            timestamp = packet.get("timestamp") or entry["receivedAt"] / 1000
            try:
                date = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, OSError, OverflowError):
                date = "Invalid timestamp"
            if packet.get("type") == "datagram":
                text = f"Binary datagram | type 0x{packet['dataType']:04x} | {packet['length']} bytes"
            else:
                text = packet.get("text") or "(Empty message)"
                if packet.get("snr") is not None:
                    text += f"  (SNR {packet['snr']} dB)"
            if packet.get("outgoing"):
                sender = f"To {sender}"
                text = f"[Radio accepted] {text}"
            self.table.insert("", "end", iid=str(index), values=(date, sender, text))
            visible += 1
        self.count.set(f"{visible} of {len(self.messages)} shown")

    def sender_label(self, packet):
        sender = packet.get("sender", "")
        radio_names = self.names.get(packet.get("radioId"), {})
        if packet.get("kind") == "Contact":
            name = radio_names.get("contacts", {}).get(sender.lower())
            return f"Contact {name} [{sender}]" if name else f"Contact {sender}"
        if sender.startswith("Channel "):
            number = sender[len("Channel "):]
            name = radio_names.get("channels", {}).get(number)
            if name:
                return f"Channel {name} [{number}]"
        return sender

    def clear(self):
        if not messagebox.askyesno("Clear history", "Back up and clear all locally saved activity?", parent=self.root):
            return
        try:
            backup = backup_before_clear(self.path, self.messages)
            save_messages(self.path, [])
        except OSError as error:
            self.notice.set(f"Could not clear saved activity: {error}")
            return
        self.messages = []
        self.storage_ready = True
        self.notice.set(f"History cleared. Backup saved to {backup}")
        self.render()

    def export(self):
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Export activity", defaultextension=".json",
            filetypes=[("JSON files", "*.json")], initialfile="meshcore-activity.json",
        )
        if path:
            try:
                export_messages(path, self.messages)
            except OSError as error:
                self.notice.set(f"Could not export activity: {error}")

    def restore(self):
        path = filedialog.askopenfilename(
            parent=self.root, title="Restore activity backup", initialdir=self.path.parent / "backups",
            filetypes=[("Activity backups", "*.json *.original"), ("All files", "*")],
        )
        if not path:
            return
        try:
            messages = load_backup(path)
        except (OSError, ValueError) as error:
            self.notice.set(f"Could not read backup: {error}")
            return
        if not messagebox.askyesno("Restore history", "Back up current activity and replace it with this backup?",
                                   parent=self.root):
            return
        try:
            backup = backup_before_clear(self.path, self.messages)
            save_messages(self.path, messages)
        except OSError as error:
            self.notice.set(f"Could not restore history: {error}")
            return
        self.messages = messages
        self.storage_ready = True
        self.notice.set(f"History restored. Previous activity backed up to {backup}")
        self.render()

    def close(self):
        async def shutdown():
            tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        future = asyncio.run_coroutine_threadsafe(shutdown(), self.loop)
        try:
            future.result(timeout=5)
        except concurrent.futures.TimeoutError:
            self.notice.set("Bluetooth shutdown timed out.")
            return
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)
        self.root.after_cancel(self.event_timer)
        self.root.destroy()


def main():
    root = tk.Tk()
    MonitorApp(root)
    root.mainloop()
