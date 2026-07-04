"""
rpi_device.py — NammaPark RPi Bench Tester (runs on the RPi)
=================================================================
Runs ON the in-hand Raspberry Pi to test MQTT comms AND the real servo
gate — minus the camera. It reuses the project's GateController, so when
a gate_command arrives over MQTT the *physical servo actually moves*. QR
scans are injected manually from the menu (the camera path is exercised
separately by main.py).

Hardware (default wiring, Pi 3A+):
  • Servo signal → physical pin 12 = BCM GPIO18 (SERVO_PIN, overridable)
  • Servo power  → physical pin 2 (5V), ground → physical pin 6 (GND)
If RPi.GPIO is unavailable (e.g. on a laptop) the servo silently falls
back to simulation logging, so this script still runs off-Pi.

What it does automatically:
  • Sends a heartbeat every HEARTBEAT_INTERVAL seconds
  • On gate_command open/close → drives the real servo (auto-closes after
    SERVO_OPEN_DURATION s); logs entry_verified / alerts

Manual CLI:
  1 → Inject valid QR scan — entry (booking state: BOOKED → ACTIVE)
  2 → Inject valid QR scan — exit  (booking state: ACTIVE → COMPLETED)
  3 → Inject QR with wrong plot_id  (should be rejected by backend)
  4 → Inject QR with missing fields (should be rejected by backend)
  5 → Inject completely invalid QR  (non-JSON, rejected immediately)
  o → Open the servo gate now   (local bench test, no MQTT)
  c → Close the servo gate now  (local bench test, no MQTT)
  b → Show mock bookings & states
  h → Send heartbeat now
  q → Quit

QR Schema (from roadmap §2.4):
  {
    "booking_id": <int>,
    "token":      "<secrets.token_hex(8)>",
    "plot_id":    <int>,
    "vehicle":    "<vehicle_number>",
    "issued_at":  "<ISO8601>"
  }

The booking_token (above JSON) is wrapped inside the entry_scan / exit_scan
MQTT payload:
  { "booking_token": "<raw QR json string>", "timestamp": "<ISO8601>" }

Usage:
    pip install paho-mqtt          # on the Pi, RPi.GPIO is already present
    python tests/laptop/rpi_device.py
"""

import json
import logging
import os
import secrets
import ssl
import sys
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

# Make the project root importable so we can reuse the real GateController
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from hardware.gate_controller import GateController

# Load broker creds / PLOT_ID from idp_rpi/.env so you don't have to export them
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
except Exception:
    pass

# ── CONFIG ──────────────────────────────────────────────────────────────────
BROKER             = os.getenv("MQTT_BROKER",   "your_broker.s1.eu.hivemq.cloud")
PORT               = int(os.getenv("MQTT_PORT", "8883"))
USERNAME           = os.getenv("MQTT_USERNAME", "your_mqtt_username")
PASSWORD           = os.getenv("MQTT_PASSWORD", "your_mqtt_password")
PLOT_ID            = int(os.getenv("PLOT_ID",   "1"))
DEVICE_ID          = os.getenv("DEVICE_ID",     "RPi-Plot-1")
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "10"))

# Servo gate wiring (BCM numbering). BCM18 == physical pin 12.
SERVO_PIN           = int(os.getenv("SERVO_PIN", "18"))
SERVO_PWM_FREQ      = int(os.getenv("SERVO_PWM_FREQ", "50"))
SERVO_OPEN_DUTY     = float(os.getenv("SERVO_OPEN_DUTY", "7.5"))
SERVO_CLOSE_DUTY    = float(os.getenv("SERVO_CLOSE_DUTY", "2.5"))
SERVO_OPEN_DURATION = int(os.getenv("SERVO_OPEN_DURATION", "5"))

