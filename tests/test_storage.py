import json
import tempfile
import unittest
from pathlib import Path

from unittest.mock import patch

from meshcore_monitor.storage import (
    backup_before_clear, export_messages, load_backup, load_messages, load_names, save_messages, save_names,
)


class StorageTests(unittest.TestCase):
    def test_backup_copies_disk_and_unsaved_memory_before_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "activity.json"
            original = b'{"bad": "preserve exactly"}'
            path.write_bytes(original)
            messages = [{"receivedAt": 1, "packet": {"type": "message", "text": "unsaved"}}]
            backup = backup_before_clear(path, messages)
            self.assertEqual(json.loads(backup.read_text(encoding="utf-8"))["messages"], messages)
            self.assertEqual(load_backup(backup), messages)
            originals = list((path.parent / "backups").glob("*.original"))
            self.assertEqual(len(originals), 1)
            self.assertEqual(originals[0].read_bytes(), original)
            save_messages(path, [])
            self.assertEqual(load_messages(path), [])

    def test_write_sync_failure_is_reported_without_replacing_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "activity.json"
            save_messages(path, [{"receivedAt": 1, "packet": {}}])
            with patch("meshcore_monitor.storage.os.fsync", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    save_messages(path, [])
            self.assertEqual(len(load_messages(path)), 1)

    def test_radio_name_cache_roundtrip_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "names.json"
            names = {"radio": {"contacts": {"010203040506": "Alice"}, "channels": {"0": "Public"}}}
            save_names(path, names)
            self.assertEqual(load_names(path), names)
            path.write_text('{"radio": {"contacts": []}}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_names(path)

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
