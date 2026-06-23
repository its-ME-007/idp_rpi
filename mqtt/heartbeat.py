"""
Heartbeat Service — NammaPark RPi Device (QR Gate Architecture)

Publishes periodic heartbeat messages to the backend via MQTT.
The backend uses these to track device health and mark offline devices.

Topic: parking/plot/{plot_id}/heartbeat

Payload (matches backend's heartbeat_handler.py):
    {
        "device_id":  "<device_name>",
        "status":     "online",
        "timestamp":  "<ISO8601>"
    }

Note: available_slots_2w / available_slots_4w are not included in the
QR-gate architecture (no slot management on device side).
"""

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from mqtt.topics import Topics

logger = logging.getLogger(__name__)


class HeartbeatService:
    """
    Background service that publishes periodic heartbeat messages.

    Runs in a daemon thread so it doesn't block the main event loop.
    The heartbeat interval is configurable (default: 60 seconds).

    Usage:
        service = HeartbeatService(
            plot_id=1,
            device_id="RPi-Plot-1",
            publish_fn=mqtt_client.publish,
            interval_seconds=60,
        )
        service.start()
        # ... application runs ...
        service.stop()
    """

    def __init__(
        self,
        plot_id: int,
        device_id: str,
        publish_fn: Callable[[str, str, int], bool],
        interval_seconds: int = 60,
    ):
        """
        Initialise the heartbeat service.

        Args:
            plot_id:          Parking plot ID this device manages
            device_id:        Unique device identifier
            publish_fn:       Function to publish MQTT messages — (topic, payload, qos) -> bool
            interval_seconds: Time between heartbeats in seconds (min 10)
        """
        self.plot_id          = plot_id
        self.device_id        = device_id
        self._publish_fn      = publish_fn
        self.interval_seconds = interval_seconds

        # Thread management
        self._running     = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event  = threading.Event()

        logger.info(
            "Heartbeat service initialised: device=%s, plot=%d, interval=%ds",
            device_id, plot_id, interval_seconds,
        )

    def _build_payload(self) -> str:
        """Build the heartbeat JSON payload."""
        return json.dumps({
            "device_id": self.device_id,
            "status":    "online",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def _heartbeat_loop(self) -> None:
        """Background thread: publish heartbeats at the configured interval."""
        logger.info("Heartbeat loop started (interval=%ds)", self.interval_seconds)

        while not self._stop_event.is_set():
            try:
                topic   = Topics.heartbeat(self.plot_id)
                payload = self._build_payload()
                success = self._publish_fn(topic, payload, 1)

                if success:
                    logger.debug("Heartbeat sent → %s", topic)
                else:
                    logger.warning("Heartbeat publish failed (will retry next interval)")

            except Exception as exc:
                logger.error("Error in heartbeat loop: %s", exc, exc_info=True)

            self._stop_event.wait(timeout=self.interval_seconds)

        logger.info("Heartbeat loop stopped")

    def start(self) -> None:
        """Start the heartbeat background thread."""
        if self._running:
            logger.warning("Heartbeat service already running")
            return

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._heartbeat_loop,
            name="heartbeat-service",
            daemon=True,
        )
        self._thread.start()
        logger.info("Heartbeat service started")

    def stop(self) -> None:
        """Stop the heartbeat background thread."""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Heartbeat service stopped")

    @property
    def is_running(self) -> bool:
        """True if the heartbeat service is currently running."""
        return self._running
