"""
rpi_inject_command.py — NammaPark Gate Command Injector
========================================================
Lets you manually send commands to the RPi from your laptop
to test if the RPi's GateCommandHandler is working correctly.

Publishes to:
  parking/plot/{PLOT_ID}/gate_command    — open / close
  parking/plot/{PLOT_ID}/entry_verified  — verification result
  parking/plot/{PLOT_ID}/alerts          — alert message

Usage:
    python rpi_inject_command.py            # interactive menu
    python rpi_inject_command.py open       # send open immediately
    python rpi_inject_command.py close      # send close immediately
    python rpi_inject_command.py verified   # send entry_verified
    python rpi_inject_command.py alert      # send alert
"""

import json
import os
import ssl
import sys
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

# ── CONFIG ─────────────────────────────────────────────────────────────────
BROKER   = os.getenv("MQTT_BROKER",   "your_broker.s1.eu.hivemq.cloud")
PORT     = int(os.getenv("MQTT_PORT", "8883"))
USERNAME = os.getenv("MQTT_USERNAME", "your_mqtt_username")
PASSWORD = os.getenv("MQTT_PASSWORD", "your_mqtt_password")
PLOT_ID  = int(os.getenv("PLOT_ID",  "1"))
# ───────────────────────────────────────────────────────────────────────────

connected = False

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def on_connect(client, userdata, flags, rc):
    global connected
    connected = (rc == 0)
    if rc == 0:
        print(f"[OK] Connected to {BROKER}:{PORT}")
    else:
        print(f"[FAIL] rc={rc}")

def connect() -> mqtt.Client:
    client_id = f"NammaPark_Injector_{int(time.time())}"
    client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
    client.username_pw_set(USERNAME, PASSWORD)
    client.tls_set(tls_version=ssl.PROTOCOL_TLS)
    client.tls_insecure_set(False)
    client.on_connect = on_connect
    client.connect(BROKER, PORT, keepalive=60)
    client.loop_start()

    deadline = time.time() + 10
    while not connected and time.time() < deadline:
        time.sleep(0.2)

    if not connected:
        print("[FAIL] Could not connect within 10s.")
        sys.exit(1)

    return client

def send(client, topic, payload):
    res = client.publish(topic, json.dumps(payload), qos=1)
    print(f"\n[SENT] → {topic}")
    print(f"  {json.dumps(payload, indent=4)}")
    time.sleep(0.5)  # give paho time to flush

# ── Command builders ───────────────────────────────────────────────────────

def cmd_open(client):
    send(client, f"parking/plot/{PLOT_ID}/gate_command", {"action": "open"})

def cmd_close(client):
    send(client, f"parking/plot/{PLOT_ID}/gate_command", {"action": "close"})

def cmd_verified(client):
    send(client, f"parking/plot/{PLOT_ID}/entry_verified", {
        "booking_id":     101,
        "vehicle_id":     7,
        "vehicle_number": "KA01AB1234",
        "timestamp":      now_iso(),
        "status":         "verified",
    })

def cmd_rejected(client):
    send(client, f"parking/plot/{PLOT_ID}/entry_verified", {
        "booking_id":     999,
        "vehicle_number": "MH02XY0000",
        "timestamp":      now_iso(),
        "status":         "rejected",
    })

def cmd_alert(client):
    send(client, f"parking/plot/{PLOT_ID}/alerts", {
        "type":      "unauthorised_qr",
        "message":   "Unknown QR token scanned at gate",
        "timestamp": now_iso(),
    })

def interactive(client):
    MENU = """
┌─────────────────────────────────────────┐
│   NammaPark Gate Command Injector       │
│   Plot ID: {plot_id:<30} │
├─────────────────────────────────────────┤
│  1 → gate_command: open                 │
│  2 → gate_command: close                │
│  3 → entry_verified (verified)          │
│  4 → entry_verified (rejected)          │
│  5 → alerts (unauthorised_qr)           │
│  q → quit                               │
└─────────────────────────────────────────┘
""".format(plot_id=PLOT_ID)

    ACTIONS = {
        "1": cmd_open,
        "2": cmd_close,
        "3": cmd_verified,
        "4": cmd_rejected,
        "5": cmd_alert,
    }

    print(MENU)
    while True:
        try:
            choice = input("Command > ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            break

        if choice == "q":
            break
        elif choice in ACTIONS:
            ACTIONS[choice](client)
        else:
            print("  Unknown option. Try 1-5 or q.")

def main():
    arg = sys.argv[1].lower() if len(sys.argv) > 1 else None

    print(f"Connecting to {BROKER}:{PORT} ...")
    client = connect()

    DISPATCH = {
        "open":     cmd_open,
        "close":    cmd_close,
        "verified": cmd_verified,
        "rejected": cmd_rejected,
        "alert":    cmd_alert,
    }

    if arg and arg in DISPATCH:
        DISPATCH[arg](client)
    elif arg:
        print(f"Unknown argument '{arg}'. Valid: open, close, verified, rejected, alert")
    else:
        interactive(client)

    client.loop_stop()
    client.disconnect()
    print("\n[DONE]")

if __name__ == "__main__":
    main()
