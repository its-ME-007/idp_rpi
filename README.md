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
├── .env.example          # Environment variable template (includes GPIO pin config)
├── .gitignore            # Python gitignore
├── README.md             # This file
├── requirements.txt      # Python dependencies
├── config.py             # Device configuration (reads from .env)
├── main.py               # Entry point — wires hardware + MQTT + heartbeat
├── hardware/
│   ├── __init__.py       # Package exports
│   ├── gpio_controller.py# Servo motor + LED GPIO driver (stubs on non-Pi)
│   └── slot_manager.py   # Physical slot state machine (FREE/RESERVED/OCCUPIED)
├── mqtt/
│   ├── __init__.py       # Package exports
│   ├── client.py         # MQTT connection manager (TLS, reconnect)
│   ├── handlers.py       # Command dispatcher wired to hardware (reserve/unlock/lock)
│   ├── heartbeat.py      # Periodic heartbeat publisher (live slot counts)
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

## Hardware Control

Physical hardware is controlled through the `hardware/` module.

### GPIO Controller (`hardware/gpio_controller.py`)

Controls servo motors (gate barriers) and dual-colour LED indicators for each slot via BCM-numbered GPIO pins.

| Action | Servo | LED |
|--------|-------|-----|
| Slot free (after lock) | Closes to 0° (2.5% duty) | Green ON, Red OFF |
| Slot reserved (after reserve) | Stays closed | Red blinks 3× then stays ON |
| Slot occupied (after unlock) | Opens to 90° (7.5% duty) | Red ON |

**Servo wiring** (SG90 / MG90S):
- Signal pin → configured `SERVO_PINS[n]` (PWM at 50 Hz)
- VCC → 5 V rail
- GND → common ground

**LED wiring** (per slot):
- Green LED anode → `LED_GREEN_PINS[n]` (via 220 Ω resistor)
- Red   LED anode → `LED_RED_PINS[n]`   (via 220 Ω resistor)
- Cathodes → GND

### Slot Manager (`hardware/slot_manager.py`)

Maintains a thread-safe state machine for each physical parking slot:

```
FREE ──[reserve]──► RESERVED ──[unlock]──► OCCUPIED
 ▲                                              │
 └─────────────────[lock]──────────────────────┘
```

### Simulation Mode

On non-RPi hardware (e.g., your dev laptop), `RPi.GPIO` is not available.
The system automatically falls back to a stub that logs all GPIO operations
to the console — so the full MQTT ↔ hardware pipeline can be developed and
tested without physical hardware.

```
WARNING | hardware.gpio_controller | RPi.GPIO not found — running in SIMULATION mode
INFO    | hardware.gpio_controller | [SIM] Gate OPEN  → slot 1 (servo pin 18, duty 7.5%)
INFO    | hardware.gpio_controller | [SIM] LED BLINK (reserved) → slot 1 (3 blinks)
```

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
