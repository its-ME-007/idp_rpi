"""
Tests for GateCommandHandler — NammaPark RPi (QR Gate Architecture)

Validates:
1. gate_command "open" triggers gate.open()
2. gate_command "close" triggers gate.close()
3. Unknown gate_command actions are ignored gracefully
4. entry_verified messages are logged for both verified and rejected status
5. alert messages are logged without crashing
6. Malformed / non-JSON payloads are handled gracefully
7. Messages on unrecognised topic suffixes are silently ignored
"""

import json
import sys
import os
import unittest
from unittest.mock import MagicMock, call

# Ensure project root is on the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mqtt.handlers import GateCommandHandler


def _make_handler() -> tuple["GateCommandHandler", MagicMock]:
    """Return a (handler, mock_gate) pair for testing."""
    mock_gate = MagicMock()
    handler = GateCommandHandler(gate_controller=mock_gate)
    return handler, mock_gate


class TestGateCommandOpen(unittest.TestCase):
    """gate_command with action=open should call gate.open()."""

    def setUp(self):
        self.handler, self.gate = _make_handler()

    def test_open_action_calls_gate_open(self):
        payload = json.dumps({"action": "open"})
        self.handler.handle("parking/plot/1/gate_command", payload)
        self.gate.open.assert_called_once()
        self.gate.close.assert_not_called()

    def test_open_action_case_insensitive(self):
        """Action matching should be case-insensitive."""
        for variant in ["OPEN", "Open", "oPeN"]:
            self.gate.reset_mock()
            payload = json.dumps({"action": variant})
            self.handler.handle("parking/plot/1/gate_command", payload)
            self.gate.open.assert_called_once()


class TestGateCommandClose(unittest.TestCase):
    """gate_command with action=close should call gate.close()."""

    def setUp(self):
        self.handler, self.gate = _make_handler()

    def test_close_action_calls_gate_close(self):
        payload = json.dumps({"action": "close"})
        self.handler.handle("parking/plot/1/gate_command", payload)
        self.gate.close.assert_called_once()
        self.gate.open.assert_not_called()

    def test_close_action_case_insensitive(self):
        for variant in ["CLOSE", "Close", "cLoSe"]:
            self.gate.reset_mock()
            payload = json.dumps({"action": variant})
            self.handler.handle("parking/plot/1/gate_command", payload)
            self.gate.close.assert_called_once()


class TestGateCommandUnknownAction(unittest.TestCase):
    """Unknown gate_command actions should be ignored (no gate movement)."""

    def setUp(self):
        self.handler, self.gate = _make_handler()

    def test_unknown_action_no_gate_movement(self):
        payload = json.dumps({"action": "explode"})
        self.handler.handle("parking/plot/1/gate_command", payload)
        self.gate.open.assert_not_called()
        self.gate.close.assert_not_called()

    def test_missing_action_field_no_gate_movement(self):
        payload = json.dumps({"foo": "bar"})
        self.handler.handle("parking/plot/1/gate_command", payload)
        self.gate.open.assert_not_called()
        self.gate.close.assert_not_called()


class TestGateHardwareErrors(unittest.TestCase):
    """Exceptions from the gate controller should be caught (no crash)."""

    def setUp(self):
        self.handler, self.gate = _make_handler()

    def test_open_raises_no_propagation(self):
        self.gate.open.side_effect = RuntimeError("servo jammed")
        payload = json.dumps({"action": "open"})
        # Should NOT raise
        try:
            self.handler.handle("parking/plot/1/gate_command", payload)
        except Exception as exc:
            self.fail(f"Handler should not propagate hardware exception: {exc}")

    def test_close_raises_no_propagation(self):
        self.gate.close.side_effect = RuntimeError("GPIO error")
        payload = json.dumps({"action": "close"})
        try:
            self.handler.handle("parking/plot/1/gate_command", payload)
        except Exception as exc:
            self.fail(f"Handler should not propagate hardware exception: {exc}")


class TestEntryVerifiedMessages(unittest.TestCase):
    """entry_verified messages should be processed without touching the gate."""

    def setUp(self):
        self.handler, self.gate = _make_handler()

    def test_verified_status_no_gate_movement(self):
        payload = json.dumps({
            "booking_id": 42,
            "vehicle_id": 7,
            "vehicle_number": "KA01AB1234",
            "timestamp": "2026-06-23T10:00:00+00:00",
            "status": "verified",
        })
        self.handler.handle("parking/plot/1/entry_verified", payload)
        self.gate.open.assert_not_called()
        self.gate.close.assert_not_called()

    def test_rejected_status_no_gate_movement(self):
        payload = json.dumps({
            "booking_id": 99,
            "vehicle_number": "MH02XY5678",
            "timestamp": "2026-06-23T10:01:00+00:00",
            "status": "rejected",
        })
        self.handler.handle("parking/plot/1/entry_verified", payload)
        self.gate.open.assert_not_called()
        self.gate.close.assert_not_called()

    def test_minimal_payload_no_crash(self):
        """Missing optional fields should not crash the handler."""
        payload = json.dumps({"status": "verified"})
        try:
            self.handler.handle("parking/plot/1/entry_verified", payload)
        except Exception as exc:
            self.fail(f"Handler crashed on minimal entry_verified payload: {exc}")


class TestAlertMessages(unittest.TestCase):
    """alert messages should be logged without crashing or touching the gate."""

    def setUp(self):
        self.handler, self.gate = _make_handler()

    def test_alert_no_gate_movement(self):
        payload = json.dumps({
            "type": "unauthorised_qr",
            "message": "Unrecognised token scanned",
            "timestamp": "2026-06-23T10:05:00+00:00",
        })
        self.handler.handle("parking/plot/1/alerts", payload)
        self.gate.open.assert_not_called()
        self.gate.close.assert_not_called()

    def test_minimal_alert_no_crash(self):
        payload = json.dumps({})
        try:
            self.handler.handle("parking/plot/1/alerts", payload)
        except Exception as exc:
            self.fail(f"Handler crashed on empty alert payload: {exc}")


class TestMalformedPayloads(unittest.TestCase):
    """Malformed / non-JSON payloads should be handled gracefully (no crash)."""

    def setUp(self):
        self.handler, self.gate = _make_handler()

    def test_invalid_json_no_crash(self):
        self.handler.handle("parking/plot/1/gate_command", "not json {{{")
        self.gate.open.assert_not_called()

    def test_empty_payload_no_crash(self):
        self.handler.handle("parking/plot/1/gate_command", "")
        self.gate.open.assert_not_called()

    def test_non_dict_json_no_crash(self):
        self.handler.handle("parking/plot/1/gate_command", json.dumps([1, 2, 3]))
        self.gate.open.assert_not_called()


class TestUnknownTopicSuffix(unittest.TestCase):
    """Messages on unrecognised suffixes are silently ignored."""

    def setUp(self):
        self.handler, self.gate = _make_handler()

    def test_unknown_suffix_no_crash(self):
        payload = json.dumps({"data": "whatever"})
        try:
            self.handler.handle("parking/plot/1/unknown_topic", payload)
        except Exception as exc:
            self.fail(f"Handler crashed on unknown topic suffix: {exc}")

    def test_unknown_suffix_no_gate_movement(self):
        payload = json.dumps({"action": "open"})
        self.handler.handle("parking/plot/1/totally_unknown", payload)
        self.gate.open.assert_not_called()
        self.gate.close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
