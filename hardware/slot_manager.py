"""
Slot Manager — NammaPark RPi Hardware Layer

Maintains the in-memory state of every physical parking slot and bridges
the MQTT command layer to the GPIO hardware layer.

Slot State Machine
------------------
                   reserve (cmd)
  FREE ──────────────────────────► RESERVED
   ▲                                  │
   │                          unlock (cmd)
   │                                  │
   │                                  ▼
  FREE ◄────────────────────── OCCUPIED
        lock (cmd) / freed (status)

Slot Types:
  2W — two-wheeler (motorcycle / scooter)
  4W — four-wheeler (car / SUV)

Thread Safety:
  All mutating operations are protected by a re-entrant lock so the
  MQTT callback thread and any other threads can safely call methods
  concurrently.
"""

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from hardware.gpio_controller import GPIOController

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class SlotState(Enum):
    FREE     = auto()   # no active booking, gate closed, green LED
    RESERVED = auto()   # booking confirmed, gate still closed, red LED
    OCCUPIED = auto()   # vehicle present, gate may be open or closed, red LED


class SlotType(str, Enum):
    TWO_WHEELER  = "2W"
    FOUR_WHEELER = "4W"


# ---------------------------------------------------------------------------
# Slot data class
# ---------------------------------------------------------------------------

@dataclass
class Slot:
    """Represents one physical parking slot."""

    slot_id:    int
    slot_type:  SlotType
    gpio_index: int          # index into GPIOController's pin arrays

    state:      SlotState  = SlotState.FREE
    booking_id: Optional[int] = None

    def __str__(self) -> str:
        return (
            f"Slot(id={self.slot_id}, type={self.slot_type.value}, "
            f"state={self.state.name}, booking={self.booking_id})"
        )


# ---------------------------------------------------------------------------
# SlotManager
# ---------------------------------------------------------------------------

