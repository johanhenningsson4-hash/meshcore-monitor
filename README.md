# MeshCore Monitor

A small, local web dashboard for a MeshCore **companion radio** over Bluetooth Low Energy. It shows connection and radio information, battery voltage, and received channel and contact messages.

## Run

Use a Web Bluetooth-compatible browser (for example, Chrome or Edge on desktop or Android), Bluetooth enabled, and a device running MeshCore companion firmware with BLE enabled. Web Bluetooth is not available in all browsers or on iOS.

From this directory, run:

```sh
python3 -m http.server 8000 --bind 127.0.0.1
```

Open `http://localhost:8000`, select **Connect device**, and choose your radio. Bluetooth requires a secure context: localhost works for local development; other hosts require HTTPS. The browser may prompt for Bluetooth pairing.

The monitor periodically requests battery voltage and drains the companion's incoming message queue, including messages queued while disconnected. **Retrieved messages are removed from the device queue**, so another companion app may not receive them. Keep this page open to monitor new messages. Messages are held in memory only, disappear on reload or when starting a new connection, and are not uploaded or persisted. Binary channel datagrams are indicated but not decoded.

Battery is displayed as voltage, not percentage: battery chemistry and calibration vary by device. A zero reading is shown as unavailable. Disconnects require manually connecting again; the displayed readings are the last received values.

## Development

No dependencies or build step are needed. Run the protocol and connection tests with:

```sh
node --test
```

The implementation follows the [MeshCore companion protocol](https://github.com/meshcore-dev/MeshCore/blob/main/docs/companion_protocol.md).
