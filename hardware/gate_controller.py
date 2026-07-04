"""
Gate Controller — NammaPark RPi Hardware Layer

Controls a single servo motor that acts as the main parking gate barrier.

Servo Positions (SG90 / MG90S at 50 Hz PWM):
  OPEN  — 7.5% duty cycle ≈ 90° (barrier raised, vehicle can pass)
  CLOSE — 2.5% duty cycle ≈ 0°  (barrier down, entry/exit blocked)

After opening, the gate auto-closes after SERVO_OPEN_DURATION seconds
(set in .env) via a background timer so vehicles are not left exposed.

Graceful Stub:
  If RPi.GPIO is not available (non-Pi environment), all GPIO calls are
  silently logged — the full MQTT + QR pipeline can still be tested on
  a development machine.
"""

import logging
import threading
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
        "RPi.GPIO not found — running in SIMULATION mode (no real GPIO output)"
    )

    class _GPIOStub:
        BCM = "BCM"
        OUT = "OUT"

        def setmode(self, mode) -> None: ...
        def setwarnings(self, flag) -> None: ...
        def setup(self, pin, mode, **kw) -> None: ...
        def cleanup(self, pins=None) -> None: ...

        class PWM:
            def __init__(self, pin, freq): ...
            def start(self, duty_cycle) -> None: ...
            def ChangeDutyCycle(self, dc) -> None: ...
            def stop(self) -> None: ...

    GPIO = _GPIOStub()


# ---------------------------------------------------------------------------
# GateController
# ---------------------------------------------------------------------------

