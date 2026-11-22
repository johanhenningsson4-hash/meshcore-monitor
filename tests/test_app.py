import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from meshcore_monitor.app import MonitorApp


class AppTests(unittest.TestCase):
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
