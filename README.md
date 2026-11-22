# MeshCore Monitor

A local desktop application for a MeshCore **companion radio** over Bluetooth Low Energy. It shows connection and radio information, battery voltage, and received channel and contact messages. After setup, it runs without an internet connection.

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

The most recent 500 received messages and datagrams are saved locally, can be searched, filtered, cleared, or exported as JSON, and remain available offline after restarting. On Windows history is stored under `%LOCALAPPDATA%\meshcore-monitor`; on Linux it is under `$XDG_DATA_HOME/meshcore-monitor` (or `~/.local/share/meshcore-monitor` if unset). This history is separate from the browser dashboard's local storage. Neither is uploaded. Binary channel datagrams are indicated but not decoded.

Battery is displayed as voltage, not percentage: battery chemistry and calibration vary by device. A zero reading is shown as unavailable. To communicate with other people when the internet is down, working MeshCore radios and a reachable mesh are still required; this monitor receives messages but does not send them.

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