# Real booking override — set these to a REAL booking (from the backend DB) so the
# live backend accepts the scan. When QR_BOOKING_ID and QR_TOKEN are set, menu
# options 1 (entry) and 2 (exit) inject a QR for that booking instead of a random
# mock one. QR plot_id always uses PLOT_ID above (must match the booking's plot).
#   export QR_BOOKING_ID=4
#   export QR_TOKEN=ce7a0c2b2344705a
#   export QR_VEHICLE=KA02JL8469
QR_BOOKING_ID = os.getenv("QR_BOOKING_ID")
QR_TOKEN      = os.getenv("QR_TOKEN")
QR_VEHICLE    = os.getenv("QR_VEHICLE", "KA01AB1234")
# ────────────────────────────────────────────────────────────────────────────

def t(suffix): return f"parking/plot/{PLOT_ID}/{suffix}"

TOPIC_HEARTBEAT    = t("heartbeat")
TOPIC_ENTRY_SCAN   = t("entry_scan")
TOPIC_EXIT_SCAN    = t("exit_scan")
TOPIC_GATE_COMMAND = t("gate_command")
TOPIC_ENTRY_VERIFY = t("entry_verified")
TOPIC_ALERTS       = t("alerts")

client: mqtt.Client = None
connected = False
gate: GateController = None
_hb_stop  = threading.Event()

# ── Mock bookings ─────────────────────────────────────────────────────────────
# Simulates QR data the Android app would have generated at booking time.
# booking_state tracks whether entry (BOOKED→ACTIVE) or exit (ACTIVE→COMPLETED)
# should be used — same QR, backend decides based on state.

MOCK_BOOKINGS = [
    {
        "booking_id": 101,
        "token":      secrets.token_hex(8),
        "plot_id":    PLOT_ID,
        "vehicle":    "KA01AB1234",
        "issued_at":  "2026-06-24T08:00:00Z",
        "state":      "BOOKED",   # BOOKED → entry scan; ACTIVE → exit scan
    },
    {
        "booking_id": 202,
        "token":      secrets.token_hex(8),
        "plot_id":    PLOT_ID,
        "vehicle":    "MH02XY5678",
        "issued_at":  "2026-06-24T09:00:00Z",
        "state":      "BOOKED",
    },
]

_booking_idx = 0  # which booking to use for next scan


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")

def log(tag: str, msg: str):
    print(f"[{ts()}] [{tag}] {msg}")


# ── QR payload builders ───────────────────────────────────────────────────────

def build_valid_qr(booking: dict) -> str:
    """Build the raw QR token JSON string (what's encoded inside the QR image)."""
    return json.dumps({
        "booking_id": booking["booking_id"],
        "token":      booking["token"],
        "plot_id":    booking["plot_id"],
        "vehicle":    booking["vehicle"],
        "issued_at":  booking.get("issued_at") or now_iso(),
    })


def active_booking() -> dict:
    """
    The booking used for valid entry/exit scans (menu 1 / 2).

    Uses the real-booking env override (QR_BOOKING_ID + QR_TOKEN) when set, so the
    live backend validates the scan; otherwise falls back to a random mock booking
    (only useful with mock_backend.py, which doesn't check tokens against a DB).
    """
    if QR_BOOKING_ID and QR_TOKEN:
        return {
            "booking_id": int(QR_BOOKING_ID),
            "token":      QR_TOKEN,
            "plot_id":    PLOT_ID,
            "vehicle":    QR_VEHICLE,
            "issued_at":  now_iso(),
            "real":       True,
        }
    return MOCK_BOOKINGS[_booking_idx % len(MOCK_BOOKINGS)]

def build_scan_payload(qr_raw: str) -> str:
    """Wrap QR string into the entry_scan / exit_scan MQTT payload."""
    return json.dumps({
        "booking_token": qr_raw,
        "timestamp":     now_iso(),
    })

def build_wrong_plot_qr() -> str:
    return json.dumps({
        "booking_id": 9999,
        "token":      secrets.token_hex(8),
        "plot_id":    PLOT_ID + 99,   # deliberately wrong
        "vehicle":    "DL01ZZ9999",
        "issued_at":  now_iso(),
    })

