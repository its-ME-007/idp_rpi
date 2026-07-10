"""
LED Indicator — NammaPark RPi Hardware Layer

Controls a single LED on a GPIO pin (active HIGH).
Turns ON when the gate opens, OFF when the gate closes.

Wiring:
  LED anode (long leg) → GPIO pin (BCM numbering, default GPIO23 = physical pin 16)
  LED cathode (short leg) → GND (e.g. physical pin 14)

If RPi.GPIO is unavailable (non-Pi environment) all calls are
simulated and logged so the pipeline can still be tested on a laptop.
"""

import logging

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

        def setmode(self, mode): ...
        def setwarnings(self, flag): ...
        def setup(self, pin, mode, **kw): ...
        def output(self, pin, state): ...
        def cleanup(self, pins=None): ...

    GPIO = _GPIOStub()


class LEDIndicator:
    """
    Simple LED indicator.

    Usage:
        led = LEDIndicator(pin=23)
        led.setup()
        led.on()
        led.off()
        led.cleanup()
    """

    def __init__(self, pin: int = 23):
        self._pin        = pin
        self._simulation = not _GPIO_AVAILABLE
        self._is_setup   = False
        logger.info("LEDIndicator initialised — pin=GPIO%d, sim=%s", pin, self._simulation)

    def setup(self) -> None:
        """Configure the LED GPIO pin as output (starts LOW = off)."""
        if self._is_setup:
            return
        if not self._simulation:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(self._pin, GPIO.OUT, initial=GPIO.LOW)
        self._is_setup = True
        logger.info("LED ready on GPIO%d", self._pin)

    def on(self) -> None:
        """Turn the LED on."""
        if self._simulation:
            logger.info("[SIM] LED ON  (GPIO%d)", self._pin)
            return
        try:
            GPIO.output(self._pin, GPIO.HIGH)
            logger.info("LED ON  (GPIO%d)", self._pin)
        except Exception as exc:
            logger.error("LED on() error: %s", exc)

    def off(self) -> None:
        """Turn the LED off."""
        if self._simulation:
            logger.info("[SIM] LED OFF (GPIO%d)", self._pin)
            return
        try:
            GPIO.output(self._pin, GPIO.LOW)
            logger.info("LED OFF (GPIO%d)", self._pin)
        except Exception as exc:
            logger.error("LED off() error: %s", exc)

    def cleanup(self) -> None:
        """Ensure LED is off and release pin."""
        if not self._simulation and self._is_setup:
            try:
                GPIO.output(self._pin, GPIO.LOW)
                GPIO.cleanup(self._pin)
            except Exception:
                pass
        self._is_setup = False
        logger.info("LED cleanup complete (GPIO%d)", self._pin)
