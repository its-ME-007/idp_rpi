"""
GPIO Controller — NammaPark RPi Hardware Layer

Controls physical hardware connected to the Raspberry Pi's GPIO pins:
  - Servo motors  : control the gate/barrier for each parking slot
  - LED indicators: green (free), red (occupied/reserved) per slot

Pin Mapping (configured via .env / config.py):
  Each slot has up to 3 GPIO pins:
    SERVO_PIN_<n>     — PWM signal to MG90S / SG90 servo (gate barrier)
    LED_GREEN_PIN_<n> — Green LED anode (slot free)
    LED_RED_PIN_<n>   — Red   LED anode (slot reserved / occupied)

Servo Positions:
  GATE_OPEN_DUTY  (default 7.5%) → 90°, barrier raised
  GATE_CLOSE_DUTY (default 2.5%) → 0°,  barrier down/blocking

Graceful Stub:
  If RPi.GPIO is not available (non-Pi environment), a mock module is
  used instead so the MQTT and business logic can still be developed
  and tested on a regular PC without hardware.
"""

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Try to import real RPi.GPIO; fall back to a stub on non-Pi environments
# ---------------------------------------------------------------------------
try:
    import RPi.GPIO as GPIO  # type: ignore
    _GPIO_AVAILABLE = True
    logger.info("RPi.GPIO loaded — real hardware mode active")
except ImportError:
    _GPIO_AVAILABLE = False
    logger.warning(
        "RPi.GPIO not found — running in SIMULATION mode (no real hardware output)"
    )

    class _GPIOStub:  # noqa: D101  (simple dev stub)
        """Minimal stub that mirrors the RPi.GPIO API used here."""

        BCM = "BCM"
        OUT = "OUT"
        HIGH = True
        LOW = False

        def setmode(self, mode) -> None: ...       # noqa: E704
        def setwarnings(self, flag) -> None: ...   # noqa: E704
        def setup(self, pin, mode, **kw) -> None: ...  # noqa: E704
        def output(self, pin, value) -> None: ...  # noqa: E704
        def cleanup(self, pins=None) -> None: ...  # noqa: E704

        class PWM:  # noqa: D106
            def __init__(self, pin, freq): ...         # noqa: E704
            def start(self, duty_cycle) -> None: ...   # noqa: E704
            def ChangeDutyCycle(self, dc) -> None: ...  # noqa: E704
            def stop(self) -> None: ...                # noqa: E704

    GPIO = _GPIOStub()


# ---------------------------------------------------------------------------
# GPIOController
# ---------------------------------------------------------------------------

