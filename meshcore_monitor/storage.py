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
    if not isinstance(messages, list) or not all(
        isinstance(entry, dict)
        and isinstance(entry.get("packet"), dict)
        and isinstance(entry.get("receivedAt"), (int, float))
        for entry in messages
    ):
        raise ValueError("Saved activity data is invalid.")
    return messages[:MAX_MESSAGES]


def save_messages(path, messages):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temp = Path(file.name)
            json.dump(messages[:MAX_MESSAGES], file, ensure_ascii=False, indent=2)
        temp.replace(path)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()


def export_messages(path, messages):
    payload = {
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "application": "MeshCore Monitor",
        "messages": messages,
    }
    with Path(path).open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
