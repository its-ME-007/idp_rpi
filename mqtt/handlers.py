"""
Command Dispatcher and Handler Stubs

Routes incoming MQTT command messages to the appropriate handler
based on the "action" field in the JSON payload.

The backend publishes commands to: parking/plot/{plot_id}/command

Expected command payloads:
    Reserve:  { "action": "reserve",  "booking_id": <int>, "slot_type": "2W"|"4W" }
    Unlock:   { "action": "unlock",   "booking_id": <int>, "slot_id": <int> }
    Lock:     { "action": "lock",     "slot_id": <int> }

After processing a command, the RPi publishes a status response to:
    parking/plot/{plot_id}/status

Status response payloads:
    Reserved: { "action": "reserved", "booking_id": <int>, "slot_id": <int> }
    Freed:    { "action": "freed",    "booking_id": <int>, "slot_id": <int> }
"""

import json
import logging
from typing import Callable, Optional

from mqtt.topics import Topics

logger = logging.getLogger(__name__)


class CommandDispatcher:
    """
    Dispatches incoming MQTT command messages to registered action handlers.

    Each handler is a function that processes a specific action type
    (reserve, unlock, lock) and optionally returns a status response
    to be published back to the backend.

    Usage:
        dispatcher = CommandDispatcher(plot_id=1, publish_fn=mqtt_client.publish)
        mqtt_client.set_message_handler(dispatcher.dispatch)
    """

    def __init__(self, plot_id: int, publish_fn: Callable[[str, str, int], bool]):
        """
        Initialize the command dispatcher.

        Args:
            plot_id: The plot ID this device manages
            publish_fn: Function to publish MQTT messages — signature: (topic, payload, qos) -> bool
        """
        self.plot_id = plot_id
        self._publish_fn = publish_fn

        # Action → handler mapping
        self._handlers: dict[str, Callable] = {
            "reserve": self._handle_reserve,
            "unlock": self._handle_unlock,
            "lock": self._handle_lock,
        }

        # Slot allocation tracking (simple in-memory state for now)
        # Maps booking_id → assigned slot_id
        self._slot_assignments: dict[int, int] = {}
        self._next_slot_id: int = 1  # Auto-incrementing slot ID

        logger.info("Command dispatcher initialized for plot %d", plot_id)

    def dispatch(self, topic: str, payload: str) -> None:
        """
        Route an incoming MQTT message to the appropriate handler.

        This is the callback registered with MQTTClient.set_message_handler().

        Args:
            topic: MQTT topic the message arrived on
            payload: Raw JSON string payload
        """
        # Parse JSON
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            logger.error("Invalid JSON in command payload: %s", payload[:200])
            return

        # Extract action
        action = data.get("action")
        if not action:
            logger.error("Missing 'action' field in command: %s", data)
            return

        # Find and execute handler
        handler = self._handlers.get(action)
        if handler:
            logger.info("Dispatching action '%s' — payload: %s", action, data)
            try:
                handler(data)
            except Exception as e:
                logger.error("Error handling action '%s': %s", action, e, exc_info=True)
        else:
            logger.warning("Unknown action '%s' received. Ignoring.", action)

    def _publish_status(self, payload: dict) -> bool:
        """
        Publish a status response to the backend.

        Args:
            payload: Status payload dict (will be JSON-serialized)

        Returns:
            True if published successfully
        """
        topic = Topics.status(self.plot_id)
        payload_str = json.dumps(payload)
        logger.info("Publishing status response → %s: %s", topic, payload_str)
        return self._publish_fn(topic, payload_str, 1)

    # =========================================================================
    # Action Handlers (stubs — hardware control will be added later)
    # =========================================================================

    def _handle_reserve(self, data: dict) -> None:
        """
        Handle a 'reserve' command from the backend.

        Expected payload:
            { "action": "reserve", "booking_id": <int>, "slot_type": "2W"|"4W" }

        This should:
        1. Find a free physical slot of the requested type
        2. Mark it as reserved
        3. Respond with the assigned slot_id

        Currently: assigns a simulated slot_id and publishes confirmation.
        TODO: Integrate with actual hardware slot sensors/actuators.
        """
        booking_id = data.get("booking_id")
        slot_type = data.get("slot_type")

        if booking_id is None or slot_type is None:
            logger.error("Reserve command missing required fields: booking_id=%s, slot_type=%s", booking_id, slot_type)
            return

        # --- STUB: Assign a simulated slot ID ---
        # In production, this will query physical sensors to find a free slot
        assigned_slot_id = self._next_slot_id
        self._next_slot_id += 1
        self._slot_assignments[booking_id] = assigned_slot_id

        logger.info(
            "RESERVE — booking_id=%d, slot_type=%s → assigned slot_id=%d",
            booking_id, slot_type, assigned_slot_id,
        )
        # TODO: Activate hardware indicator (LED/display) for the assigned slot

        # Publish confirmation back to backend
        self._publish_status({
            "action": "reserved",
            "booking_id": booking_id,
            "slot_id": assigned_slot_id,
        })

    def _handle_unlock(self, data: dict) -> None:
        """
        Handle an 'unlock' command from the backend.

        Expected payload:
            { "action": "unlock", "booking_id": <int>, "slot_id": <int> }

        This should:
        1. Unlock the physical barrier/gate for the specified slot
        2. Allow the user's vehicle to enter

        Currently: logs the action.
        TODO: Activate servo/gate mechanism for the specified slot.
        """
        booking_id = data.get("booking_id")
        slot_id = data.get("slot_id")

        if booking_id is None or slot_id is None:
            logger.error("Unlock command missing required fields: booking_id=%s, slot_id=%s", booking_id, slot_id)
            return

        logger.info(
            "UNLOCK — booking_id=%d, slot_id=%d → barrier opened",
            booking_id, slot_id,
        )
        # TODO: Trigger servo motor to open gate/barrier for this slot

    def _handle_lock(self, data: dict) -> None:
        """
        Handle a 'lock' command from the backend.

        Expected payload:
            { "action": "lock", "slot_id": <int> }

        This should:
        1. Lock the physical barrier/gate for the specified slot
        2. Free the slot for future bookings

        Currently: logs the action and publishes freed response.
        TODO: Activate servo/gate mechanism to lock the slot.
        """
        slot_id = data.get("slot_id")

        if slot_id is None:
            logger.error("Lock command missing required field: slot_id=%s", slot_id)
            return

        # Find the booking for this slot (if tracked)
        booking_id = None
        for bid, sid in self._slot_assignments.items():
            if sid == slot_id:
                booking_id = bid
                break

        logger.info(
            "LOCK — slot_id=%d, booking_id=%s → barrier closed, slot freed",
            slot_id, booking_id,
        )
        # TODO: Trigger servo motor to close gate/barrier for this slot

        # Clean up tracking
        if booking_id is not None:
            self._slot_assignments.pop(booking_id, None)

            # Publish freed status back to backend
            self._publish_status({
                "action": "freed",
                "booking_id": booking_id,
                "slot_id": slot_id,
            })

    def get_active_reservations(self) -> dict[int, int]:
        """
        Get currently active slot assignments.

        Returns:
            Dict mapping booking_id → slot_id
        """
        return dict(self._slot_assignments)