class GPIOController:
    """
    Manages all GPIO interactions for one parking plot.

    Each slot has an independent servo and a pair of LED indicators.
    All pin numbers must be BCM-numbered GPIO pins.

    Usage:
        controller = GPIOController(
            servo_pins=[18, 23],
            led_green_pins=[24, 25],
            led_red_pins=[8, 7],
        )
        controller.setup()
        controller.open_gate(slot_index=0)
        controller.set_led_reserved(slot_index=0)
        controller.close_gate(slot_index=0)
        controller.set_led_free(slot_index=0)
        controller.cleanup()
    """

    # Servo duty-cycle constants (50 Hz PWM)
    # SG90 / MG90S: 2.5% ≈ 0°, 7.5% ≈ 90°, 12.5% ≈ 180°
    GATE_OPEN_DUTY  = 7.5   # barrier raised
    GATE_CLOSE_DUTY = 2.5   # barrier lowered / blocking

    # How long to hold the servo at the target position before stopping PWM
    SERVO_HOLD_SECONDS = 0.5

    def __init__(
        self,
        servo_pins: list[int],
        led_green_pins: list[int],
        led_red_pins: list[int],
        pwm_frequency: int = 50,
    ):
        """
        Initialize the GPIO controller.

        Args:
            servo_pins:      BCM pin numbers for each slot's servo motor
            led_green_pins:  BCM pin numbers for each slot's green LED
            led_red_pins:    BCM pin numbers for each slot's red LED
            pwm_frequency:   PWM frequency in Hz (default 50 Hz for servos)

        Note: All three lists must have the same length (one entry per slot).
        """
        if not (len(servo_pins) == len(led_green_pins) == len(led_red_pins)):
            raise ValueError(
                f"servo_pins ({len(servo_pins)}), led_green_pins ({len(led_green_pins)}) "
                f"and led_red_pins ({len(led_red_pins)}) must all have the same length."
            )

        self._servo_pins      = servo_pins
        self._led_green_pins  = led_green_pins
        self._led_red_pins    = led_red_pins
        self._pwm_frequency   = pwm_frequency
        self._pwm_objects: dict[int, object] = {}  # pin → GPIO.PWM instance
        self._is_setup        = False
        self._simulation      = not _GPIO_AVAILABLE

        logger.info(
            "GPIOController created for %d slots | servo=%s | green=%s | red=%s | sim=%s",
            len(servo_pins), servo_pins, led_green_pins, led_red_pins, self._simulation,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def setup(self) -> None:
        """
        Configure all GPIO pins (call once at startup).

        Sets BCM numbering, configures all pins as outputs, initialises
        PWM objects for servos, and puts all slots into the 'free' state
        (gate closed, green LED on).
        """
        if self._is_setup:
            logger.warning("GPIOController.setup() called more than once — skipping")
            return

        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        all_output_pins = self._led_green_pins + self._led_red_pins
        for pin in all_output_pins:
            GPIO.setup(pin, GPIO.OUT)

        for pin in self._servo_pins:
            GPIO.setup(pin, GPIO.OUT)
            pwm = GPIO.PWM(pin, self._pwm_frequency)
            pwm.start(0)  # Start with 0% duty (servo inactive)
            self._pwm_objects[pin] = pwm

        self._is_setup = True
        logger.info("GPIO pins configured successfully (BCM mode)")

        # Initialise all slots to free state
        for idx in range(len(self._servo_pins)):
            self._close_gate_raw(idx)
            self._set_led_raw(idx, green=True)

    def cleanup(self) -> None:
        """Release all GPIO resources (call at shutdown)."""
        if not self._is_setup:
            return

        # Stop all PWM
        for pwm in self._pwm_objects.values():
            pwm.stop()

        GPIO.cleanup()
        self._is_setup = False
        logger.info("GPIO cleanup complete")

    # ------------------------------------------------------------------
    # Gate (servo) control
    # ------------------------------------------------------------------

    def open_gate(self, slot_index: int) -> None:
        """
        Open the barrier for the given slot (allow vehicle entry/exit).

        Args:
            slot_index: 0-based slot index
        """
        self._validate_index(slot_index)
        slot_num = slot_index + 1  # human-readable

        if self._simulation:
            logger.info("[SIM] Gate OPEN  → slot %d (servo pin %d, duty %.1f%%)",
                        slot_num, self._servo_pins[slot_index], self.GATE_OPEN_DUTY)
            return

        logger.info("Gate OPEN → slot %d", slot_num)
        self._move_servo(slot_index, self.GATE_OPEN_DUTY)

    def close_gate(self, slot_index: int) -> None:
        """
        Close/lock the barrier for the given slot.

        Args:
            slot_index: 0-based slot index
        """
        self._validate_index(slot_index)
        self._close_gate_raw(slot_index)

    # ------------------------------------------------------------------
    # LED indicator control
    # ------------------------------------------------------------------

    def set_led_free(self, slot_index: int) -> None:
        """Green LED on, red LED off → slot is available."""
        self._validate_index(slot_index)
        self._set_led_raw(slot_index, green=True)
        logger.info("LED → slot %d : FREE (green)", slot_index + 1)

    def set_led_reserved(self, slot_index: int) -> None:
        """Red LED on, green LED off → slot is reserved or occupied."""
        self._validate_index(slot_index)
        self._set_led_raw(slot_index, green=False)
        logger.info("LED → slot %d : RESERVED (red)", slot_index + 1)

    def set_led_blink_reserved(self, slot_index: int, blinks: int = 3) -> None:
        """
        Briefly blink the red LED to alert the user that their slot is ready.

        Useful after a 'reserve' command to guide the driver to their slot.

        Args:
            slot_index: 0-based slot index
            blinks:     Number of blink cycles (default 3)
        """
        self._validate_index(slot_index)
        slot_num = slot_index + 1

        if self._simulation:
            logger.info("[SIM] LED BLINK (reserved) → slot %d (%d blinks)", slot_num, blinks)
            self._set_led_raw(slot_index, green=False)
            return

        logger.info("LED BLINK (reserved) → slot %d (%d blinks)", slot_num, blinks)
        for _ in range(blinks):
            self._set_led_raw(slot_index, green=False)
            time.sleep(0.3)
            self._set_led_raw(slot_index, green=True)
            time.sleep(0.3)
        # End in reserved (red on)
        self._set_led_raw(slot_index, green=False)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate_index(self, slot_index: int) -> None:
        if slot_index < 0 or slot_index >= len(self._servo_pins):
            raise IndexError(
                f"slot_index {slot_index} is out of range "
                f"(controller manages {len(self._servo_pins)} slots)"
            )

    def _move_servo(self, slot_index: int, duty_cycle: float) -> None:
        """Set servo duty cycle, hold briefly, then set to 0 to reduce jitter."""
        pin = self._servo_pins[slot_index]
        pwm = self._pwm_objects.get(pin)
        if pwm is None:
            logger.error("No PWM object for servo pin %d", pin)
            return

        pwm.ChangeDutyCycle(duty_cycle)
        time.sleep(self.SERVO_HOLD_SECONDS)
        pwm.ChangeDutyCycle(0)  # Disable signal to avoid servo jitter/heat

    def _close_gate_raw(self, slot_index: int) -> None:
        slot_num = slot_index + 1
        if self._simulation:
            logger.info("[SIM] Gate CLOSE → slot %d (servo pin %d, duty %.1f%%)",
                        slot_num, self._servo_pins[slot_index], self.GATE_CLOSE_DUTY)
            return
        logger.info("Gate CLOSE → slot %d", slot_num)
        self._move_servo(slot_index, self.GATE_CLOSE_DUTY)

    def _set_led_raw(self, slot_index: int, green: bool) -> None:
        green_pin = self._led_green_pins[slot_index]
        red_pin   = self._led_red_pins[slot_index]

        if self._simulation:
            colour = "GREEN" if green else "RED"
            logger.debug("[SIM] LED %s → slot %d", colour, slot_index + 1)
            return

        GPIO.output(green_pin, GPIO.HIGH if green else GPIO.LOW)
        GPIO.output(red_pin,   GPIO.LOW  if green else GPIO.HIGH)

    @property
    def slot_count(self) -> int:
        """Number of slots this controller manages."""
        return len(self._servo_pins)

    @property
    def is_simulation(self) -> bool:
        """True when running without real RPi.GPIO hardware."""
        return self._simulation
