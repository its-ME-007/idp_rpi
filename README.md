# NammaPark — RPi Hardware & Interfacing

This repo contains the **hardware networking** and **MQTT interfacing** code for the NammaPark smart parking system, built for IDP 2026.

The RPi module connects to the same **HiveMQ Cloud** MQTT broker used by the [IDP backend](https://github.com/its-ME-007/idp-mqtt) and the [Android app](https://github.com/its-ME-007/idp-app), enabling real-time communication between the app and physical parking hardware.

_[Visit the Google Stitch Workspace to view the UI](https://stitch.withgoogle.com/projects/2640292831832766307)_

---

## Architecture

```
┌──────────────┐       ┌──────────────────┐       ┌──────────────┐
│  Android App │       │  HiveMQ Cloud    │       │  Raspberry Pi │
│              │──────▶│  MQTT Broker     │──────▶│  (this repo)  │
│  (idp-app)   │       │  (TLS:8883)      │       │               │
│              │◀──────│                  │◀──────│               │
└──────────────┘       └──────────────────┘       └──────────────┘
                              ▲
                              │
                       ┌──────┴──────┐
                       │ IDP Backend │
                       │  (FastAPI)  │
                       │  (IDP repo) │
                       └─────────────┘
```

### MQTT Message Flow

| Direction | Topic | Payload | Purpose |
|-----------|-------|---------|---------|
| Backend → RPi | `parking/plot/{id}/command` | `{ action: "reserve", booking_id, slot_type }` | Reserve a slot |
| Backend → RPi | `parking/plot/{id}/command` | `{ action: "unlock", booking_id, slot_id }` | Unlock on arrival |
| Backend → RPi | `parking/plot/{id}/command` | `{ action: "lock", slot_id }` | Lock (cancel/checkout) |
| RPi → Backend | `parking/plot/{id}/status` | `{ action: "reserved", booking_id, slot_id }` | Confirm reservation |
| RPi → Backend | `parking/plot/{id}/status` | `{ action: "freed", booking_id, slot_id }` | Vehicle departed |
| RPi → Backend | `parking/plot/{id}/heartbeat` | `{ device_id, status, timestamp, ... }` | Health check |

---

## Project Structure

```
idp_rpi/
├── .env.example          # Environment variable template
├── .gitignore            # Python gitignore
├── README.md             # This file
├── requirements.txt      # Python dependencies
├── config.py             # Device configuration (reads from .env)
├── main.py               # Entry point — starts MQTT service
├── mqtt/
│   ├── __init__.py       # Package exports
│   ├── client.py         # MQTT connection manager (TLS, reconnect)
│   ├── handlers.py       # Command dispatcher + action handler stubs
│   ├── heartbeat.py      # Periodic heartbeat publisher
│   └── topics.py         # Topic constants & builders
└── tests/
    ├── __init__.py
    ├── test_topics.py     # Topic string validation
    ├── test_handlers.py   # Command dispatch & response tests
    └── test_heartbeat.py  # Heartbeat payload format tests
```

---

## Setup

### Prerequisites
- Python 3.10+ (tested on 3.11)
- Access to the HiveMQ Cloud broker (credentials in project `.env`)

### Installation

```bash
# Clone the repo
git clone <repo-url>
cd idp_rpi

# Create virtual environment
python -m venv .venv

# Activate (Linux/macOS)
source .venv/bin/activate

# Activate (Windows)
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration

```bash
# Copy the environment template
cp .env.example .env

# Edit .env with your credentials
# Required: MQTT_BROKER, MQTT_USERNAME, MQTT_PASSWORD, PLOT_ID
```

### Running

```bash
# Start the RPi MQTT service
python main.py
```

The service will:
1. Connect to HiveMQ Cloud over TLS
2. Subscribe to `parking/plot/{PLOT_ID}/command`
3. Start sending heartbeats every 60 seconds
4. Log all incoming commands to the console

Stop with `Ctrl+C` for graceful shutdown.

### Running Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_handlers.py -v
```

---

## Adding Hardware Control

The handler stubs in `mqtt/handlers.py` are ready for hardware integration. Each handler has a `# TODO` comment indicating where to add GPIO/servo/sensor code:

```python
def _handle_reserve(self, data: dict) -> None:
    # ...
    # TODO: Activate hardware indicator (LED/display) for the assigned slot
    # ...
```

The handlers will be extended with:
- **Servo motor control** for gate barriers
- **IR/ultrasonic sensor** integration for slot occupancy detection
- **LED indicators** for slot status display
- **Camera module** integration for QR code scanning

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `paho-mqtt` | 1.6.1 | MQTT client (matches IDP backend) |
| `python-dotenv` | 1.0.0 | Environment variable loading |

---

## Related Repositories

- **IDP Backend**: FastAPI server with MQTT broker, database, and API → `d:\IDP`
- **IDP App**: Android mobile app with MQTT manager → `d:\idp-app`
