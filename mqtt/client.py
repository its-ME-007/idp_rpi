"""
MQTT Client for NammaPark RPi Device (QR Gate Architecture)

Handles the MQTT connection lifecycle to HiveMQ Cloud broker:
- TLS-encrypted connection (port 8883)
- Auto-reconnect with exponential backoff
- Subscribe to gate_command, entry_verified, and alerts on connect
- Route incoming messages to registered handler
- Publish outbound messages (entry_scan, heartbeats)
- Graceful disconnect

Uses paho-mqtt 1.6.1, matching the IDP backend.
"""

import logging
import ssl
import threading
import time
from typing import Callable, Optional

import paho.mqtt.client as mqtt

from mqtt.topics import Topics

logger = logging.getLogger(__name__)


class MQTTClient:
    """
    MQTT connection manager for the RPi parking device.

    Connects to HiveMQ Cloud over TLS, subscribes to the command topic
    for the configured plot, and dispatches incoming messages to a
    registered handler callback.

    Usage:
        client = MQTTClient(
            broker="xxx.s1.eu.hivemq.cloud",
            port=8883,
            username="user",
            password="pass",
            device_id="RPi-Plot-1",
            plot_id=1,
        )
        client.set_message_handler(my_handler)
        client.connect()  # Blocking until connected or timeout
        client.loop_start()  # Background network loop
        # ... run application ...
        client.disconnect()
    """

    def __init__(
        self,
        broker: str,
        port: int,
        username: str,
        password: str,
        device_id: str,
        plot_id: int,
        reconnect_max_attempts: int = 0,
        reconnect_base_delay: float = 1.0,
        reconnect_max_delay: float = 60.0,
    ):
        """
        Initialize the MQTT client.

        Args:
            broker: HiveMQ Cloud broker hostname
            port: Broker port (8883 for TLS)
            username: MQTT username
            password: MQTT password
            device_id: Unique device identifier (used as client ID prefix)
            plot_id: Parking plot ID this device manages
            reconnect_max_attempts: Max reconnect attempts (0 = unlimited)
            reconnect_base_delay: Initial reconnect delay in seconds
            reconnect_max_delay: Maximum reconnect delay in seconds
        """
        self.broker = broker
        self.port = port
        self.username = username
        self.password = password
        self.device_id = device_id
        self.plot_id = plot_id

        # Reconnect settings
        self._reconnect_max_attempts = reconnect_max_attempts
        self._reconnect_base_delay = reconnect_base_delay
        self._reconnect_max_delay = reconnect_max_delay
        self._reconnect_attempts = 0

        # State
        self.connected = False
        self._connected_event = threading.Event()
        self._shutdown_event = threading.Event()
        self._message_handler: Optional[Callable[[str, str], None]] = None

        # Build the paho MQTT client
        # Client ID includes device name + timestamp for uniqueness
        client_id = f"NammaPark_{device_id}_{int(time.time())}"
        self._client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)

        # Configure authentication
        self._client.username_pw_set(username, password)

        # Configure TLS for HiveMQ Cloud (port 8883)
        self._client.tls_set(tls_version=ssl.PROTOCOL_TLS)
        self._client.tls_insecure_set(False)

        # Register paho callbacks
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        logger.info("MQTT client initialized: %s (device=%s, plot=%d)", broker, device_id, plot_id)

    def set_message_handler(self, handler: Callable[[str, str], None]) -> None:
        """
        Register a callback for incoming MQTT messages.

        The handler receives (topic: str, payload: str) and is called
        for every message on subscribed topics.

        Args:
            handler: Callback function(topic, payload)
        """
        self._message_handler = handler
        logger.debug("Message handler registered: %s", handler)

    def _on_connect(self, client, userdata, flags, rc):
        """Paho callback: connection established or failed."""
        if rc == 0:
            logger.info("Connected to MQTT broker %s:%d", self.broker, self.port)
            self.connected = True
            self._reconnect_attempts = 0
            self._connected_event.set()

            # Subscribe to all inbound topics for the QR-gate architecture
            inbound_topics = [
                Topics.gate_command(self.plot_id),
                Topics.service_gate_command(self.plot_id),
                Topics.entry_verified(self.plot_id),
                Topics.alerts(self.plot_id),
            ]
            for topic in inbound_topics:
                client.subscribe(topic, qos=1)
                logger.info("Subscribed to: %s", topic)
        else:
            rc_descriptions = {
                1: "Incorrect protocol version",
                2: "Invalid client identifier",
                3: "Server unavailable",
                4: "Bad username or password",
                5: "Not authorized",
            }
            reason = rc_descriptions.get(rc, f"Unknown error (rc={rc})")
            logger.error("MQTT connection failed: %s", reason)
            self.connected = False
            self._connected_event.set()  # Unblock connect() even on failure

    def _on_disconnect(self, client, userdata, rc):
        """Paho callback: disconnected from broker."""
        self.connected = False
        self._connected_event.clear()

        if rc == 0:
            logger.info("Cleanly disconnected from MQTT broker")
        else:
            logger.warning("Unexpected MQTT disconnection (rc=%d). Paho will auto-reconnect.", rc)
            self._reconnect_attempts += 1

            if self._reconnect_max_attempts > 0 and self._reconnect_attempts > self._reconnect_max_attempts:
                logger.error(
                    "Max reconnect attempts (%d) exceeded. Giving up.",
                    self._reconnect_max_attempts,
                )

    def _on_message(self, client, userdata, msg):
        """Paho callback: message received on a subscribed topic."""
        try:
            topic = msg.topic
            payload = msg.payload.decode("utf-8")
            logger.debug("Message received — Topic: %s | Payload: %s", topic, payload)

            if self._message_handler:
                self._message_handler(topic, payload)
            else:
                logger.warning("No message handler registered. Ignoring message on: %s", topic)
        except UnicodeDecodeError:
            logger.error("Failed to decode MQTT message payload as UTF-8 on topic: %s", msg.topic)
        except Exception as e:
            logger.error("Error processing MQTT message: %s", e, exc_info=True)

    def connect(self, timeout_seconds: int = 10) -> bool:
        """
        Connect to the MQTT broker (blocks until connected or timeout).

        Args:
            timeout_seconds: Max time to wait for connection

        Returns:
            True if connected successfully, False otherwise
        """
        if self.connected:
            logger.info("Already connected to MQTT broker")
            return True

        try:
            self._connected_event.clear()
            logger.info("Connecting to %s:%d ...", self.broker, self.port)
            self._client.connect(self.broker, self.port, keepalive=60)

            # Start the network loop so the connect callback fires
            self._client.loop_start()

            # Wait for _on_connect to signal
            if self._connected_event.wait(timeout=timeout_seconds) and self.connected:
                logger.info("MQTT connection established successfully")
                return True
            else:
                logger.error(
                    "MQTT connection timed out after %ds (broker=%s:%d)",
                    timeout_seconds,
                    self.broker,
                    self.port,
                )
                return False

        except Exception as e:
            logger.error("Failed to connect to MQTT broker: %s", e, exc_info=True)
            return False

    def disconnect(self) -> None:
        """Disconnect from the MQTT broker and stop the network loop."""
        # Release the main thread parked in loop_forever()
        self._shutdown_event.set()

        if self._client:
            try:
                # Send DISCONNECT first (while the background loop is alive to
                # flush it), then stop the loop thread.
                self._client.disconnect()
                self._client.loop_stop()
                logger.info("MQTT client disconnected")
            except Exception as e:
                logger.error("Error during MQTT disconnect: %s", e, exc_info=True)

        self.connected = False

    def publish(self, topic: str, payload: str, qos: int = 1) -> bool:
        """
        Publish a message to the MQTT broker.

        Args:
            topic: MQTT topic to publish to
            payload: Message payload (JSON string)
            qos: Quality of Service (0, 1, or 2)

        Returns:
            True if publish was successful, False otherwise
        """
        if not self.connected:
            logger.error("Cannot publish to %s: not connected", topic)
            return False

        try:
            result = self._client.publish(topic, payload, qos=qos)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.info("Published to %s: %s", topic, payload[:200])
                return True
            else:
                logger.error("Publish failed for %s: %s", topic, mqtt.error_string(result.rc))
                return False
        except Exception as e:
            logger.error("Error publishing to %s: %s", topic, e, exc_info=True)
            return False

    def loop_forever(self) -> None:
        """
        Block the calling (main) thread until disconnect() is called or the
        process is interrupted.

        The MQTT network loop already runs in the background thread started by
        connect()/loop_start(), and paho auto-reconnects there. We must NOT
        start a second loop here — two loops reading the same TLS socket
        corrupt the TLS record layer (ssl.SSLError RECORD_LAYER_FAILURE →
        unexpected rc=7). So we simply park the main thread; the background
        loop keeps doing all the network I/O and reconnection.
        """
        logger.info("RPi device running — network loop active in background. Ctrl+C to stop.")
        try:
            # Wait in 1s slices so SIGINT/SIGTERM stays responsive.
            while not self._shutdown_event.wait(timeout=1.0):
                pass
        except KeyboardInterrupt:
            logger.info("MQTT loop interrupted by keyboard")

    def is_connected(self) -> bool:
        """Check if currently connected to the MQTT broker."""
        return self.connected and self._client is not None
