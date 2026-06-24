"""
rpi_test_e2e.py — NammaPark RPi End-to-End MQTT Pipeline Test
==============================================================
Simulates the full QR gate flow in one script:

  1. Connects to HiveMQ Cloud
  2. Subscribes to gate_command + entry_verified + alerts (what RPi listens on)
  3. Publishes a fake QR entry_scan (what RPi sends when QR is scanned)
  4. Waits for the backend's response on gate_command / entry_verified
  5. Reports pass/fail with timing

Run this with the backend live to check the full loop:
  RPi → entry_scan → [HiveMQ] → Backend → gate_command → [HiveMQ] → RPi

Usage:
    python rpi_test_e2e.py
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
DEVICE_ID = os.getenv("DEVICE_ID",   "RPi-Plot-1")

# How long to wait for a backend response after publishing entry_scan (seconds)
RESPONSE_TIMEOUT = 15
# ───────────────────────────────────────────────────────────────────────────

connected      = False
response_recv  = False
response_topic = None
response_data  = None
scan_sent_at   = None

def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def on_connect(client, userdata, flags, rc):
    global connected
    if rc == 0:
        connected = True
        subs = [
            f"parking/plot/{PLOT_ID}/gate_command",
            f"parking/plot/{PLOT_ID}/entry_verified",
            f"parking/plot/{PLOT_ID}/alerts",
        ]
        for topic in subs:
            client.subscribe(topic, qos=1)
        print(f"[{ts()}] Connected + subscribed to {len(subs)} topics")
    else:
        print(f"[{ts()}] Connection failed rc={rc}")

def on_message(client, userdata, msg):
    global response_recv, response_topic, response_data
    suffix = msg.topic.split("/")[-1]
    try:
        data = json.loads(msg.payload.decode("utf-8"))
    except Exception:
        data = {"raw": msg.payload.decode("utf-8")}

    elapsed = f"{time.time() - scan_sent_at:.2f}s" if scan_sent_at else "?"

    print(f"\n[{ts()}] RESPONSE RECEIVED (+{elapsed})")
    print(f"  Topic  : {msg.topic}")
    print(f"  Payload: {json.dumps(data, indent=4)}")

    if suffix in ("gate_command", "entry_verified"):
        response_recv  = True
        response_topic = msg.topic
        response_data  = data

def build_entry_scan(booking_id: int) -> str:
    mock_qr = json.dumps({
        "booking_id": booking_id,
        "token":      "e2e_test_token_xyz",
        "plot_id":    PLOT_ID,
        "vehicle":    "KA01AB9999",
        "issued_at":  now_iso(),
    })
    return json.dumps({
        "booking_token": mock_qr,
        "timestamp":     now_iso(),
    })

def main():
    global scan_sent_at

    client_id = f"NammaPark_E2E_{int(time.time())}"
    client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
    client.username_pw_set(USERNAME, PASSWORD)
    client.tls_set(tls_version=ssl.PROTOCOL_TLS)
    client.tls_insecure_set(False)
    client.on_connect = on_connect
    client.on_message = on_message

    print(f"═══════════════════════════════════════════════")
    print(f"  NammaPark E2E MQTT Test  (plot_id={PLOT_ID})")
    print(f"═══════════════════════════════════════════════")
    print(f"  Broker : {BROKER}:{PORT}")
    print(f"  Timeout: {RESPONSE_TIMEOUT}s for backend response")
    print()

    print(f"[{ts()}] Connecting...")
    client.connect(BROKER, PORT, keepalive=60)
    client.loop_start()

    # Wait for connection
    deadline = time.time() + 10
    while not connected and time.time() < deadline:
        time.sleep(0.2)

    if not connected:
        print("[FAIL] Could not connect within 10s.")
        client.loop_stop()
        sys.exit(1)

    # ── Step 1: Heartbeat (verify device is seen by backend) ──────────────
    print(f"\n[STEP 1] Sending heartbeat...")
    hb_payload = json.dumps({
        "device_id": DEVICE_ID,
        "status":    "online",
        "timestamp": now_iso(),
    })
    client.publish(f"parking/plot/{PLOT_ID}/heartbeat", hb_payload, qos=1)
    print(f"  → parking/plot/{PLOT_ID}/heartbeat")
    print(f"    {hb_payload}")
    time.sleep(1)

    # ── Step 2: Publish entry_scan and wait for gate_command ──────────────
    print(f"\n[STEP 2] Publishing QR entry_scan...")
    scan_payload = build_entry_scan(booking_id=101)
    scan_sent_at = time.time()
    client.publish(f"parking/plot/{PLOT_ID}/entry_scan", scan_payload, qos=1)
    print(f"  → parking/plot/{PLOT_ID}/entry_scan")
    print(f"    {scan_payload}")
    print(f"\n  Waiting up to {RESPONSE_TIMEOUT}s for backend response...")

    deadline = time.time() + RESPONSE_TIMEOUT
    while not response_recv and time.time() < deadline:
        time.sleep(0.2)

    # ── Result ─────────────────────────────────────────────────────────────
    print()
    print("═══════════════════════════════════════════════")
    if response_recv:
        elapsed = time.time() - scan_sent_at
        print(f"  [PASS] Backend responded in {elapsed:.2f}s")
        print(f"  Topic  : {response_topic}")
        suffix = response_topic.split("/")[-1]
        if suffix == "gate_command":
            action = response_data.get("action", "?")
            print(f"  Action : {action.upper()}")
        elif suffix == "entry_verified":
            status = response_data.get("status", "?")
            print(f"  Status : {status}")
    else:
        print(f"  [TIMEOUT] No response from backend in {RESPONSE_TIMEOUT}s")
        print("  → Is the backend running and connected to the same broker?")
        print("  → Is PLOT_ID correct?")
        print("  → Is the backend subscribed to parking/plot/+/entry_scan?")
    print("═══════════════════════════════════════════════")

    client.loop_stop()
    client.disconnect()

if __name__ == "__main__":
    main()
