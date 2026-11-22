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
from .storage import MAX_MESSAGES, default_path, export_messages, load_messages, save_messages


class MonitorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("MeshCore Monitor")
        self.root.geometry("1020x680")
        self.root.minsize(720, 480)
        self.events = queue.Queue()
        self.path = default_path()
        self.messages = []
        self.storage_ready = True
        self.devices = []
        self.connection = None
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
        self.render()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self._process_events)

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

        tools = ttk.Frame(outer)
        tools.pack(fill="x")
        ttk.Label(tools, text="Recent activity", font=("TkDefaultFont", 13, "bold")).pack(side="left")
        self.count = tk.StringVar()
        ttk.Label(tools, textvariable=self.count).pack(side="left", padx=8)
        ttk.Button(tools, text="Clear history", command=self.clear).pack(side="right")
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
        self.state = "connecting"
        self.scan_button.config(state="disabled")
        self.device_choice.config(state="disabled")
        self.connect_button.config(text="Connecting...", state="disabled")
        self.status.set("Connecting...")

        async def connect():
            connection = MeshConnection(
                device,
                lambda packet: self.events.put(("packet", packet)),
                lambda status, detail: self.events.put(("status", (status, detail))),
                lambda error: self.events.put(("error", error)),
            )
            await connection.run()

        self.connection = asyncio.run_coroutine_threadsafe(connect(), self.loop)

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
                    elif self.state == "connecting":
                        self.connect_button.config(text="Connecting...", state="disabled")
                    elif self.state == "connected":
                        self.connect_button.config(text="Disconnect", state="normal")
                elif event == "error":
                    self.notice.set(f"Bluetooth error: {value}")
                elif event == "packet":
                    self.on_packet(value)
        except queue.Empty:
            pass
        self.root.after(100, self._process_events)

    def on_packet(self, packet):
        kind = packet["type"]
        if kind == "self":
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
            if self.storage_ready:
                try:
                    save_messages(self.path, self.messages)
                except OSError as error:
                    self.notice.set(f"Message received, but activity could not be saved: {error}")
            self.render()

    def render(self):
        self.table.delete(*self.table.get_children())
        query = self.search.get().strip().lower()
        selected = self.filter.current()
        visible = 0
        for entry in self.messages:
            packet = entry["packet"]
            if selected == 1 and packet.get("kind") != "Channel":
                continue
            if selected == 2 and packet.get("kind") != "Contact":
                continue
            if selected == 3 and packet.get("type") != "datagram":
                continue
            if query and not any(query in str(packet.get(key, "")).lower()
                                 for key in ("sender", "text", "kind", "type")):
                continue
            timestamp = packet.get("timestamp") or entry["receivedAt"] / 1000
            try:
                date = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, OSError, OverflowError):
                date = "Invalid timestamp"
            sender = packet.get("sender", "")
            if packet.get("kind") == "Contact":
                sender = f"Contact {sender}"
            if packet.get("type") == "datagram":
                text = f"Binary datagram | type 0x{packet['dataType']:04x} | {packet['length']} bytes"
            else:
                text = packet.get("text") or "(Empty message)"
                if packet.get("snr") is not None:
                    text += f"  (SNR {packet['snr']} dB)"
            self.table.insert("", "end", values=(date, sender, text))
            visible += 1
        self.count.set(f"{visible} of {len(self.messages)} shown")

    def clear(self):
        if not messagebox.askyesno("Clear history", "Delete all locally saved activity?", parent=self.root):
            return
        try:
            save_messages(self.path, [])
        except OSError as error:
            self.notice.set(f"Could not clear saved activity: {error}")
            return
        self.messages = []
        self.storage_ready = True
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
        self.root.destroy()


def main():
    root = tk.Tk()
    MonitorApp(root)
    root.mainloop()