def build_missing_fields_qr() -> str:
    """QR missing 'token' and 'vehicle' — backend should reject."""
    return json.dumps({
        "booking_id": 777,
        "plot_id":    PLOT_ID,
        "issued_at":  now_iso(),
        # token and vehicle deliberately omitted
    })


# ── Heartbeat thread ──────────────────────────────────────────────────────────

def heartbeat_loop():
    log("HB", f"Heartbeat started (every {HEARTBEAT_INTERVAL}s)")
    while not _hb_stop.wait(timeout=HEARTBEAT_INTERVAL):
        if connected:
            payload = json.dumps({
                "device_id": DEVICE_ID,
                "status":    "online",
                "timestamp": now_iso(),
            })
            client.publish(TOPIC_HEARTBEAT, payload, qos=1)
            log("HB", f"Sent → {TOPIC_HEARTBEAT}")


# ── MQTT callbacks ────────────────────────────────────────────────────────────

def on_connect(mqttc, userdata, flags, rc):
    global connected
    if rc == 0:
        connected = True
        for topic in (TOPIC_GATE_COMMAND, TOPIC_ENTRY_VERIFY, TOPIC_ALERTS):
            mqttc.subscribe(topic, qos=1)
        log("OK", f"Connected to {BROKER}:{PORT}")
        log("OK", "Subscribed: gate_command | entry_verified | alerts")

        # Immediate first heartbeat
        mqttc.publish(TOPIC_HEARTBEAT, json.dumps({
            "device_id": DEVICE_ID,
            "status":    "online",
            "timestamp": now_iso(),
        }), qos=1)
        log("HB", "Initial heartbeat sent")
        print()
    else:
        codes = {1:"Bad protocol", 2:"Bad client ID", 3:"Unavailable",
                 4:"Bad credentials", 5:"Not authorised"}
        log("ERR", f"Connect failed: {codes.get(rc, f'rc={rc}')}")

def on_disconnect(mqttc, userdata, rc):
    global connected
    connected = False
    if rc != 0:
        log("WARN", f"Unexpected disconnect rc={rc} — reconnecting...")

def on_message(mqttc, userdata, msg):
    suffix = msg.topic.split("/")[-1]
    try:
        data = json.loads(msg.payload.decode("utf-8"))
    except Exception:
        data = {"raw": msg.payload.decode("utf-8")}

    if suffix == "gate_command":
        action = data.get("action", "?").lower()
        log("GATE", f"▶ Command: {action.upper()}")
        if action == "open":
            gate.open()      # drives the real servo (auto-closes after N s)
        elif action == "close":
            gate.close()
        else:
            log("GATE", f"Unknown action '{action}' — ignoring")

    elif suffix == "entry_verified":
        status  = data.get("status", "?")
        vehicle = data.get("vehicle_number", "?")
        b_id    = data.get("booking_id", "?")
        if status in ("verified", "checked_out"):
            label = "CHECKED IN" if status == "verified" else "CHECKED OUT"
            log("VERIFY", f"✓ {label} — booking={b_id}  vehicle={vehicle}")
        else:
            log("VERIFY", f"✗ REJECTED — booking={b_id}  status={status}")

    elif suffix == "alerts":
        log("ALERT", f"⚠ [{data.get('type','?')}] {data.get('message','')}")

    else:
        log("RECV", f"[{msg.topic}] {json.dumps(data)}")


# ── CLI actions ───────────────────────────────────────────────────────────────

def inject_entry_scan():
    booking = active_booking()
    qr_raw  = build_valid_qr(booking)
    payload = build_scan_payload(qr_raw)
    client.publish(TOPIC_ENTRY_SCAN, payload, qos=1)
    kind = "REAL" if booking.get("real") else "MOCK"
    log("SCAN", f"entry_scan → {TOPIC_ENTRY_SCAN}  [{kind}]")
    log("SCAN", f"  booking_id={booking['booking_id']}  plot_id={booking['plot_id']}  vehicle={booking['vehicle']}  token={booking['token']}")
    log("SCAN", "  (backend decides check-in vs check-out from the booking's DB status)")

