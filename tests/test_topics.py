"""
Tests for MQTT Topic Builders

Validates that all topic strings match the backend's expected format:
    - parking/plot/{plot_id}/command   (subscribe)
    - parking/plot/{plot_id}/status    (publish)
    - parking/plot/{plot_id}/heartbeat (publish)
"""

import sys
import os
import unittest

# Ensure project root is on the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mqtt.topics import Topics


class TestTopicBuilders(unittest.TestCase):
    """Test that topic builder functions produce correct strings."""

    def test_command_topic(self):
        """Command topic matches backend's publish format."""
        self.assertEqual(Topics.command(1), "parking/plot/1/command")
        self.assertEqual(Topics.command(42), "parking/plot/42/command")

    def test_status_topic(self):
        """Status topic matches backend's subscribe format."""
        self.assertEqual(Topics.status(1), "parking/plot/1/status")
        self.assertEqual(Topics.status(99), "parking/plot/99/status")

    def test_heartbeat_topic(self):
        """Heartbeat topic matches backend's subscribe format."""
        self.assertEqual(Topics.heartbeat(1), "parking/plot/1/heartbeat")
        self.assertEqual(Topics.heartbeat(5), "parking/plot/5/heartbeat")

    def test_topics_use_consistent_prefix(self):
        """All topics share the parking/plot prefix."""
        for plot_id in [1, 2, 100]:
            for topic in [Topics.command(plot_id), Topics.status(plot_id), Topics.heartbeat(plot_id)]:
                self.assertTrue(
                    topic.startswith("parking/plot/"),
                    f"Topic '{topic}' should start with 'parking/plot/'"
                )


class TestTopicParser(unittest.TestCase):
    """Test that plot_id can be extracted from topic strings."""

    def test_parse_command_topic(self):
        self.assertEqual(Topics.parse_plot_id("parking/plot/1/command"), 1)

    def test_parse_status_topic(self):
        self.assertEqual(Topics.parse_plot_id("parking/plot/42/status"), 42)

    def test_parse_heartbeat_topic(self):
        self.assertEqual(Topics.parse_plot_id("parking/plot/99/heartbeat"), 99)

    def test_parse_invalid_topic(self):
        """Invalid topics should return None."""
        self.assertIsNone(Topics.parse_plot_id("invalid/topic"))
        self.assertIsNone(Topics.parse_plot_id("parking/plot"))
        self.assertIsNone(Topics.parse_plot_id(""))

    def test_parse_non_numeric_plot_id(self):
        """Non-numeric plot IDs should return None."""
        self.assertIsNone(Topics.parse_plot_id("parking/plot/abc/command"))


if __name__ == "__main__":
    unittest.main()
