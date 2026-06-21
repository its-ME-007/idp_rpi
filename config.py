"""
NammaPark RPi Device Configuration

Loads settings from environment variables (.env file or system env).
All MQTT and device identity settings are centralized here.
"""

import os
import sys
from dotenv import load_dotenv

# Load .env file if present (no error if missing — falls back to system env)
load_dotenv()


class DeviceConfig:
    """
    RPi device configuration.

    Reads all settings from environment variables.
    Required variables will cause a clear error message if missing.
    """

    # --- MQTT Broker ---
    MQTT_BROKER: str = os.getenv("MQTT_BROKER", "")
    MQTT_PORT: int = int(os.getenv("MQTT_PORT", "8883"))
    MQTT_USERNAME: str = os.getenv("MQTT_USERNAME", "")
    MQTT_PASSWORD: str = os.getenv("MQTT_PASSWORD", "")

    # --- Device Identity ---
    DEVICE_ID: str = os.getenv("DEVICE_ID", "RPi-Unknown")
    PLOT_ID: int = int(os.getenv("PLOT_ID", "0"))

    # --- Heartbeat ---
    HEARTBEAT_INTERVAL: int = int(os.getenv("HEARTBEAT_INTERVAL", "60"))

    # --- Slot Capacity (static defaults — replaced by sensor data later) ---
    TOTAL_SLOTS_2W: int = int(os.getenv("TOTAL_SLOTS_2W", "5"))
    TOTAL_SLOTS_4W: int = int(os.getenv("TOTAL_SLOTS_4W", "3"))

    # --- Reconnect ---
    RECONNECT_MAX_ATTEMPTS: int = int(os.getenv("RECONNECT_MAX_ATTEMPTS", "0"))  # 0 = unlimited
    RECONNECT_BASE_DELAY: float = float(os.getenv("RECONNECT_BASE_DELAY", "1.0"))
    RECONNECT_MAX_DELAY: float = float(os.getenv("RECONNECT_MAX_DELAY", "60.0"))

    # --- Logging ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

    @classmethod
    def validate(cls) -> list[str]:
        """
        Validate that all required configuration is present.

        Returns:
            list[str]: List of error messages (empty if valid)
        """
        errors = []

        if not cls.MQTT_BROKER:
            errors.append("MQTT_BROKER is required (set in .env or environment)")
        if not cls.MQTT_USERNAME:
            errors.append("MQTT_USERNAME is required (set in .env or environment)")
        if not cls.MQTT_PASSWORD:
            errors.append("MQTT_PASSWORD is required (set in .env or environment)")
        if cls.PLOT_ID <= 0:
            errors.append("PLOT_ID must be a positive integer (set in .env or environment)")
        if cls.MQTT_PORT <= 0 or cls.MQTT_PORT > 65535:
            errors.append("MQTT_PORT must be between 1 and 65535")
        if cls.HEARTBEAT_INTERVAL < 10:
            errors.append("HEARTBEAT_INTERVAL must be at least 10 seconds")

        return errors

    @classmethod
    def print_summary(cls) -> None:
        """Print a human-readable configuration summary (masks secrets)."""
        print("=" * 60)
        print("  NammaPark RPi Device Configuration")
        print("=" * 60)
        print(f"  Broker:     {cls.MQTT_BROKER}:{cls.MQTT_PORT}")
        print(f"  Username:   {cls.MQTT_USERNAME}")
        print(f"  Password:   {'*' * len(cls.MQTT_PASSWORD) if cls.MQTT_PASSWORD else '(not set)'}")
        print(f"  Device ID:  {cls.DEVICE_ID}")
        print(f"  Plot ID:    {cls.PLOT_ID}")
        print(f"  Heartbeat:  every {cls.HEARTBEAT_INTERVAL}s")
        print(f"  Slots:      2W={cls.TOTAL_SLOTS_2W}, 4W={cls.TOTAL_SLOTS_4W}")
        print(f"  Log Level:  {cls.LOG_LEVEL}")
        print("=" * 60)


# Module-level singleton
config = DeviceConfig()
