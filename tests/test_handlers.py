"""
Tests for Command Dispatcher and Handlers

Validates:
1. Commands are dispatched to the correct handler based on action
2. Reserve handler publishes 'reserved' status with slot_id
3. Lock handler publishes 'freed' status
4. Malformed payloads are handled gracefully (no crash)
5. Unknown actions are logged and ignored
"""

import json
import sys
import os
import unittest

# Ensure project root is on the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mqtt.handlers import CommandDispatcher
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


class TestCommandDispatcher(unittest.TestCase):
    """Test command dispatch routing."""

    def setUp(self):
        self.publisher = MockPublisher()
        self.dispatcher = CommandDispatcher(plot_id=1, publish_fn=self.publisher.publish)

    def test_reserve_command_dispatches(self):
        """Reserve command triggers handler and publishes 'reserved' status."""
        payload = json.dumps({
            "action": "reserve",
            "booking_id": 101,
            "slot_type": "2W"
        })
        self.dispatcher.dispatch("parking/plot/1/command", payload)

        # Should have published a status response
        self.assertEqual(len(self.publisher.published), 1)

        topic, response_str, qos = self.publisher.published[0]
        response = json.loads(response_str)

        self.assertEqual(topic, "parking/plot/1/status")
        self.assertEqual(response["action"], "reserved")
        self.assertEqual(response["booking_id"], 101)
        self.assertIn("slot_id", response)
        self.assertIsInstance(response["slot_id"], int)

    def test_reserve_assigns_incrementing_slot_ids(self):
        """Each reserve gets a unique slot_id."""
        for booking_id in [1, 2, 3]:
            payload = json.dumps({
                "action": "reserve",
                "booking_id": booking_id,
                "slot_type": "4W"
            })
            self.dispatcher.dispatch("parking/plot/1/command", payload)

        # Should have 3 publishes with distinct slot_ids
        slot_ids = [json.loads(p[1])["slot_id"] for p in self.publisher.published]
        self.assertEqual(len(set(slot_ids)), 3, "Each reservation should get a unique slot_id")

    def test_unlock_command_dispatches(self):
        """Unlock command is handled without publishing status (log-only for now)."""
        payload = json.dumps({
            "action": "unlock",
            "booking_id": 101,
            "slot_id": 5
        })
        self.dispatcher.dispatch("parking/plot/1/command", payload)

        # Unlock doesn't publish a status response (just activates hardware)
        self.assertEqual(len(self.publisher.published), 0)

    def test_lock_command_publishes_freed(self):
        """Lock command publishes 'freed' status if booking was tracked."""
        # First reserve a slot
        reserve_payload = json.dumps({
            "action": "reserve",
            "booking_id": 201,
            "slot_type": "2W"
        })
        self.dispatcher.dispatch("parking/plot/1/command", reserve_payload)

        # Get the assigned slot_id
        reserved_response = json.loads(self.publisher.published[0][1])
        slot_id = reserved_response["slot_id"]

        self.publisher.clear()

        # Now lock that slot
        lock_payload = json.dumps({
            "action": "lock",
            "slot_id": slot_id
        })
        self.dispatcher.dispatch("parking/plot/1/command", lock_payload)

        # Should publish 'freed' status
        self.assertEqual(len(self.publisher.published), 1)
        response = json.loads(self.publisher.published[0][1])
        self.assertEqual(response["action"], "freed")
        self.assertEqual(response["booking_id"], 201)
        self.assertEqual(response["slot_id"], slot_id)

    def test_lock_unknown_slot_no_publish(self):
        """Lock for an untracked slot doesn't publish (no booking to free)."""
        payload = json.dumps({
            "action": "lock",
            "slot_id": 999
        })
        self.dispatcher.dispatch("parking/plot/1/command", payload)

        # No status published for unknown slot
        self.assertEqual(len(self.publisher.published), 0)