class GateController:
    """
    Controls a single servo-driven gate barrier.

    Usage:
        gate = GateController(
            servo_pin=18,
            pwm_frequency=50,
            open_duty=7.5,
            close_duty=2.5,
            auto_close_seconds=5,
        )
        gate.setup()
        gate.open()        # raises barrier; auto-closes after N seconds
        gate.close()       # lowers barrier immediately
        gate.cleanup()     # releases GPIO on shutdown
    """

    # Time to hold servo at target before zeroing PWM (reduces jitter/heat)
    _SERVO_HOLD_SECONDS = 0.5

    def __init__(
        self,
        servo_pin: int,
        pwm_frequency: int = 50,
        open_duty: float = 7.5,
        close_duty: float = 2.5,
        auto_close_seconds: int = 5,
    ):
        """
        Initialise the gate controller.

        Args:
            servo_pin:          BCM GPIO pin wired to the servo signal wire
            pwm_frequency:      PWM frequency in Hz (50 Hz standard for SG90/MG90S)
            open_duty:          Duty cycle % for open position  (default 7.5% ≈ 90°)
            close_duty:         Duty cycle % for close position (default 2.5% ≈ 0°)
            auto_close_seconds: Seconds to wait after opening before auto-close
        """
        self._pin        = servo_pin
        self._freq       = pwm_frequency
        self._open_duty  = open_duty
        self._close_duty = close_duty
        self._auto_close = auto_close_seconds
        self._pwm: Optional[object] = None
        self._is_setup   = False
        self._is_open    = False
        self._simulation = not _GPIO_AVAILABLE

        # Auto-close timer handle
        self._close_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

        logger.info(
            "GateController initialised — pin=GPIO%d, open=%.1f%%, close=%.1f%%, "
            "auto_close=%ds, sim=%s",
            servo_pin, open_duty, close_duty, auto_close_seconds, self._simulation,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def setup(self) -> None:
        """Configure GPIO and PWM (call once at startup)."""
        if self._is_setup:
            logger.warning("GateController.setup() called more than once — skipping")
            return

        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(self._pin, GPIO.OUT)

        self._pwm = GPIO.PWM(self._pin, self._freq)
        self._pwm.start(0)   # Start idle; servo stays at current physical position

        self._is_setup = True
        logger.info("GPIO configured: servo on GPIO%d at %d Hz", self._pin, self._freq)

        # Start with gate physically closed
        self._move_to(self._close_duty, label="INIT CLOSE")

    def cleanup(self) -> None:
        """Release all GPIO resources (call at shutdown)."""
        if not self._is_setup:
            return

        self._cancel_timer()
        if self._pwm:
            self._pwm.stop()
            # Release our reference BEFORE GPIO.cleanup() so the PWM object's
            # destructor runs now (while the gpiochip is still open). Otherwise
            # rpi-lgpio's PWM.__del__ fires at interpreter exit after cleanup()
            # has freed the chip, raising "unsupported operand type(s) for &:
            # 'NoneType' and 'int'" (harmless but noisy).
            self._pwm = None
        GPIO.cleanup()
        self._is_setup = False
        logger.info("GPIO cleanup complete")

    # ------------------------------------------------------------------
    # Gate control (public API)
    # ------------------------------------------------------------------

    def open(self) -> None:
        """
        Open the gate barrier and schedule auto-close.

        Safe to call while the gate is already open — resets the timer.
        Thread-safe.
        """
        with self._lock:
            self._cancel_timer()

            if self._simulation:
                if self._auto_close and self._auto_close > 0:
                    logger.info(
                        "[SIM] GATE OPEN  (GPIO%d, duty=%.1f%%) — will auto-close in %ds",
                        self._pin, self._open_duty, self._auto_close,
                    )
                else:
                    logger.info(
                        "[SIM] GATE OPEN  (GPIO%d, duty=%.1f%%) — stays open until closed",
                        self._pin, self._open_duty,
                    )
            else:
                logger.info("GATE OPEN → GPIO%d", self._pin)
                self._move_to(self._open_duty, label="OPEN")

            self._is_open = True

            # Schedule auto-close, unless disabled (auto_close <= 0). A service
            # gate stays open for the whole session and is closed explicitly.
            if self._auto_close and self._auto_close > 0:
                self._close_timer = threading.Timer(
                    self._auto_close, self._auto_close_callback
                )
                self._close_timer.daemon = True
                self._close_timer.start()
                logger.debug("Auto-close timer set for %ds", self._auto_close)
            else:
                logger.debug("Auto-close disabled — gate will stay open until closed explicitly")

    def close(self) -> None:
        """
        Close (lower) the gate barrier immediately.

        Thread-safe; cancels any pending auto-close timer.
        """
        with self._lock:
            self._cancel_timer()

            if self._simulation:
                logger.info(
                    "[SIM] GATE CLOSE (GPIO%d, duty=%.1f%%)",
                    self._pin, self._close_duty,
                )
            else:
                logger.info("GATE CLOSE → GPIO%d", self._pin)
                self._move_to(self._close_duty, label="CLOSE")

            self._is_open = False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _move_to(self, duty_cycle: float, label: str = "") -> None:
        """Set servo duty cycle, hold briefly, then idle the signal."""
        if self._pwm is None:
            logger.error("PWM not initialised — was setup() called?")
            return
        self._pwm.ChangeDutyCycle(duty_cycle)
        time.sleep(self._SERVO_HOLD_SECONDS)
        self._pwm.ChangeDutyCycle(0)   # Idle signal to prevent jitter
        logger.debug("Servo moved: %s (duty=%.1f%%)", label, duty_cycle)

    def _auto_close_callback(self) -> None:
        """Called by the background timer to close the gate automatically."""
        logger.info("Auto-close timer fired — closing gate")
        with self._lock:
            if self._simulation:
                logger.info("[SIM] GATE AUTO-CLOSE (GPIO%d)", self._pin)
            else:
                self._move_to(self._close_duty, label="AUTO-CLOSE")
            self._is_open = False

    def _cancel_timer(self) -> None:
        """Cancel any pending auto-close timer (must be called under self._lock)."""
        if self._close_timer and self._close_timer.is_alive():
            self._close_timer.cancel()
            self._close_timer = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        """True if the gate is currently in the open position."""
        return self._is_open

    @property
    def is_simulation(self) -> bool:
        """True when running without real RPi.GPIO hardware."""
        return self._simulation
