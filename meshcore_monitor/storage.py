"""Local activity history, compatible with the web dashboard's export format."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

MAX_MESSAGES = 500


def default_path():
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "meshcore-monitor" / "activity.json"


def load_messages(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as file:
        messages = json.load(file)
    return _validate_messages(messages)


def _validate_messages(messages):
    if not isinstance(messages, list) or not all(
        isinstance(entry, dict)
        and isinstance(entry.get("packet"), dict)
        and isinstance(entry.get("receivedAt"), (int, float))
        for entry in messages
    ):
        raise ValueError("Saved activity data is invalid.")
    return messages[:MAX_MESSAGES]


def load_backup(path):
    with Path(path).open(encoding="utf-8") as file:
        payload = json.load(file)
    if isinstance(payload, dict) and payload.get("application") == "MeshCore Monitor":
        payload = payload.get("messages")
    return _validate_messages(payload)


def save_messages(path, messages):
    _write_json(path, messages[:MAX_MESSAGES])


def _sync_directory(path):
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temp = Path(file.name)
            json.dump(value, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        temp.replace(path)
        _sync_directory(path.parent)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()


def backup_before_clear(path, messages):
    path = Path(path)
    directory = path.parent / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    if path.exists():
        with path.open("rb") as source, NamedTemporaryFile(
            "wb", dir=directory, prefix=f"activity-{timestamp}-", suffix=".original", delete=False
        ) as backup:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                backup.write(chunk)
            backup.flush()
            os.fsync(backup.fileno())
        _sync_directory(directory)
    with NamedTemporaryFile(
        "w", encoding="utf-8", dir=directory, prefix=f"activity-{timestamp}-", suffix=".json", delete=False
    ) as backup:
        json.dump({"exportedAt": datetime.now(timezone.utc).isoformat(),
                   "application": "MeshCore Monitor", "messages": messages}, backup, ensure_ascii=False, indent=2)
        backup.flush()
        os.fsync(backup.fileno())
        backup_path = Path(backup.name)
    _sync_directory(directory)
    return backup_path


def load_names(path):
    path = Path(path)
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as file:
        names = json.load(file)
    if not isinstance(names, dict) or not all(
        isinstance(radio, str) and isinstance(data, dict)
        and all(isinstance(data.get(kind), dict) and all(
            isinstance(key, str) and isinstance(name, str) for key, name in data[kind].items()
        ) for kind in ("contacts", "channels"))
        for radio, data in names.items()
    ):
        raise ValueError("Saved radio names are invalid.")
    return names


def save_names(path, names):
    _write_json(path, names)


def export_messages(path, messages):
    payload = {
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "application": "MeshCore Monitor",
        "messages": messages,
    }
    with Path(path).open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
