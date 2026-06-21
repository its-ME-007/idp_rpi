"""
Live Broker Test — Subscriber

Connects to the HiveMQ Cloud broker and listens for messages on the
command topic used by the NammaPark app.

Usage:
    1. Start this subscriber FIRST in one terminal:
         python tests/test_broker_subscriber.py

    2. Then run the publisher in another terminal:
         python tests/test_broker_publisher.py

    3. You should see the published message appear in this subscriber's output.

    Press Ctrl+C to stop.
"""

import json
import os
import ssl
import sys
import time

# Add project root to path so we can import config
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
import paho.mqtt.client as mqtt

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# --- Configuration from .env ------------------------------------------------
BROKER = os.getenv("MQTT_BROKER")
PORT = int(os.getenv("MQTT_PORT", "8883"))
USERNAME = os.getenv("MQTT_USERNAME")
PASSWORD = os.getenv("MQTT_PASSWORD")
PLOT_ID = os.getenv("PLOT_ID", "1")

# Subscribe to ALL topics for this plot (command, status, heartbeat)
TOPICS = [
    "parking/plot/{}/command".format(PLOT_ID),
    "parking/plot/{}/status".format(PLOT_ID),
    "parking/plot/{}/heartbeat".format(PLOT_ID),
]

# --- MQTT Callbacks ----------------------------------------------------------

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("")
        print("[OK] CONNECTED to HiveMQ broker: {}:{}".format(BROKER, PORT))
        print("     Client ID: {}".format(client._client_id.decode()))
        print("     Username:  {}".format(USERNAME))
        print("")

        # Subscribe to all topics
        for topic in TOPICS:
            client.subscribe(topic, qos=1)
            print("     Subscribed to: {}".format(topic))

        print("")
        print("=" * 60)
        print("  Waiting for messages... (press Ctrl+C to stop)")
        print("=" * 60)
        print("")
    else:
        rc_messages = {
            1: "Incorrect protocol version",
            2: "Invalid client identifier",
            3: "Server unavailable",
            4: "Bad username or password",
            5: "Not authorized",
        }
        reason = rc_messages.get(rc, "Unknown error (rc={})".format(rc))
        print("")
        print("[FAIL] CONNECTION FAILED: {}".format(reason))


def on_disconnect(client, userdata, rc):
    if rc == 0:
        print("")
        print("[OK] Cleanly disconnected from broker")
    else:
        print("")
        print("[WARN] Unexpected disconnect (rc={}). Will attempt reconnect...".format(rc))


def on_message(client, userdata, msg):
    """Called when a message is received on a subscribed topic."""
    topic = msg.topic
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        payload_str = json.dumps(payload, indent=2)
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload_str = msg.payload.decode("utf-8", errors="replace")

    # Determine message type from topic
    if topic.endswith("/command"):
        msg_type = "COMMAND"
    elif topic.endswith("/status"):
        msg_type = "STATUS"
    elif topic.endswith("/heartbeat"):
        msg_type = "HEARTBEAT"
    else:
        msg_type = "MESSAGE"

    timestamp = time.strftime("%H:%M:%S")
    print("[{}] << {} >>".format(timestamp, msg_type))
    print("  Topic:   {}".format(topic))
    print("  Payload: {}".format(payload_str))
    print("")


# --- Main --------------------------------------------------------------------

def main():
    # Validate config
    if not BROKER or not USERNAME or not PASSWORD:
        print("[FAIL] Missing MQTT credentials in .env file")
        print("       Required: MQTT_BROKER, MQTT_USERNAME, MQTT_PASSWORD")
        sys.exit(1)

    print("=" * 60)
    print("  NammaPark -- Live Broker Subscriber Test")
    print("=" * 60)
    print("  Broker:   {}:{}".format(BROKER, PORT))
    print("  Username: {}".format(USERNAME))
    print("  Plot ID:  {}".format(PLOT_ID))
    print("  Topics:   {} subscriptions".format(len(TOPICS)))
    print("=" * 60)
    print("")
    print("Connecting...")

    # Create client
    client_id = "NammaPark_Subscriber_{}".format(int(time.time()))
    client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)

    # Auth
    client.username_pw_set(USERNAME, PASSWORD)

    # TLS for HiveMQ Cloud
    client.tls_set(tls_version=ssl.PROTOCOL_TLS)
    client.tls_insecure_set(False)

    # Set callbacks
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    # Connect and loop
    try:
        client.connect(BROKER, PORT, keepalive=60)
        client.loop_forever()
    except KeyboardInterrupt:
        print("")
        print("[STOP] Subscriber stopped by user")
        client.disconnect()
    except Exception as e:
        print("[FAIL] Error: {}".format(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
