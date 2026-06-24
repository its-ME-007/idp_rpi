"""
NammaPark RPi Device — Main Entry Point (QR Gate Architecture)

Bootstraps and wires together all subsystems:
  1. Loads and validates configuration from .env
  2. Initialises servo gate controller (single gate, no slots)
  3. Connects to HiveMQ Cloud MQTT broker (TLS)
  4. Registers GateCommandHandler as the MQTT message handler
     (listens for gate_command / entry_verified / alerts from backend)
  5. Starts the QR camera scanner
     (scans QR codes and publishes entry_scan to backend)
  6. Starts the HeartbeatService
  7. Runs the MQTT event loop until interrupted

MQTT Flow:
  Pi scans QR  →  publish entry_scan
  Backend validates  →  publish gate_command { action: "open" }
  Pi receives gate_command  →  servo opens gate (auto-closes after N seconds)

Usage:
    python main.py

Stop with Ctrl+C (SIGINT) or SIGTERM for graceful shutdown.
"""

import logging
import signal
import sys

from config import config, DeviceConfig
from mqtt.client import MQTTClient
from mqtt.handlers import GateCommandHandler
from mqtt.heartbeat import HeartbeatService
from hardware.gate_controller import GateController
from camera.qr_scanner import QRScanner


def setup_logging(level: str = "INFO") -> None:
    """Configure structured logging for the application."""
    # Log messages contain non-ASCII chars (—, ✓, →). On a Pi terminal whose
    # default encoding is latin-1/POSIX, writing them raises UnicodeEncodeError
    # and can kill worker threads. Force UTF-8 (replace anything unmappable).
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    # Reduce noise from paho internals
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

    # --- Initialise Gate Controller (single servo, main gate) ---
    logger.info("Initialising gate controller...")
    gate = GateController(
        servo_pin=DeviceConfig.SERVO_PIN,
        pwm_frequency=DeviceConfig.SERVO_PWM_FREQ,
        open_duty=DeviceConfig.SERVO_OPEN_DUTY,
        close_duty=DeviceConfig.SERVO_CLOSE_DUTY,
        auto_close_seconds=DeviceConfig.SERVO_OPEN_DURATION,
    )
    gate.setup()

    if gate.is_simulation:
        logger.warning(
            "Gate in SIMULATION mode — no real GPIO output "
            "(run on a Raspberry Pi with RPi.GPIO installed for hardware control)"
        )
    else:
        logger.info("Gate controller ready on GPIO%d", DeviceConfig.SERVO_PIN)

    # --- Initialise MQTT Client ---
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

    # --- Initialise Gate Command Handler ---
    # Receives gate_command / entry_verified / alerts from backend
    gate_handler = GateCommandHandler(gate_controller=gate)
    mqtt_client.set_message_handler(gate_handler.handle)

    # --- Initialise Heartbeat Service ---
    heartbeat = HeartbeatService(
        plot_id=DeviceConfig.PLOT_ID,
        device_id=DeviceConfig.DEVICE_ID,
        publish_fn=mqtt_client.publish,
        interval_seconds=DeviceConfig.HEARTBEAT_INTERVAL,
    )

    # --- Initialise QR Scanner ---
    # Scans QR codes and publishes entry_scan → backend validates → gate_command
    qr_scanner = QRScanner(
        plot_id=DeviceConfig.PLOT_ID,
        publish_fn=mqtt_client.publish,
        camera_index=DeviceConfig.CAMERA_INDEX,
        scan_interval=DeviceConfig.QR_SCAN_INTERVAL,
        cooldown_seconds=DeviceConfig.QR_COOLDOWN,
        camera_width=DeviceConfig.CAMERA_WIDTH,
        camera_height=DeviceConfig.CAMERA_HEIGHT,
    )

    # --- Graceful Shutdown Handler ---
    def shutdown(signum, frame):
        sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        logger.info("Received %s — shutting down gracefully...", sig_name)
        qr_scanner.stop()
        heartbeat.stop()
        mqtt_client.disconnect()
        gate.cleanup()
        logger.info("Shutdown complete.")
        sys.exit(0)

    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # --- Connect to MQTT Broker ---
    logger.info("Connecting to MQTT broker...")
    connected = mqtt_client.connect(timeout_seconds=15)

    if not connected:
        logger.error("Failed to connect to MQTT broker. Exiting.")
        gate.cleanup()
        sys.exit(1)

    # --- Start Background Services ---
    heartbeat.start()
    qr_scanner.start()

    # --- Run Event Loop ---
    logger.info("=" * 60)
    logger.info("  RPi device is online.")
    if qr_scanner.is_simulation:
        logger.info("  QR scanner: SIMULATION mode")
        logger.info("  Inject test QR:  qr_scanner.inject_test_qr(<json_str>)")
    else:
        logger.info("  QR scanner: camera index %d", DeviceConfig.CAMERA_INDEX)
    logger.info("  Gate:        GPIO%d (auto-closes after %ds)",
                DeviceConfig.SERVO_PIN, DeviceConfig.SERVO_OPEN_DURATION)
    logger.info("  Press Ctrl+C to stop.")
    logger.info("=" * 60)

    try:
        mqtt_client.loop_forever()
    except KeyboardInterrupt:
        pass
    finally:
        qr_scanner.stop()
        heartbeat.stop()
        mqtt_client.disconnect()
        gate.cleanup()
        logger.info("NammaPark RPi device stopped.")


if __name__ == "__main__":
    main()
