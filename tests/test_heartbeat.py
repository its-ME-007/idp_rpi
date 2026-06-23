"""
Tests for HeartbeatService — NammaPark RPi (QR Gate Architecture)

Validates:
1. Heartbeat payload matches backend's expected format
2. Heartbeat publishes to the correct topic
3. Service starts and stops cleanly
4. Double-start / stop-before-start are no-ops (no crash)

Note: The QR-gate architecture heartbeat no longer includes
available_slots_2w / available_slots_4w — just device_id, status,
and timestamp.
"""

import json
import sys
import os
import time
import unittest
from datetime import datetime

# Ensure project root is on the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mqtt.heartbeat import HeartbeatService
from mqtt.topics import Topics


class MockPublisher:
    """Captures published messages for test assertions."""

    def __init__(self):
        self.published: list[tuple[str, str, int]] = []

    def publish(self, topic: str, payload: str, qos: int = 1) -> bool:
        self.published.append((topic, payload, qos))
        return True

    @property
    def last_published(self) -> "tuple[str, str, int] | None":
        return self.published[-1] if self.published else None

    @property
    def last_payload_dict(self) -> "dict | None":
        if self.last_published:
            return json.loads(self.last_published[1])
        return None

    def clear(self):
        self.published.clear()


class TestHeartbeatPayloadFormat(unittest.TestCase):
    """
    Validate heartbeat payload matches what the backend's
    heartbeat_handler.py expects for the QR-gate architecture.

    Required fields:
        - device_id  (str)
        - status     (str: "online")
        - timestamp  (str: ISO8601)
    """

    def setUp(self):
        self.publisher = MockPublisher()
        self.service = HeartbeatService(
            plot_id=1,
            device_id="RPi-Test-1",
            publish_fn=self.publisher.publish,
            interval_seconds=60,
        )

    def test_payload_has_required_fields(self):
        """Heartbeat payload must contain all fields expected by backend."""
        payload = json.loads(self.service._build_payload())
        for field in ("device_id", "status", "timestamp"):
            self.assertIn(field, payload, f"Missing required field: {field}")

    def test_device_id_matches(self):
        """device_id in payload must match configured device ID."""
        payload = json.loads(self.service._build_payload())
        self.assertEqual(payload["device_id"], "RPi-Test-1")

    def test_status_is_online(self):
        """status must be 'online' (backend checks this value)."""
        payload = json.loads(self.service._build_payload())
        self.assertEqual(payload["status"], "online")

    def test_timestamp_is_iso8601(self):
        """timestamp must be a valid ISO 8601 string."""
        payload = json.loads(self.service._build_payload())
        timestamp = payload["timestamp"]
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            self.fail(f"Timestamp '{timestamp}' is not valid ISO 8601")

    def test_payload_is_valid_json(self):
        """Payload must be valid JSON (not double-encoded)."""
        payload_str = self.service._build_payload()
        parsed = json.loads(payload_str)
        self.assertIsInstance(parsed, dict)

    def test_no_slot_fields_in_payload(self):
        """
        QR-gate architecture does not include slot count fields in heartbeat.
        If the backend needs them, they come from the backend's own DB.
        """
        payload = json.loads(self.service._build_payload())
        self.assertNotIn("available_slots_2w", payload)
        self.assertNotIn("available_slots_4w", payload)


class TestHeartbeatTopic(unittest.TestCase):
    """Validate heartbeat publishes to the correct topic."""

    def test_publishes_to_heartbeat_topic(self):
        """Heartbeat must publish to parking/plot/{plot_id}/heartbeat."""
        publisher = MockPublisher()
        service = HeartbeatService(
            plot_id=7,
            device_id="RPi-Test-7",
            publish_fn=publisher.publish,
            interval_seconds=1,  # Short interval for testing
        )

        service.start()
        time.sleep(1.5)  # Wait for at least one heartbeat
        service.stop()

        self.assertGreater(
            len(publisher.published), 0,
            "Should have published at least one heartbeat",
        )
        topic = publisher.published[0][0]
        self.assertEqual(topic, Topics.heartbeat(7))

    def test_heartbeat_uses_correct_plot_id_in_topic(self):
        """Plot ID must be encoded in the topic string."""
        publisher = MockPublisher()
        service = HeartbeatService(
            plot_id=42,
            device_id="RPi-Plot-42",
            publish_fn=publisher.publish,
            interval_seconds=1,
        )
        service.start()
        time.sleep(1.5)
        service.stop()

        self.assertTrue(len(publisher.published) > 0)
        self.assertIn("42", publisher.published[0][0])


class TestHeartbeatLifecycle(unittest.TestCase):
    """Test start/stop behaviour."""

    def _make_service(self, interval: int = 60) -> "tuple[HeartbeatService, MockPublisher]":
        publisher = MockPublisher()
        service = HeartbeatService(
            plot_id=1,
            device_id="RPi-Test-1",
            publish_fn=publisher.publish,
            interval_seconds=interval,
        )
        return service, publisher

    def test_start_and_stop(self):
        """Service starts and stops cleanly without errors."""
        service, _ = self._make_service()
        self.assertFalse(service.is_running)
        service.start()
        self.assertTrue(service.is_running)
        service.stop()
        self.assertFalse(service.is_running)

    def test_double_start_is_noop(self):
        """Starting an already-running service is a no-op (no exception)."""
        service, _ = self._make_service()
        service.start()
        service.start()  # Should not raise
        service.stop()

    def test_stop_before_start_is_noop(self):
        """Stopping a never-started service is a no-op (no exception)."""
        service, _ = self._make_service()
        service.stop()  # Should not raise

    def test_is_running_false_after_stop(self):
        """is_running must be False after stop()."""
        service, _ = self._make_service(interval=1)
        service.start()
        time.sleep(0.2)
        service.stop()
        self.assertFalse(service.is_running)


class TestHeartbeatQoS(unittest.TestCase):
    """Heartbeats should be published with QoS 1."""

    def test_heartbeat_qos_is_1(self):
        publisher = MockPublisher()
        service = HeartbeatService(
            plot_id=1,
            device_id="RPi-QoS-Test",
            publish_fn=publisher.publish,
            interval_seconds=1,
        )
        service.start()
        time.sleep(1.5)
        service.stop()

        self.assertTrue(len(publisher.published) > 0)
        _, _, qos = publisher.published[0]
        self.assertEqual(qos, 1)


if __name__ == "__main__":
    unittest.main()
