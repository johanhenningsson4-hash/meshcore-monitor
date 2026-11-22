import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch
from unittest.mock import AsyncMock

from meshcore_monitor.app import MonitorApp


class AppTests(unittest.TestCase):
    def test_backup_failure_prevents_clear_and_radio_names_are_scoped(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        root.withdraw()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "activity.json"
            with patch("meshcore_monitor.app.default_path", return_value=path):
                app = MonitorApp(root)
                try:
                    app.names = {"r1": {"contacts": {"010203040506": "Alice"}, "channels": {"1": "Local"}},
                                 "r2": {"contacts": {"010203040506": "Other"}, "channels": {"1": "Elsewhere"}}}
                    app.radio_id = "r1"
                    app.update_destinations()
                    self.assertEqual(app.destination_values()["Local [1]"], "1")
                    app.on_packet({"type": "message", "sender": "010203040506", "kind": "Contact",
                                   "text": "Hi", "timestamp": 1, "snr": None, "radioId": "r1"})
                    self.assertIn("Alice", app.table.item("0", "values")[1])
                    app.table.selection_set("0")
                    app.select_message(None)
                    self.assertIn("Alice [010203040506]", app.destination_choice["values"])
                    app.search.set("Alice")
                    self.assertEqual(len(app.table.get_children()), 1)
                    with patch("meshcore_monitor.app.messagebox.askyesno", return_value=True), \
                         patch("meshcore_monitor.app.backup_before_clear", side_effect=OSError("disk full")):
                        app.clear()
                    self.assertEqual(len(app.messages), 1)
                    self.assertIn("disk full", app.notice.get())
                    self.assertTrue(path.exists())
                    with patch("meshcore_monitor.app.messagebox.askyesno", return_value=True):
                        app.clear()
                    self.assertEqual(app.messages, [])
                    backup = next((path.parent / "backups").glob("*.json"))
                    with patch("meshcore_monitor.app.filedialog.askopenfilename", return_value=str(backup)), \
                         patch("meshcore_monitor.app.messagebox.askyesno", return_value=True):
                        app.restore()
                    self.assertEqual(len(app.messages), 1)
                    self.assertEqual(app.messages[0]["packet"]["text"], "Hi")
                finally:
                    app.close()

    def test_send_and_select_contact(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        root.withdraw()
        with tempfile.TemporaryDirectory() as directory:
            with patch("meshcore_monitor.app.default_path", return_value=Path(directory) / "activity.json"):
                app = MonitorApp(root)
                try:
                    app.on_packet({"type": "message", "sender": "010203040506", "kind": "Contact",
                                   "text": "Hi", "timestamp": 1, "snr": None})
                    app.table.selection_set("0")
                    app.select_message(None)
                    self.assertEqual(app.destination.get(), "010203040506")
                    self.assertEqual(app.destination_type.get(), "Contact")
                    app.radio_connection = type("Radio", (), {
                        "send_message": AsyncMock(return_value=42), "radio_id": "test-radio"
                    })()
                    app.state = "connected"
                    app.message_text.set("Reply")
                    app.send_message()
                    deadline = time.monotonic() + 2
                    while app.sending and time.monotonic() < deadline:
                        root.update()
                        time.sleep(0.01)
                    self.assertFalse(app.sending)
                    self.assertEqual(app.messages[0]["packet"]["text"], "Reply")
                    self.assertTrue(app.messages[0]["packet"]["outgoing"])
                    self.assertIn("delivery is not confirmed", app.notice.get())
                    app.radio_connection.send_message.assert_awaited_once_with("contact", "010203040506", "Reply")
                finally:
                    app.close()

    def test_activity_is_shown_filtered_and_restored(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        root.withdraw()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "activity.json"
            with patch("meshcore_monitor.app.default_path", return_value=path):
                app = MonitorApp(root)
                try:
                    app.on_packet({"type": "message", "sender": "Channel 1", "kind": "Channel",
                                   "text": "hello", "timestamp": 1, "snr": None})
                    self.assertEqual(len(app.table.get_children()), 1)
                    app.search.set("not found")
                    self.assertEqual(len(app.table.get_children()), 0)
                    app.search.set("hello")
                    self.assertEqual(len(app.table.get_children()), 1)
                finally:
                    app.close()
                root = tk.Tk()
                root.withdraw()
                restored = MonitorApp(root)
                try:
                    self.assertEqual(len(restored.table.get_children()), 1)
                finally:
                    restored.close()