class SlotManager:
    """
    Owns all Slot objects and orchestrates GPIO actions when state changes.

    Usage:
        gpio = GPIOController(servo_pins=[...], ...)
        gpio.setup()

        manager = SlotManager(
            slots_2w=[(1, 0), (2, 1)],   # (slot_id, gpio_index) pairs
            slots_4w=[(3, 2), (4, 3)],
            gpio_controller=gpio,
        )

        # On 'reserve' command:
        slot_id = manager.reserve_slot(booking_id=42, slot_type="2W")

        # On 'unlock' command:
        manager.unlock_slot(booking_id=42, slot_id=slot_id)

        # On 'lock' command:
        manager.lock_slot(slot_id=slot_id)
    """

    def __init__(
        self,
        slots_2w: list[tuple[int, int]],
        slots_4w: list[tuple[int, int]],
        gpio_controller: GPIOController,
    ):
        """
        Initialize the slot manager.

        Args:
            slots_2w:         List of (slot_id, gpio_index) for 2W slots
            slots_4w:         List of (slot_id, gpio_index) for 4W slots
            gpio_controller:  Configured and set-up GPIOController instance
        """
        self._gpio = gpio_controller
        self._lock = threading.RLock()

        # Build slot registry
        self._slots: dict[int, Slot] = {}  # slot_id → Slot

        for slot_id, gpio_index in slots_2w:
            self._slots[slot_id] = Slot(
                slot_id=slot_id,
                slot_type=SlotType.TWO_WHEELER,
                gpio_index=gpio_index,
            )

        for slot_id, gpio_index in slots_4w:
            self._slots[slot_id] = Slot(
                slot_id=slot_id,
                slot_type=SlotType.FOUR_WHEELER,
                gpio_index=gpio_index,
            )

        # Initialise LEDs for all slots to green (free)
        for slot in self._slots.values():
            self._gpio.set_led_free(slot.gpio_index)

        logger.info(
            "SlotManager ready: %d slots total (%d 2W, %d 4W)",
            len(self._slots), len(slots_2w), len(slots_4w),
        )

    # ------------------------------------------------------------------
    # MQTT Command Handlers
    # ------------------------------------------------------------------

    def reserve_slot(self, booking_id: int, slot_type: str) -> Optional[int]:
        """
        Find a free slot of the requested type, mark it reserved, and
        activate hardware indicators.

        Called when the backend sends:
            { "action": "reserve", "booking_id": <int>, "slot_type": "2W"|"4W" }

        Returns:
            The assigned slot_id on success, or None if no free slot exists.
        """
        with self._lock:
            try:
                target_type = SlotType(slot_type)
            except ValueError:
                logger.error("Unknown slot_type '%s' in reserve command", slot_type)
                return None

            # Find the first free slot of the requested type
            free_slot = self._find_free_slot(target_type)

            if free_slot is None:
                logger.warning(
                    "RESERVE FAILED — no free %s slots available (booking_id=%d)",
                    slot_type, booking_id,
                )
                return None

            # Transition: FREE → RESERVED
            free_slot.state      = SlotState.RESERVED
            free_slot.booking_id = booking_id

            logger.info(
                "RESERVE — booking_id=%d → %s",
                booking_id, free_slot,
            )

            # Hardware: blink red LED to indicate slot is assigned
            try:
                self._gpio.set_led_blink_reserved(free_slot.gpio_index)
            except Exception as exc:
                logger.error("GPIO error on reserve (LED blink): %s", exc)

            return free_slot.slot_id

    def unlock_slot(self, booking_id: int, slot_id: int) -> bool:
        """
        Open the gate/barrier for the vehicle to enter its reserved slot.

        Called when the backend sends:
            { "action": "unlock", "booking_id": <int>, "slot_id": <int> }

        Returns:
            True on success, False if the slot is in an unexpected state.
        """
        with self._lock:
            slot = self._get_slot(slot_id)
            if slot is None:
                return False

            if slot.state != SlotState.RESERVED:
                logger.warning(
                    "UNLOCK ignored — slot %d is not RESERVED (state=%s, booking=%s)",
                    slot_id, slot.state.name, slot.booking_id,
                )
                return False

            if slot.booking_id != booking_id:
                logger.warning(
                    "UNLOCK ignored — slot %d belongs to booking %s, not %d",
                    slot_id, slot.booking_id, booking_id,
                )
                return False

            # Transition: RESERVED → OCCUPIED
            slot.state = SlotState.OCCUPIED

            logger.info("UNLOCK — %s", slot)

            # Hardware: open gate
            try:
                self._gpio.open_gate(slot.gpio_index)
            except Exception as exc:
                logger.error("GPIO error on unlock (open gate): %s", exc)

            return True

    def lock_slot(self, slot_id: int) -> Optional[int]:
        """
        Close the barrier, free the slot, and update LED indicators.

        Called when the backend sends:
            { "action": "lock", "slot_id": <int> }

        Returns:
            The booking_id that was freed (for status response), or None.
        """
        with self._lock:
            slot = self._get_slot(slot_id)
            if slot is None:
                return None

            if slot.state == SlotState.FREE:
                logger.warning("LOCK ignored — slot %d is already FREE", slot_id)
                return None

            freed_booking_id = slot.booking_id

            # Transition: OCCUPIED / RESERVED → FREE
            slot.state      = SlotState.FREE
            slot.booking_id = None

            logger.info("LOCK — slot_id=%d, freed booking_id=%s", slot_id, freed_booking_id)

            # Hardware: close gate + green LED
            try:
                self._gpio.close_gate(slot.gpio_index)
                self._gpio.set_led_free(slot.gpio_index)
            except Exception as exc:
                logger.error("GPIO error on lock (close gate / set LED): %s", exc)

            return freed_booking_id

    # ------------------------------------------------------------------
    # Availability Queries
    # ------------------------------------------------------------------

    def available_count(self, slot_type: SlotType) -> int:
        """Return the number of free slots for the given type."""
        with self._lock:
            return sum(
                1 for s in self._slots.values()
                if s.slot_type == slot_type and s.state == SlotState.FREE
            )

    def available_2w(self) -> int:
        """Free 2-wheeler slot count (used by HeartbeatService)."""
        return self.available_count(SlotType.TWO_WHEELER)

    def available_4w(self) -> int:
        """Free 4-wheeler slot count (used by HeartbeatService)."""
        return self.available_count(SlotType.FOUR_WHEELER)

    def all_slots_snapshot(self) -> list[dict]:
        """
        Return a snapshot of all slot states (useful for diagnostics).

        Returns:
            List of dicts: [{"slot_id", "slot_type", "state", "booking_id"}, ...]
        """
        with self._lock:
            return [
                {
                    "slot_id":    s.slot_id,
                    "slot_type":  s.slot_type.value,
                    "state":      s.state.name,
                    "booking_id": s.booking_id,
                }
                for s in sorted(self._slots.values(), key=lambda x: x.slot_id)
            ]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _find_free_slot(self, slot_type: SlotType) -> Optional[Slot]:
        """Return the first FREE slot of the given type, or None."""
        return next(
            (
                s for s in sorted(self._slots.values(), key=lambda x: x.slot_id)
                if s.slot_type == slot_type and s.state == SlotState.FREE
            ),
            None,
        )

    def _get_slot(self, slot_id: int) -> Optional[Slot]:
        """Look up a slot by ID and log a warning if not found."""
        slot = self._slots.get(slot_id)
        if slot is None:
            logger.warning("Slot %d not found in registry", slot_id)
        return slot
