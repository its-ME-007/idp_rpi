"""
Buzzer Controller — NammaPark RPi Hardware Layer

Controls an active buzzer (GPIO HIGH = on, LOW = off).
Used to alert users before the gate barrier opens.

Wiring:
  Buzzer + → GPIO pin (BCM numbering, default GPIO24)
  Buzzer - → GND

If RPi.GPIO is unavailable (non-Pi environment) all calls are
simulated and logged so the pipeline can still be tested on a laptop.
"""

import logging
import time

logger = logging.getLogger(__name__)

try:
    import RPi.GPIO as GPIO  # type: ignore
    _GPIO_AVAILABLE = True
except ImportError:
    _GPIO_AVAILABLE = False

    class _GPIOStub:
        BCM = "BCM"
        OUT = "OUT"
        HIGH = True
        LOW  = False

        def setup(self, pin, mode, **kw): ...
        def output(self, pin, state): ...

    GPIO = _GPIOStub()


class BuzzerController:
    """
    Active buzzer controller.

    Usage:
        buzzer = BuzzerController(pin=24, buzz_seconds=3.0)
        buzzer.setup()
        buzzer.buzz()      # blocks for buzz_seconds then stops
        buzzer.cleanup()
    """

    def __init__(self, pin: int = 24, buzz_seconds: float = 3.0):
        self._pin         = pin
        self._buzz_secs   = buzz_seconds
        self._simulation  = not _GPIO_AVAILABLE
        self._is_setup    = False
        logger.info(
            "BuzzerController initialised — pin=GPIO%d, duration=%.1fs, sim=%s",
            pin, buzz_seconds, self._simulation,
        )

    def setup(self) -> None:
        """Configure the buzzer GPIO pin as output (starts HIGH = off for low-level trigger)."""
        if self._is_setup:
            return
        if not self._simulation:
            GPIO.setup(self._pin, GPIO.OUT, initial=GPIO.HIGH)
        self._is_setup = True
        logger.info("Buzzer ready on GPIO%d", self._pin)

    def buzz(self, duration: float | None = None) -> None:
        """
        Sound the buzzer for `duration` seconds (blocking).
        Low-level trigger: GPIO LOW = on, GPIO HIGH = off.
        """
        dur = duration if duration is not None else self._buzz_secs
        if self._simulation:
            logger.info("[SIM] Buzzer ON for %.1fs", dur)
            time.sleep(dur)
            logger.info("[SIM] Buzzer OFF")
            return
        try:
            GPIO.output(self._pin, GPIO.LOW)   # LOW = on (low-level trigger)
            logger.info("Buzzer ON for %.1fs", dur)
            time.sleep(dur)
            GPIO.output(self._pin, GPIO.HIGH)  # HIGH = off
            logger.info("Buzzer OFF")
        except Exception as exc:
            logger.error("Buzzer error: %s", exc)

    def cleanup(self) -> None:
        """Ensure buzzer is off and release pin."""
        if not self._simulation and self._is_setup:
            try:
                GPIO.output(self._pin, GPIO.HIGH)  # HIGH = off
            except Exception:
                pass
        self._is_setup = False
