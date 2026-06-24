"""
rpi_test_publisher.py — NammaPark RPi MQTT Publisher Test
==========================================================
Simulates the RPi publishing to HiveMQ Cloud without needing
any hardware. Tests the two topics the RPi publishes on:

  parking/plot/{PLOT_ID}/heartbeat   — device health
  parking/plot/{PLOT_ID}/entry_scan  — QR code scan event

Usage:
    python rpi_test_publisher.py

Set your credentials in the CONFIG block below or via env vars.
"""

import json
import os
import ssl
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
# ───────────────────────────────────────────────────────────────────────────

connected = False

def on_connect(client, userdata, flags, rc):
    global connected
    if rc == 0:
        connected = True
        print(f"[OK] Connected to {BROKER}:{PORT}")
    else:
        codes = {1: "Bad protocol", 2: "Bad client ID", 3: "Broker unavailable",
                 4: "Bad credentials", 5: "Not authorised"}
        print(f"[FAIL] Connect error: {codes.get(rc, f'rc={rc}')}")

def on_publish(client, userdata, mid):
    print(f"       ↳ Broker ACK (mid={mid})")

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def build_heartbeat() -> str:
    return json.dumps({
        "device_id": DEVICE_ID,
        "status":    "online",
        "timestamp": now_iso(),
    })

def build_entry_scan(booking_id: int = 101) -> str:
    """Wraps a mock QR payload the way QRScanner would."""
    mock_qr = json.dumps({
        "booking_id": booking_id,
        "token":      "test_token_abc123",
        "plot_id":    PLOT_ID,
        "vehicle":    "KA01AB1234",
        "issued_at":  now_iso(),
    })
    return json.dumps({
        "booking_token": mock_qr,
        "timestamp":     now_iso(),
    })

def main():
    client_id = f"NammaPark_TestPublisher_{int(time.time())}"
    client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
    client.username_pw_set(USERNAME, PASSWORD)
    client.tls_set(tls_version=ssl.PROTOCOL_TLS)
    client.tls_insecure_set(False)
    client.on_connect = on_connect
    client.on_publish = on_publish

    print(f"Connecting to {BROKER}:{PORT} ...")
    client.connect(BROKER, PORT, keepalive=60)
    client.loop_start()

    # Wait for connection
    deadline = time.time() + 10
    while not connected and time.time() < deadline:
        time.sleep(0.2)

    if not connected:
        print("[FAIL] Could not connect within 10s. Check credentials / broker URL.")
        client.loop_stop()
        return

    heartbeat_topic  = f"parking/plot/{PLOT_ID}/heartbeat"
    entry_scan_topic = f"parking/plot/{PLOT_ID}/entry_scan"

    # ── Test 1: Heartbeat ──────────────────────────────────────────────────
    print(f"\n── Test 1: Heartbeat ──────────────────────────────")
    for i in range(3):
        payload = build_heartbeat()
        res = client.publish(heartbeat_topic, payload, qos=1)
        print(f"[{i+1}] PUBLISH → {heartbeat_topic}")
        print(f"    payload: {payload}")
        time.sleep(2)

    # ── Test 2: Entry Scan (QR gate trigger) ───────────────────────────────
    print(f"\n── Test 2: Entry Scan (QR event) ──────────────────")
    payload = build_entry_scan(booking_id=101)
    res = client.publish(entry_scan_topic, payload, qos=1)
    print(f"[1] PUBLISH → {entry_scan_topic}")
    print(f"    payload: {payload}")
    time.sleep(1)

    # ── Test 3: Second scan (different booking) ────────────────────────────
    payload = build_entry_scan(booking_id=202)
    res = client.publish(entry_scan_topic, payload, qos=1)
    print(f"[2] PUBLISH → {entry_scan_topic}")
    print(f"    payload: {payload}")
    time.sleep(1)

    print("\n[DONE] All publishes sent. Disconnecting...")
    client.loop_stop()
    client.disconnect()

if __name__ == "__main__":
    main()
