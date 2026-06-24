# Laptop Test Harness — `tests/laptop/`

Manual tools for exercising the NammaPark RPi **QR-gate** flow without the real
backend or app. Because the backend (`d:\IDP`) and Android app aren't QR-gate-ready
yet, **`mock_backend.py` stands in for both** so the RPi can be developed and tested
in isolation. It is also the **reference contract**: whatever it publishes/validates
is what the real backend must implement when it migrates (roadmap §2.2–2.5).

None of these files are `pytest` tests — they're run by hand. The real unit tests
live one level up in `tests/` (`test_topics.py`, `test_handlers.py`,
`test_heartbeat.py`) and are the only files `pytest tests/` collects.

## Setup

```bash
pip install -r ../../requirements.txt        # paho-mqtt etc. (device deps)
pip install -r requirements-dev.txt          # qrcode + Pillow (only for --gui)
```

Set broker credentials via env vars (or the `.env` / CONFIG blocks):
`MQTT_BROKER`, `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`, `PLOT_ID`.

## Tools

| Script | Role |
|--------|------|
| `mock_backend.py` | **Backend + app stand-in.** Auto-responds to `entry_scan`/`exit_scan` (validate → `gate_command: open` → `entry_verified`, auto-close). Console menu for manual commands. `--gui` adds a QR generator (see below). |
| `rpi_device.py` | **RPi bench tester.** Run on the in-hand Pi: drives the **real servo** (via `GateController`, BCM18 = physical pin 12) on `gate_command`, sends heartbeats, and injects entry/exit/bad scans from a menu (`o`/`c` move the servo locally). Auto-falls back to servo simulation off-Pi. Pairs with `mock_backend.py`. |
| `rpi_test_e2e.py` | Automated single-shot E2E check: publish one `entry_scan`, wait for the backend response, report pass/fail + timing. |
| `rpi_test_subscriber.py` | Passive sniffer — subscribes to all plot topics and prints traffic. |
| `rpi_test_publisher.py` | Scriptable one-shot publisher (heartbeat + entry_scan). |
| `rpi_inject_command.py` | Arg-driven backend→RPi injector (`open`/`close`/`verified`/`rejected`/`alert`). |
| `rpi_pipeline_smoke.py` | On-device pipeline smoke test (gate + QR parse + scanner + handler), no broker/camera. Run from anywhere; prints `=== All tests passed! ===`. |

## QR generator (`mock_backend.py --gui`)

```bash
python mock_backend.py --gui
```

Opens a small window to generate a QR encoding the booking schema (roadmap §2.4):

```json
{"booking_id": <int>, "token": "<secrets.token_hex(8)>", "plot_id": <int>,
 "vehicle": "<vehicle_number>", "issued_at": "<ISO8601>"}
```

The entire compact JSON is encoded as plain text in the QR. Display it on screen and
let a real RPi camera scan it to drive the full loop:

```
screen QR → RPi camera (OpenCV) → entry_scan {booking_token, timestamp}
          → mock_backend validates → gate_command {action: open} → servo opens
```

Re-scanning the same QR drives the exit path. The auto-responder keeps running in the
background while the GUI is open; the GUI also mirrors the console's manual command
buttons. If `qrcode`/`Pillow`/`tkinter` aren't installed it falls back to the console
menu, so console mode never needs the QR deps.

## Typical workflows

- **Test a real Pi against a mock backend:** run `python mock_backend.py --gui` on the
  laptop, run `python main.py` on the Pi, scan the on-screen QR with the Pi camera.
- **Test fully on the laptop (no Pi):** run `mock_backend.py` and `rpi_device.py` in
  two terminals; use `rpi_device.py`'s menu to inject scans.
- **Quick connectivity check:** `rpi_test_subscriber.py` in one terminal,
  `rpi_test_publisher.py` / `rpi_inject_command.py` in another.
