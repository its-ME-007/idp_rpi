"""
MQTT Topic Constants and Builders — NammaPark RPi (QR Gate Architecture)

Matches the Phase 2 QR Access topic structure from the Feature Development Roadmap:

  Pi publishes:
    parking/plot/{id}/entry_scan     — QR scanned at entry gate
    parking/plot/{id}/heartbeat      — device health + timestamp

  Pi subscribes:
    parking/plot/{id}/gate_command   — backend commands gate open/close
    parking/plot/{id}/alerts         — unauthorised access / device alerts (log only)

  Backend publishes (Pi subscribes):
    parking/plot/{id}/gate_command   — { "action": "open" | "close" }
    parking/plot/{id}/entry_verified — entry confirmation (logged, not acted on directly)
"""


class Topics:
    """
    MQTT topic builder for NammaPark parking system (QR Gate architecture).

    All topics follow the pattern: parking/plot/{plot_id}/{suffix}
    """

    PREFIX = "parking/plot"

    # Suffixes
    ENTRY_SCAN     = "entry_scan"
    GATE_COMMAND   = "gate_command"
    SERVICE_GATE_COMMAND = "service_gate_command"
    HEARTBEAT      = "heartbeat"
    ENTRY_VERIFIED = "entry_verified"
    ALERTS         = "alerts"

    # ---------------------------------------------------------------------------
    # Pi publishes
    # ---------------------------------------------------------------------------

    @staticmethod
    def entry_scan(plot_id: int) -> str:
        """
        Pi publishes here when a QR code is scanned at the gate.

        Payload: { "booking_token": "<raw_qr_json>", "timestamp": "<ISO8601>" }
        Backend validates booking_token and responds on gate_command.
        """
        return f"{Topics.PREFIX}/{plot_id}/{Topics.ENTRY_SCAN}"

    @staticmethod
    def heartbeat(plot_id: int) -> str:
        """
        Pi publishes here periodically for device health monitoring.

        Payload: { "device_id", "status", "timestamp" }
        """
        return f"{Topics.PREFIX}/{plot_id}/{Topics.HEARTBEAT}"

    # ---------------------------------------------------------------------------
    # Pi subscribes
    # ---------------------------------------------------------------------------

    @staticmethod
    def gate_command(plot_id: int) -> str:
        """
        Backend publishes here to control the servo gate barrier.

        Payload: { "action": "open" } or { "action": "close" }
        """
        return f"{Topics.PREFIX}/{plot_id}/{Topics.GATE_COMMAND}"

    @staticmethod
    def service_gate_command(plot_id: int) -> str:
        """
        Backend publishes here to control the service gate servo (Phase 10.5).

        Payload: { "action": "open" } (service check-in) or { "action": "close" } (check-out).
        Unlike the main gate, the service gate stays open for the whole session.
        """
        return f"{Topics.PREFIX}/{plot_id}/{Topics.SERVICE_GATE_COMMAND}"

    @staticmethod
    def entry_verified(plot_id: int) -> str:
        """
        Backend publishes here after validating QR token for entry.

        Payload: { "booking_id", "vehicle_id", "vehicle_number", "timestamp", "status" }
        Pi logs this but gate action is driven by gate_command.
        """
        return f"{Topics.PREFIX}/{plot_id}/{Topics.ENTRY_VERIFIED}"

    @staticmethod
    def alerts(plot_id: int) -> str:
        """
        Backend publishes alerts here (unauthorised QR, device offline, etc.).

        Payload: { "type", "message", "timestamp" }
        """
        return f"{Topics.PREFIX}/{plot_id}/{Topics.ALERTS}"

    # ---------------------------------------------------------------------------
    # Utility
    # ---------------------------------------------------------------------------

    @staticmethod
    def parse_plot_id(topic: str) -> "int | None":
        """
        Extract the plot_id from an MQTT topic string.

        Args:
            topic: Full topic string, e.g. "parking/plot/1/gate_command"

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
