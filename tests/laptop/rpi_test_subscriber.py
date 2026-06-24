"""
rpi_test_subscriber.py — NammaPark RPi MQTT Subscriber Test
=============================================================
Subscribes to all topics the RPi listens on and prints incoming
messages. Use this on your laptop/PC while the backend or Android
app sends commands, to verify the broker is routing correctly.

Subscribed topics:
  parking/plot/{PLOT_ID}/gate_command    — open / close gate
  parking/plot/{PLOT_ID}/entry_verified  — QR verification result
  parking/plot/{PLOT_ID}/alerts          — security / device alerts

Also subscribes to the RPi's own publish topics so you can
verify heartbeats / entry_scan events if you run the publisher
in another terminal:
  parking/plot/{PLOT_ID}/heartbeat
  parking/plot/{PLOT_ID}/entry_scan

Usage:
    python rpi_test_subscriber.py
    # Keep running — press Ctrl+C to stop
"""

import json
import os
import ssl
import time
from datetime import datetime

import paho.mqtt.client as mqtt

# ── CONFIG ─────────────────────────────────────────────────────────────────
BROKER   = os.getenv("MQTT_BROKER",   "your_broker.s1.eu.hivemq.cloud")
PORT     = int(os.getenv("MQTT_PORT", "8883"))
USERNAME = os.getenv("MQTT_USERNAME", "your_mqtt_username")
PASSWORD = os.getenv("MQTT_PASSWORD", "your_mqtt_password")
PLOT_ID  = int(os.getenv("PLOT_ID",  "1"))
DEVICE_ID = os.getenv("DEVICE_ID",   "RPi-Plot-1")
# ───────────────────────────────────────────────────────────────────────────

TOPICS = [
    # RPi subscribes (backend → RPi)
    f"parking/plot/{PLOT_ID}/gate_command",
    f"parking/plot/{PLOT_ID}/entry_verified",
    f"parking/plot/{PLOT_ID}/alerts",
    # RPi publishes (RPi → backend) — listen here to verify publisher test
    f"parking/plot/{PLOT_ID}/heartbeat",
    f"parking/plot/{PLOT_ID}/entry_scan",
]

MSG_COUNT = 0

def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"[{ts()}] [OK] Connected to {BROKER}:{PORT}")
        for topic in TOPICS:
            client.subscribe(topic, qos=1)
            print(f"       ↳ Subscribed: {topic}")
        print("\nWaiting for messages... (Ctrl+C to stop)\n")
    else:
        codes = {1: "Bad protocol", 2: "Bad client ID", 3: "Broker unavailable",
                 4: "Bad credentials", 5: "Not authorised"}
        print(f"[{ts()}] [FAIL] Connect error: {codes.get(rc, f'rc={rc}')}")

def on_disconnect(client, userdata, rc):
    if rc != 0:
        print(f"[{ts()}] [WARN] Unexpected disconnect (rc={rc}). Paho will reconnect...")

def on_message(client, userdata, msg):
    global MSG_COUNT
    MSG_COUNT += 1
    suffix = msg.topic.split("/")[-1]
    payload_raw = msg.payload.decode("utf-8")

    # Pretty-print if JSON
    try:
        payload_pretty = json.dumps(json.loads(payload_raw), indent=4)
    except Exception:
        payload_pretty = payload_raw

    direction = "↓ RECV (backend→RPi)" if suffix in ("gate_command", "entry_verified", "alerts") \
                else "↑ RECV (RPi→backend)"

    print(f"[{ts()}] #{MSG_COUNT} {direction}")
    print(f"  Topic  : {msg.topic}")
    print(f"  QoS    : {msg.qos}")
    print(f"  Payload:\n{payload_pretty}")
    print()

    # Decode gate commands for quick human readability
    if suffix == "gate_command":
        try:
            data = json.loads(payload_raw)
            action = data.get("action", "?").upper()
            print(f"  ▶ GATE ACTION: {action}")
            print()
        except Exception:
            pass

def main():
    client_id = f"NammaPark_TestSubscriber_{int(time.time())}"
    client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
    client.username_pw_set(USERNAME, PASSWORD)
    client.tls_set(tls_version=ssl.PROTOCOL_TLS)
    client.tls_insecure_set(False)
    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect
    client.on_message    = on_message

    print(f"Connecting to {BROKER}:{PORT} ...")
    client.connect(BROKER, PORT, keepalive=60)

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print(f"\n[{ts()}] Stopped. Total messages received: {MSG_COUNT}")
        client.disconnect()

if __name__ == "__main__":
    main()
