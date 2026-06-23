"""
Tests for MQTT Topic Builders — NammaPark RPi (QR Gate Architecture)

Validates that all topic strings match the backend's expected format:
    Pi publishes:
        - parking/plot/{plot_id}/entry_scan   (QR scan event)
        - parking/plot/{plot_id}/heartbeat    (device health)
    Pi subscribes:
        - parking/plot/{plot_id}/gate_command  (open / close)
        - parking/plot/{plot_id}/entry_verified (verification result)
        - parking/plot/{plot_id}/alerts         (security alerts)
"""

import sys
import os
import unittest

# Ensure project root is on the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mqtt.topics import Topics


class TestTopicBuilders(unittest.TestCase):
    """Test that topic builder functions produce correct strings."""

    # --- Pi publishes ---

    def test_entry_scan_topic(self):
        """entry_scan topic: Pi publishes QR scan events here."""
        self.assertEqual(Topics.entry_scan(1),  "parking/plot/1/entry_scan")
        self.assertEqual(Topics.entry_scan(42), "parking/plot/42/entry_scan")

    def test_heartbeat_topic(self):
        """heartbeat topic: Pi publishes periodic health payloads here."""
        self.assertEqual(Topics.heartbeat(1), "parking/plot/1/heartbeat")
        self.assertEqual(Topics.heartbeat(5), "parking/plot/5/heartbeat")

    # --- Pi subscribes ---

    def test_gate_command_topic(self):
        """gate_command topic: backend sends open/close commands here."""
        self.assertEqual(Topics.gate_command(1),  "parking/plot/1/gate_command")
        self.assertEqual(Topics.gate_command(99), "parking/plot/99/gate_command")

    def test_entry_verified_topic(self):
        """entry_verified topic: backend publishes QR verification result here."""
        self.assertEqual(Topics.entry_verified(1),  "parking/plot/1/entry_verified")
        self.assertEqual(Topics.entry_verified(10), "parking/plot/10/entry_verified")

    def test_alerts_topic(self):
        """alerts topic: backend publishes security/device alerts here."""
        self.assertEqual(Topics.alerts(1),   "parking/plot/1/alerts")
        self.assertEqual(Topics.alerts(100), "parking/plot/100/alerts")

    def test_topics_use_consistent_prefix(self):
        """All topics share the parking/plot prefix."""
        for plot_id in [1, 2, 100]:
            all_topics = [
                Topics.entry_scan(plot_id),
                Topics.heartbeat(plot_id),
                Topics.gate_command(plot_id),
                Topics.entry_verified(plot_id),
                Topics.alerts(plot_id),
            ]
            for topic in all_topics:
                self.assertTrue(
                    topic.startswith("parking/plot/"),
                    f"Topic '{topic}' should start with 'parking/plot/'",
                )

    def test_topic_ends_with_correct_suffix(self):
        """Each builder produces the correct suffix."""
        suffixes = {
            Topics.entry_scan(1):     "entry_scan",
            Topics.heartbeat(1):      "heartbeat",
            Topics.gate_command(1):   "gate_command",
            Topics.entry_verified(1): "entry_verified",
            Topics.alerts(1):         "alerts",
        }
        for topic, expected_suffix in suffixes.items():
            self.assertTrue(
                topic.endswith(expected_suffix),
                f"Expected topic '{topic}' to end with '{expected_suffix}'",
            )


class TestTopicParser(unittest.TestCase):
    """Test that plot_id can be extracted from topic strings."""

    def test_parse_entry_scan_topic(self):
        self.assertEqual(Topics.parse_plot_id("parking/plot/1/entry_scan"), 1)

    def test_parse_gate_command_topic(self):
        self.assertEqual(Topics.parse_plot_id("parking/plot/42/gate_command"), 42)

    def test_parse_heartbeat_topic(self):
        self.assertEqual(Topics.parse_plot_id("parking/plot/99/heartbeat"), 99)

    def test_parse_entry_verified_topic(self):
        self.assertEqual(Topics.parse_plot_id("parking/plot/7/entry_verified"), 7)

    def test_parse_alerts_topic(self):
        self.assertEqual(Topics.parse_plot_id("parking/plot/3/alerts"), 3)

    def test_parse_invalid_topic(self):
        """Invalid topics should return None."""
        self.assertIsNone(Topics.parse_plot_id("invalid/topic"))
        self.assertIsNone(Topics.parse_plot_id("parking/plot"))
        self.assertIsNone(Topics.parse_plot_id(""))

    def test_parse_non_numeric_plot_id(self):
        """Non-numeric plot IDs should return None."""
        self.assertIsNone(Topics.parse_plot_id("parking/plot/abc/gate_command"))


if __name__ == "__main__":
    unittest.main()
