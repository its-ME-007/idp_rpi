"""
Tests for Heartbeat Service

Validates:
1. Heartbeat payload matches backend's expected format
2. Heartbeat publishes to the correct topic
3. Slot count updates are reflected in payloads
4. Service starts and stops cleanly
"""

import json
import sys
import os
import time
import unittest

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
    def last_published(self) -> tuple[str, str, int] | None:
        return self.published[-1] if self.published else None

    @property
    def last_payload_dict(self) -> dict | None:
        if self.last_published:
            return json.loads(self.last_published[1])
        return None

    def clear(self):
        self.published.clear()


class TestHeartbeatPayloadFormat(unittest.TestCase):
    """
    Validate heartbeat payload matches what the backend's
    heartbeat_handler.py expects.

    Required fields:
        - device_id (str)
        - status (str: "online")
        - timestamp (str: ISO8601)
        - available_slots_2w (int)
        - available_slots_4w (int)
    """

    def setUp(self):
        self.publisher = MockPublisher()
        self.service = HeartbeatService(
            plot_id=1,
            device_id="RPi-Test-1",
            publish_fn=self.publisher.publish,
            interval_seconds=60,
            total_slots_2w=5,
            total_slots_4w=3,
        )

    def test_payload_has_required_fields(self):
        """Heartbeat payload must contain all fields expected by backend."""
        payload_str = self.service._build_payload()
        payload = json.loads(payload_str)

        required_fields = ["device_id", "status", "timestamp", "available_slots_2w", "available_slots_4w"]
        for field in required_fields:
            self.assertIn(field, payload, f"Missing required field: {field}")

    def test_device_id_matches(self):
        """device_id in payload must match configured device ID."""
        payload = json.loads(self.service._build_payload())
        self.assertEqual(payload["device_id"], "RPi-Test-1")

    def test_status_is_online(self):
        """status must be 'online' (backend checks for this value)."""
        payload = json.loads(self.service._build_payload())
        self.assertEqual(payload["status"], "online")

    def test_timestamp_is_iso8601(self):
        """timestamp must be a valid ISO 8601 string."""
        payload = json.loads(self.service._build_payload())
        timestamp = payload["timestamp"]

        # Should not throw — validates ISO format
        from datetime import datetime
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            self.fail(f"Timestamp '{timestamp}' is not valid ISO 8601")

    def test_slot_counts_are_integers(self):
        """Slot counts must be integers, matching backend expectations."""
        payload = json.loads(self.service._build_payload())
        self.assertIsInstance(payload["available_slots_2w"], int)
        self.assertIsInstance(payload["available_slots_4w"], int)

    def test_default_slot_counts(self):
        """Default slot counts match constructor values."""
        payload = json.loads(self.service._build_payload())
        self.assertEqual(payload["available_slots_2w"], 5)
        self.assertEqual(payload["available_slots_4w"], 3)

    def test_payload_is_valid_json(self):
        """Payload must be valid JSON (not double-encoded)."""
        payload_str = self.service._build_payload()
        parsed = json.loads(payload_str)
        self.assertIsInstance(parsed, dict)


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

        self.assertGreater(len(publisher.published), 0, "Should have published at least one heartbeat")

        topic = publisher.published[0][0]
        self.assertEqual(topic, "parking/plot/7/heartbeat")


class TestSlotCountUpdates(unittest.TestCase):
    """Test that slot count updates are reflected in payloads."""

    def test_update_slot_counts(self):
        """Updated slot counts appear in subsequent heartbeat payloads."""
        publisher = MockPublisher()
        service = HeartbeatService(
            plot_id=1,
            device_id="RPi-Test-1",
            publish_fn=publisher.publish,
            total_slots_2w=10,
            total_slots_4w=5,
        )

        # Update counts
        service.update_slot_counts(available_2w=3, available_4w=1)

        payload = json.loads(service._build_payload())
        self.assertEqual(payload["available_slots_2w"], 3)
        self.assertEqual(payload["available_slots_4w"], 1)


class TestHeartbeatLifecycle(unittest.TestCase):
    """Test start/stop behavior."""

    def test_start_and_stop(self):
        """Service starts and stops cleanly without errors."""
        publisher = MockPublisher()
        service = HeartbeatService(
            plot_id=1,
            device_id="RPi-Test-1",
            publish_fn=publisher.publish,
            interval_seconds=60,
        )

        self.assertFalse(service.is_running)
        service.start()
        self.assertTrue(service.is_running)
        service.stop()
        self.assertFalse(service.is_running)

    def test_double_start(self):
        """Starting an already-running service is a no-op."""
        publisher = MockPublisher()
        service = HeartbeatService(
            plot_id=1,
            device_id="RPi-Test-1",
            publish_fn=publisher.publish,
            interval_seconds=60,
        )

        service.start()
        service.start()  # Should not raise
        service.stop()

    def test_stop_before_start(self):
        """Stopping a never-started service is a no-op."""
        publisher = MockPublisher()
        service = HeartbeatService(
            plot_id=1,
            device_id="RPi-Test-1",
            publish_fn=publisher.publish,
            interval_seconds=60,
        )

        service.stop()  # Should not raise


if __name__ == "__main__":
    unittest.main()
