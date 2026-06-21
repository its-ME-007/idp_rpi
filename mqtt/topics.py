"""
MQTT Topic Constants and Builders

Centralized topic management for NammaPark RPi device.
Matches the topic structure used by the IDP backend:
  - parking/plot/{plot_id}/command   (backend → RPi)
  - parking/plot/{plot_id}/status    (RPi → backend)
  - parking/plot/{plot_id}/heartbeat (RPi → backend)

All topic strings are built through this module to prevent
typos and ensure consistency with the backend.
"""


class Topics:
    """
    MQTT topic builder for NammaPark parking system.

    All topics follow the pattern: parking/plot/{plot_id}/{suffix}

    Subscriptions (RPi listens):
        - parking/plot/{plot_id}/command  — receive actions from backend

    Publications (RPi sends):
        - parking/plot/{plot_id}/status    — report action results
        - parking/plot/{plot_id}/heartbeat — periodic health check
    """

    # Topic base prefix
    PREFIX = "parking/plot"

    # Topic suffixes
    COMMAND = "command"
    STATUS = "status"
    HEARTBEAT = "heartbeat"

    @staticmethod
    def command(plot_id: int) -> str:
        """
        Build the command topic for a plot (backend → RPi).

        The RPi subscribes to this topic to receive actions:
        - reserve: Reserve a slot for a booking
        - unlock: Unlock a slot when user arrives
        - lock: Lock a slot (cancellation or checkout)

        Args:
            plot_id: The parking plot ID this device manages

        Returns:
            Topic string, e.g. "parking/plot/1/command"
        """
        return f"{Topics.PREFIX}/{plot_id}/{Topics.COMMAND}"

    @staticmethod
    def status(plot_id: int) -> str:
        """
        Build the status topic for a plot (RPi → backend).

        The RPi publishes to this topic to report action results:
        - reserved: Slot successfully reserved (includes slot_id)
        - freed: Vehicle departed, slot freed

        Args:
            plot_id: The parking plot ID this device manages

        Returns:
            Topic string, e.g. "parking/plot/1/status"
        """
        return f"{Topics.PREFIX}/{plot_id}/{Topics.STATUS}"

    @staticmethod
    def heartbeat(plot_id: int) -> str:
        """
        Build the heartbeat topic for a plot (RPi → backend).

        The RPi publishes to this topic periodically for health monitoring.
        Payload includes device status and available slot counts.

        Args:
            plot_id: The parking plot ID this device manages

        Returns:
            Topic string, e.g. "parking/plot/1/heartbeat"
        """
        return f"{Topics.PREFIX}/{plot_id}/{Topics.HEARTBEAT}"

    @staticmethod
    def parse_plot_id(topic: str) -> int | None:
        """
        Extract the plot_id from an MQTT topic string.

        Args:
            topic: Full topic string, e.g. "parking/plot/1/command"

        Returns:
            The plot_id as int, or None if the topic format is invalid
        """
        try:
            parts = topic.split("/")
            if len(parts) >= 3 and parts[0] == "parking" and parts[1] == "plot":
                return int(parts[2])
        except (ValueError, IndexError):
            pass
        return None
