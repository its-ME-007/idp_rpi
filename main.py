"""
NammaPark RPi Device — Main Entry Point

Starts the MQTT interfacing module:
1. Loads configuration from .env
2. Connects to HiveMQ Cloud broker
3. Registers command handlers (reserve, unlock, lock)
4. Starts heartbeat service
5. Runs the MQTT event loop until interrupted

Usage:
    python main.py

Stop with Ctrl+C (SIGINT) or SIGTERM for graceful shutdown.
"""

import logging
import signal
import sys

from config import config, DeviceConfig
from mqtt.client import MQTTClient
from mqtt.handlers import CommandDispatcher
from mqtt.heartbeat import HeartbeatService


def setup_logging(level: str = "INFO") -> None:
    """Configure structured logging for the application."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )

    # Reduce noise from paho-mqtt internals
    logging.getLogger("paho").setLevel(logging.WARNING)


def main() -> None:
    """Application entry point."""

    # --- Setup Logging ---
    setup_logging(DeviceConfig.LOG_LEVEL)
    logger = logging.getLogger("main")

    logger.info("=" * 60)
    logger.info("  NammaPark RPi Device Starting...")
    logger.info("=" * 60)

    # --- Validate Configuration ---
    errors = DeviceConfig.validate()
    if errors:
        for error in errors:
            logger.error("CONFIG ERROR: %s", error)
        logger.error("Fix the above configuration errors in .env and restart.")
        sys.exit(1)

    DeviceConfig.print_summary()

    # --- Initialize MQTT Client ---
    mqtt_client = MQTTClient(
        broker=DeviceConfig.MQTT_BROKER,
        port=DeviceConfig.MQTT_PORT,
        username=DeviceConfig.MQTT_USERNAME,
        password=DeviceConfig.MQTT_PASSWORD,
        device_id=DeviceConfig.DEVICE_ID,
        plot_id=DeviceConfig.PLOT_ID,
        reconnect_max_attempts=DeviceConfig.RECONNECT_MAX_ATTEMPTS,
        reconnect_base_delay=DeviceConfig.RECONNECT_BASE_DELAY,
        reconnect_max_delay=DeviceConfig.RECONNECT_MAX_DELAY,
    )

    # --- Initialize Command Dispatcher ---
    dispatcher = CommandDispatcher(
        plot_id=DeviceConfig.PLOT_ID,
        publish_fn=mqtt_client.publish,
    )
    mqtt_client.set_message_handler(dispatcher.dispatch)

    # --- Initialize Heartbeat Service ---
    heartbeat = HeartbeatService(
        plot_id=DeviceConfig.PLOT_ID,
        device_id=DeviceConfig.DEVICE_ID,
        publish_fn=mqtt_client.publish,
        interval_seconds=DeviceConfig.HEARTBEAT_INTERVAL,
        total_slots_2w=DeviceConfig.TOTAL_SLOTS_2W,
        total_slots_4w=DeviceConfig.TOTAL_SLOTS_4W,
    )

    # --- Graceful Shutdown Handler ---
    def shutdown(signum, frame):
        sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        logger.info("Received %s — shutting down gracefully...", sig_name)
        heartbeat.stop()
        mqtt_client.disconnect()
        logger.info("Shutdown complete.")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # --- Connect to Broker ---
    logger.info("Connecting to MQTT broker...")
    connected = mqtt_client.connect(timeout_seconds=15)

    if not connected:
        logger.error("Failed to connect to MQTT broker. Exiting.")
        sys.exit(1)

    # --- Start Heartbeat ---
    heartbeat.start()

    # --- Run Event Loop ---
    logger.info("RPi device is online and listening for commands.")
    logger.info("Press Ctrl+C to stop.")
    logger.info("-" * 60)

    try:
        # loop_forever handles reconnection automatically
        mqtt_client.loop_forever()
    except KeyboardInterrupt:
        pass
    finally:
        heartbeat.stop()
        mqtt_client.disconnect()
        logger.info("NammaPark RPi device stopped.")


if __name__ == "__main__":
    main()