def inject_exit_scan():
    booking = active_booking()
    qr_raw  = build_valid_qr(booking)   # same QR, exit topic
    payload = build_scan_payload(qr_raw)
    client.publish(TOPIC_EXIT_SCAN, payload, qos=1)
    kind = "REAL" if booking.get("real") else "MOCK"
    log("SCAN", f"exit_scan → {TOPIC_EXIT_SCAN}  [{kind}]")
    log("SCAN", f"  booking_id={booking['booking_id']}  plot_id={booking['plot_id']}  vehicle={booking['vehicle']}  token={booking['token']}")
    log("SCAN", "  (backend treats as CHECK-OUT only if the booking is currently ACTIVE)")

def inject_wrong_plot():
    qr_raw  = build_wrong_plot_qr()
    payload = build_scan_payload(qr_raw)
    client.publish(TOPIC_ENTRY_SCAN, payload, qos=1)
    log("SCAN", f"BAD entry_scan (wrong plot_id) → {TOPIC_ENTRY_SCAN}")
    log("SCAN", f"  payload: {qr_raw}")

def inject_missing_fields():
    qr_raw  = build_missing_fields_qr()
    payload = build_scan_payload(qr_raw)
    client.publish(TOPIC_ENTRY_SCAN, payload, qos=1)
    log("SCAN", f"BAD entry_scan (missing fields) → {TOPIC_ENTRY_SCAN}")
    log("SCAN", f"  payload: {qr_raw}")

def inject_invalid_qr():
    payload = build_scan_payload("not json at all %%%")
    client.publish(TOPIC_ENTRY_SCAN, payload, qos=1)
    log("SCAN", f"BAD entry_scan (non-JSON QR) → {TOPIC_ENTRY_SCAN}")

def show_bookings():
    print(f"\n  ── Mock Bookings (plot_id={PLOT_ID}) ────────────────")
    for i, b in enumerate(MOCK_BOOKINGS):
        marker = " ◀ next" if i == (_booking_idx % len(MOCK_BOOKINGS)) else ""
        print(f"  [{i}] booking_id={b['booking_id']}  vehicle={b['vehicle']}")
        print(f"       token={b['token']}  state={b['state']}{marker}")
    print()

def local_open_gate():
    log("SERVO", f"Local OPEN (GPIO{SERVO_PIN}) — bench test, no MQTT")
    gate.open()

def local_close_gate():
    log("SERVO", f"Local CLOSE (GPIO{SERVO_PIN}) — bench test, no MQTT")
    gate.close()


MENU = """
┌──────────────────────────────────────────────────────┐
│   NammaPark RPi Bench Tester                         │
│   Device: {device_id:<20}  Plot: {plot_id:<5}     │
├──────────────────────────────────────────────────────┤
│  Valid QR scans:                                     │
│   1 → entry_scan  (check-in,  BOOKED → ACTIVE)      │
│   2 → exit_scan   (check-out, ACTIVE → COMPLETED)   │
│  Bad QR scans (rejection test):                      │
│   3 → entry_scan — wrong plot_id                     │
│   4 → entry_scan — missing fields                    │
│   5 → entry_scan — non-JSON payload                  │
│  Servo (local bench test, no MQTT):                  │
│   o → open gate now                                  │
│   c → close gate now                                 │
│  Device:                                             │
│   b → show mock bookings & states                    │
│   h → send heartbeat now                             │
│   q → quit                                           │
└──────────────────────────────────────────────────────┘
Enter command: """

ACTIONS = {
    "1": inject_entry_scan,
    "2": inject_exit_scan,
    "3": inject_wrong_plot,
    "4": inject_missing_fields,
    "5": inject_invalid_qr,
    "o": local_open_gate,
    "c": local_close_gate,
    "b": show_bookings,
}

