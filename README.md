# MeshCore Monitor

A local desktop application for a MeshCore **companion radio** over Bluetooth Low Energy. It shows connection and radio information and battery voltage, and sends and receives channel and contact messages. After setup, it runs without an internet connection.

## Desktop setup

Install Python 3.9 or newer, Tkinter, and the dependencies **before** losing internet access. On Linux, install the distribution's Tkinter package (often `python3-tk`) and ensure Bluetooth and BlueZ are running. On Windows, include Tcl/Tk when installing Python. A Bluetooth adapter and a device running MeshCore companion firmware with BLE enabled are required.

Create and activate a virtual environment, then install the dependency:

```sh
python -m venv .venv
```

On Windows, run `.venv\Scripts\activate`; on Linux, run `source .venv/bin/activate`. Then run:

```sh
python -m pip install -r requirements.txt
python -m meshcore_monitor
```

Scan for Bluetooth devices, select your radio, and connect. Pair the radio using the operating system if required. Scanning lists nearby Bluetooth devices, not just MeshCore radios. The app periodically requests battery voltage and reads the companion's incoming message queue, including messages queued while disconnected. **Retrieved messages are removed from the device queue**, so another companion app may not receive them. The app attempts to reconnect after an unexpected disconnect.

On connection, the app reads contact and channel names from the radio and caches them locally for offline display. The destination dropdown shows these names alongside their identifiers; you can also enter a channel slot or a contact's 12-character hexadecimal public-key prefix manually. Selecting a received contact message fills in its prefix. Names are associated with the connected radio, and old messages without a recorded radio identity remain identified by their original numbers or prefixes. Ambiguous contact prefixes are not given a name. The contact must already be known to the radio; channel slots must already be configured on it. Messages are limited to 120 UTF-8 bytes to avoid radio-side truncation. The app records a message when the radio accepts it, **not** when a recipient receives it; delivery is not confirmed, and a timeout can leave the outcome unknown. Channel 0 is commonly public; anyone with the channel key can read its messages.

The most recent 500 received messages, accepted outgoing messages, and datagrams are saved locally, can be searched, filtered, cleared, or exported as JSON, and remain available offline after restarting. Older messages are discarded when the limit is reached. Files are flushed to disk before replacement; incoming queue draining stops if a message cannot be saved. A message has already been removed from the radio before it can be saved, so a crash or power failure during that interval can still lose it.

Clearing or restoring history first creates backups in the `backups` folder next to the history file, including the on-disk original and a JSON snapshot of the current in-memory history. If the backup fails, the operation is cancelled. Use **Restore backup** to restore a snapshot or a valid original; the current history is backed up before replacement. Backups accumulate until you remove them and contain message contents, so protect the folder and copy backups to another device for protection against disk failure.

On Windows history and names are stored under `%LOCALAPPDATA%\meshcore-monitor`; on Linux they are under `$XDG_DATA_HOME/meshcore-monitor` (or `~/.local/share/meshcore-monitor` if unset). This history is separate from the browser dashboard's local storage. Neither is uploaded. Binary channel datagrams are indicated but not decoded.

Battery is displayed as voltage, not percentage: battery chemistry and calibration vary by device. A zero reading is shown as unavailable. To communicate with other people when the internet is down, working MeshCore radios and a reachable mesh are still required.

## Existing web dashboard

Use a Web Bluetooth-compatible browser (for example, Chrome or Edge on desktop or Android), Bluetooth enabled, and a device running MeshCore companion firmware with BLE enabled. Web Bluetooth is not available in all browsers or on iOS.

From this directory, run:

```sh
python3 -m http.server 8000 --bind 127.0.0.1
```

Open `http://localhost:8000`, select **Connect device**, and choose your radio. Bluetooth requires a secure context: localhost works for local development; other hosts require HTTPS. The browser may prompt for Bluetooth pairing.

The web dashboard also runs locally without internet once its files are available. It keeps its own browser-local activity history; the desktop app does not import it automatically.

## Development

Run the desktop tests after installing the Python dependency:

```sh
python -m unittest discover -s tests
```

Run the existing web tests with:

```sh
node --test
```

The implementation follows the [MeshCore companion protocol](https://github.com/meshcore-dev/MeshCore/blob/main/docs/companion_protocol.md).
