"""
Live Broker Test — Publisher

Connects to the HiveMQ Cloud broker and publishes a test command
payload on the parking command topic, simulating what the IDP backend
sends to the RPi.

Usage:
    1. (Optional) Start the subscriber first to see the message arrive:
         python tests/test_broker_subscriber.py

    2. Run this publisher:
         python tests/test_broker_publisher.py

    The script publishes a test "reserve" command, waits for confirmation,
    then disconnects.
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

# Topic to publish on (same topic the RPi subscribes to)
COMMAND_TOPIC = f"parking/plot/{PLOT_ID}/command"

# Test payloads - these match the exact format the IDP backend publishes
TEST_PAYLOADS = [
    {
        "name": "Reserve Slot (2W)",
        "topic": COMMAND_TOPIC,
        "payload": {
            "action": "reserve",
            "booking_id": 9999,
            "slot_type": "2W",
        },
    },
    {
        "name": "Unlock Slot",
        "topic": COMMAND_TOPIC,
        "payload": {
            "action": "unlock",
            "booking_id": 9999,
            "slot_id": 1,
        },
    },
    {
        "name": "Lock Slot",
        "topic": COMMAND_TOPIC,
        "payload": {
            "action": "lock",
            "slot_id": 1,
        },
    },
]

# --- State -------------------------------------------------------------------
publish_results = []


# --- MQTT Callbacks ----------------------------------------------------------

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("")
        print("[OK] CONNECTED to HiveMQ broker: {}:{}".format(BROKER, PORT))
        print("     Client ID: {}".format(client._client_id.decode()))
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


def on_publish(client, userdata, mid):
    """Called when a message has been successfully published."""
    publish_results.append(mid)


# --- Main --------------------------------------------------------------------

def main():
    # Validate config
    if not BROKER or not USERNAME or not PASSWORD:
        print("[FAIL] Missing MQTT credentials in .env file")
        print("       Required: MQTT_BROKER, MQTT_USERNAME, MQTT_PASSWORD")
        sys.exit(1)

    print("=" * 60)
    print("  NammaPark -- Live Broker Publisher Test")
    print("=" * 60)
    print("  Broker:   {}:{}".format(BROKER, PORT))
    print("  Username: {}".format(USERNAME))
    print("  Plot ID:  {}".format(PLOT_ID))
    print("  Topic:    {}".format(COMMAND_TOPIC))
    print("  Payloads: {} test messages".format(len(TEST_PAYLOADS)))
    print("=" * 60)
    print("")
    print("Connecting...")

    # Create client
    client_id = "NammaPark_Publisher_{}".format(int(time.time()))
    client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)

    # Auth
    client.username_pw_set(USERNAME, PASSWORD)

    # TLS for HiveMQ Cloud
    client.tls_set(tls_version=ssl.PROTOCOL_TLS)
    client.tls_insecure_set(False)

    # Set callbacks
    client.on_connect = on_connect
    client.on_publish = on_publish

    # Connect
    try:
        client.connect(BROKER, PORT, keepalive=60)
        client.loop_start()
    except Exception as e:
        print("[FAIL] Connection error: {}".format(e))
        sys.exit(1)

    # Wait for connection
    time.sleep(3)

    if not client.is_connected():
        print("[FAIL] Failed to connect within 3 seconds. Check credentials and network.")
        client.loop_stop()
        sys.exit(1)

    # Publish test messages
    print("-" * 60)
    print("  Publishing test messages...")
    print("-" * 60)
    print("")

    success_count = 0
    fail_count = 0

    for i, test in enumerate(TEST_PAYLOADS, 1):
        name = test["name"]
        topic = test["topic"]
        payload = json.dumps(test["payload"])

        print("  [{}/{}] {}".format(i, len(TEST_PAYLOADS), name))
        print("    Topic:   {}".format(topic))
        print("    Payload: {}".format(payload))

        result = client.publish(topic, payload, qos=1)

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            # Wait for publish confirmation
            result.wait_for_publish(timeout=5)
            if result.is_published():
                print("    Result:  [OK] Published (mid={})".format(result.mid))
                success_count += 1
            else:
                print("    Result:  [WARN] Sent but not confirmed within 5s")
                fail_count += 1
        else:
            print("    Result:  [FAIL] Failed ({})".format(mqtt.error_string(result.rc)))
            fail_count += 1

        print("")

        # Small delay between messages
        time.sleep(0.5)

    # Summary
    print("=" * 60)
    print("  Test Summary")
    print("=" * 60)
    print("  Successful: {}/{}".format(success_count, len(TEST_PAYLOADS)))
    if fail_count > 0:
        print("  Failed:     {}/{}".format(fail_count, len(TEST_PAYLOADS)))
    print("")

    if success_count == len(TEST_PAYLOADS):
        print("  ALL MESSAGES PUBLISHED SUCCESSFULLY!")
        print("  If the subscriber is running, it should have received them.")
    else:
        print("  [WARN] Some messages failed. Check broker connectivity.")

    print("")

    # Disconnect
    client.loop_stop()
    client.disconnect()
    print("[OK] Disconnected from broker")


if __name__ == "__main__":
    main()