class TestMalformedPayloads(unittest.TestCase):
    """Test graceful handling of bad inputs."""

    def setUp(self):
        self.publisher = MockPublisher()
        self.dispatcher = CommandDispatcher(plot_id=1, publish_fn=self.publisher.publish)

    def test_invalid_json(self):
        """Invalid JSON should be logged and ignored, not crash."""
        self.dispatcher.dispatch("parking/plot/1/command", "not valid json {{{")
        self.assertEqual(len(self.publisher.published), 0)

    def test_missing_action_field(self):
        """Payload without 'action' should be ignored."""
        payload = json.dumps({"booking_id": 1, "slot_type": "2W"})
        self.dispatcher.dispatch("parking/plot/1/command", payload)
        self.assertEqual(len(self.publisher.published), 0)

    def test_unknown_action(self):
        """Unknown action should be logged and ignored."""
        payload = json.dumps({"action": "explode", "data": 42})
        self.dispatcher.dispatch("parking/plot/1/command", payload)
        self.assertEqual(len(self.publisher.published), 0)

    def test_reserve_missing_booking_id(self):
        """Reserve without booking_id should not publish."""
        payload = json.dumps({"action": "reserve", "slot_type": "2W"})
        self.dispatcher.dispatch("parking/plot/1/command", payload)
        self.assertEqual(len(self.publisher.published), 0)

    def test_reserve_missing_slot_type(self):
        """Reserve without slot_type should not publish."""
        payload = json.dumps({"action": "reserve", "booking_id": 1})
        self.dispatcher.dispatch("parking/plot/1/command", payload)
        self.assertEqual(len(self.publisher.published), 0)

    def test_unlock_missing_fields(self):
        """Unlock without required fields should not crash."""
        payload = json.dumps({"action": "unlock"})
        self.dispatcher.dispatch("parking/plot/1/command", payload)
        self.assertEqual(len(self.publisher.published), 0)

    def test_lock_missing_slot_id(self):
        """Lock without slot_id should not crash."""
        payload = json.dumps({"action": "lock"})
        self.dispatcher.dispatch("parking/plot/1/command", payload)
        self.assertEqual(len(self.publisher.published), 0)

    def test_empty_payload(self):
        """Empty string payload should be handled gracefully."""
        self.dispatcher.dispatch("parking/plot/1/command", "")
        self.assertEqual(len(self.publisher.published), 0)


class TestStatusResponseFormat(unittest.TestCase):
    """Validate that status responses match what the backend expects."""

    def setUp(self):
        self.publisher = MockPublisher()
        self.dispatcher = CommandDispatcher(plot_id=3, publish_fn=self.publisher.publish)

    def test_reserved_response_format(self):
        """
        Reserved response must match backend's status_handler.py expected format:
            { "action": "reserved", "booking_id": <int>, "slot_id": <int> }
        """
        payload = json.dumps({
            "action": "reserve",
            "booking_id": 42,
            "slot_type": "4W"
        })
        self.dispatcher.dispatch("parking/plot/3/command", payload)

        response = self.publisher.last_payload_dict
        self.assertIsNotNone(response)

        # Validate all required fields are present
        self.assertIn("action", response)
        self.assertIn("booking_id", response)
        self.assertIn("slot_id", response)

        # Validate types
        self.assertEqual(response["action"], "reserved")
        self.assertIsInstance(response["booking_id"], int)
        self.assertIsInstance(response["slot_id"], int)

    def test_status_published_to_correct_topic(self):
        """Status responses must go to parking/plot/{plot_id}/status."""
        payload = json.dumps({
            "action": "reserve",
            "booking_id": 1,
            "slot_type": "2W"
        })
        self.dispatcher.dispatch("parking/plot/3/command", payload)

        topic = self.publisher.published[0][0]
        self.assertEqual(topic, "parking/plot/3/status")


class TestActiveReservations(unittest.TestCase):
    """Test slot assignment tracking."""

    def setUp(self):
        self.publisher = MockPublisher()
        self.dispatcher = CommandDispatcher(plot_id=1, publish_fn=self.publisher.publish)

    def test_reservation_tracked(self):
        """After reserve, booking → slot mapping is tracked."""
        payload = json.dumps({
            "action": "reserve",
            "booking_id": 10,
            "slot_type": "2W"
        })
        self.dispatcher.dispatch("parking/plot/1/command", payload)

        reservations = self.dispatcher.get_active_reservations()
        self.assertIn(10, reservations)

    def test_lock_removes_tracking(self):
        """After lock, the booking → slot mapping is removed."""
        # Reserve
        payload = json.dumps({
            "action": "reserve",
            "booking_id": 20,
            "slot_type": "4W"
        })
        self.dispatcher.dispatch("parking/plot/1/command", payload)

        slot_id = json.loads(self.publisher.published[0][1])["slot_id"]

        # Lock
        lock_payload = json.dumps({"action": "lock", "slot_id": slot_id})
        self.dispatcher.dispatch("parking/plot/1/command", lock_payload)

        reservations = self.dispatcher.get_active_reservations()
        self.assertNotIn(20, reservations)


if __name__ == "__main__":
    unittest.main()
