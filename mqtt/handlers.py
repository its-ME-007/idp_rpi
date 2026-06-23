"""
Gate Command Handler — NammaPark RPi (QR Gate Architecture)

Subscribes to the gate_command topic and controls the physical servo gate
based on backend instructions.

Topics:
  Subscribe: parking/plot/{plot_id}/gate_command
    Payload: { "action": "open" } or { "action": "close" }

  Subscribe: parking/plot/{plot_id}/entry_verified
    Payload: { "booking_id", "vehicle_id", "vehicle_number", "timestamp", "status" }
    (logged only; gate is driven by gate_command)

  Subscribe: parking/plot/{plot_id}/alerts
    Payload: { "type", "message", "timestamp" }
    (logged to console; future: trigger buzzer/display)
"""

import json
import logging
from typing import Callable

from hardware.gate_controller import GateController

logger = logging.getLogger(__name__)


class GateCommandHandler:
    """
    Routes incoming MQTT messages to the gate controller.

    Registered as the message handler on MQTTClient.  Handles three
    inbound topics:
      - gate_command   → opens or closes the servo gate
      - entry_verified → logs the backend's verification result
      - alerts         → logs security/device alerts

    Usage:
        handler = GateCommandHandler(gate_controller)
        mqtt_client.set_message_handler(handler.handle)
    """

    def __init__(self, gate_controller: GateController):
        """
        Initialise the gate command handler.

        Args:
            gate_controller: Configured and set-up GateController instance
        """
        self._gate = gate_controller
        logger.info("GateCommandHandler initialised")

    def handle(self, topic: str, payload: str) -> None:
        """
        Route an incoming MQTT message to the correct sub-handler.

        This is the callback registered with MQTTClient.set_message_handler().

        Args:
            topic:   Full MQTT topic string
            payload: Raw JSON payload string
        """
        # Parse JSON defensively
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            logger.error("Invalid JSON on topic %s: %s", topic, payload[:200])
            return

        if not isinstance(data, dict):
            logger.error("Expected JSON object on topic %s, got %s — ignoring", topic, type(data).__name__)
            return

        # Route by topic suffix
        suffix = topic.split("/")[-1]   # e.g. "gate_command", "entry_verified"

        if suffix == "gate_command":
            self._handle_gate_command(data)
        elif suffix == "entry_verified":
            self._handle_entry_verified(data)
        elif suffix == "alerts":
            self._handle_alert(data)
        else:
            logger.debug("No handler for topic suffix '%s' — ignoring", suffix)

    # ------------------------------------------------------------------
    # Sub-handlers
    # ------------------------------------------------------------------

    def _handle_gate_command(self, data: dict) -> None:
        """
        Process a gate_command message from the backend.

        Expected payload:
            { "action": "open" }   or
            { "action": "close" }

        The backend sends "open" after successfully validating a QR scan
        (check-in or check-out).  The Pi opens the gate; the GateController
        auto-closes after SERVO_OPEN_DURATION seconds.
        """
        action = data.get("action", "").lower()

        if action == "open":
            logger.info("GATE COMMAND: open — raising barrier")
            try:
                self._gate.open()
            except Exception as exc:
                logger.error("Error opening gate: %s", exc, exc_info=True)

        elif action == "close":
            logger.info("GATE COMMAND: close — lowering barrier")
            try:
                self._gate.close()
            except Exception as exc:
                logger.error("Error closing gate: %s", exc, exc_info=True)

        else:
            logger.warning("GATE COMMAND: unknown action '%s' — ignoring", action)

    def _handle_entry_verified(self, data: dict) -> None:
        """
        Log the backend's entry verification result.

        Payload: { "booking_id", "vehicle_id", "vehicle_number", "timestamp", "status" }

        The gate itself is controlled exclusively via gate_command.  This
        message is informational (useful for local logging / future display).
        """
        booking_id     = data.get("booking_id")
        vehicle_number = data.get("vehicle_number", "N/A")
        status         = data.get("status", "unknown")
        timestamp      = data.get("timestamp", "")

        if status == "verified":
            logger.info(
                "ENTRY VERIFIED ✓ — booking_id=%s, vehicle=%s, at=%s",
                booking_id, vehicle_number, timestamp,
            )
        else:
            logger.warning(
                "ENTRY REJECTED ✗ — booking_id=%s, vehicle=%s, status=%s",
                booking_id, vehicle_number, status,
            )

    def _handle_alert(self, data: dict) -> None:
        """
        Log a security or device alert from the backend.

        Payload: { "type", "message", "timestamp" }
        """
        alert_type = data.get("type", "unknown")
        message    = data.get("message", "")
        timestamp  = data.get("timestamp", "")
        logger.warning("ALERT [%s] @ %s — %s", alert_type, timestamp, message)