def cli_loop():
    print(MENU.format(device_id=DEVICE_ID, plot_id=PLOT_ID), end="", flush=True)
    while True:
        try:
            choice = input().strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break
        if choice == "q":
            break
        elif choice == "h":
            payload = json.dumps({
                "device_id": DEVICE_ID,
                "status":    "online",
                "timestamp": now_iso(),
            })
            client.publish(TOPIC_HEARTBEAT, payload, qos=1)
            log("HB", "Manual heartbeat sent")
        elif choice in ACTIONS:
            ACTIONS[choice]()
        elif choice != "":
            print(f"  Unknown: '{choice}'")
        print("Enter command: ", end="", flush=True)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    global client, gate

    # Banners + log messages use non-ASCII chars (═, ┌, —). On a Pi terminal
    # whose default encoding is latin-1/POSIX these raise UnicodeEncodeError, so
    # force UTF-8 (replace anything unmappable) before printing/logging anything.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    # Surface GateController's own logging (servo moves, sim warnings)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    print("═" * 54)
    print(f"  NammaPark RPi Bench Tester")
    print(f"  Broker    : {BROKER}:{PORT}")
    print(f"  Device ID : {DEVICE_ID}  |  Plot ID: {PLOT_ID}")
    print(f"  Servo     : GPIO{SERVO_PIN} (physical pin 12)  open={SERVO_OPEN_DURATION}s")
    print(f"  Heartbeat : every {HEARTBEAT_INTERVAL}s")
    if QR_BOOKING_ID and QR_TOKEN:
        print(f"  QR source : REAL booking_id={QR_BOOKING_ID} token={QR_TOKEN} vehicle={QR_VEHICLE}")
    else:
        print(f"  QR source : MOCK (random tokens — only works with mock_backend.py)")
    print("═" * 54)
    print()

    # --- Initialise the real servo gate (auto-sims if RPi.GPIO is absent) ---
    gate = GateController(
        servo_pin=SERVO_PIN,
        pwm_frequency=SERVO_PWM_FREQ,
        open_duty=SERVO_OPEN_DUTY,
        close_duty=SERVO_CLOSE_DUTY,
        auto_close_seconds=SERVO_OPEN_DURATION,
    )
    gate.setup()
    if gate.is_simulation:
        log("WARN", "RPi.GPIO not available — servo in SIMULATION mode (not on a Pi?)")
    else:
        log("OK", f"Servo gate ready on GPIO{SERVO_PIN} (physical pin 12)")
    print()

    # Print the generated mock tokens so you know what to expect
    print("  Mock QR tokens generated for this session:")
    for b in MOCK_BOOKINGS:
        print(f"    booking={b['booking_id']}  vehicle={b['vehicle']}  token={b['token']}")
    print()

    client = mqtt.Client(
        client_id=f"NammaPark_{DEVICE_ID}_{int(time.time())}",
        protocol=mqtt.MQTTv311,
    )
    client.username_pw_set(USERNAME, PASSWORD)
    client.tls_set(tls_version=ssl.PROTOCOL_TLS)
    client.tls_insecure_set(False)
    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect
    client.on_message    = on_message

    log("...", f"Connecting to {BROKER}:{PORT}")
    client.connect(BROKER, PORT, keepalive=60)
    client.loop_start()

    deadline = time.time() + 10
    while not connected and time.time() < deadline:
        time.sleep(0.2)

    if not connected:
        log("ERR", "Could not connect within 10s. Check credentials.")
        client.loop_stop()
        gate.cleanup()
        sys.exit(1)

    hb_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    hb_thread.start()

    try:
        cli_loop()
    finally:
        _hb_stop.set()
        client.loop_stop()
        client.disconnect()
        gate.cleanup()
        log("BYE", "Disconnected")

if __name__ == "__main__":
    main()
