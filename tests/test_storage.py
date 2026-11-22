import json
import tempfile
import unittest
from pathlib import Path

from meshcore_monitor.storage import export_messages, load_messages, save_messages


class StorageTests(unittest.TestCase):
    def test_persistence_limit_clear_and_export(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data" / "activity.json"
            self.assertEqual(load_messages(path), [])
            entries = [{"receivedAt": index, "packet": {"type": "message", "text": "hello"}}
                       for index in range(510)]
            save_messages(path, entries)
            self.assertEqual(load_messages(path), entries[:500])
            export = Path(directory) / "export.json"
            export_messages(export, load_messages(path))
            payload = json.loads(export.read_text(encoding="utf-8"))
            self.assertEqual(payload["application"], "MeshCore Monitor")
            self.assertEqual(payload["messages"], entries[:500])
            save_messages(path, [])
            self.assertEqual(load_messages(path), [])

    def test_invalid_saved_data_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "activity.json"
            path.write_text('{"bad": true}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_messages(path)
            self.assertEqual(path.read_text(encoding="utf-8"), '{"bad": true}')
