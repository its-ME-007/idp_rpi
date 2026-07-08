"""
NammaPark RPi Device Configuration

Loads settings from environment variables (.env file or system env).
All MQTT, device identity, and hardware GPIO settings are centralised here.
"""

import os
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
    MQTT_BROKER: str   = os.getenv("MQTT_BROKER", "")
    MQTT_PORT: int     = int(os.getenv("MQTT_PORT", "8883"))
    MQTT_USERNAME: str = os.getenv("MQTT_USERNAME", "")
    MQTT_PASSWORD: str = os.getenv("MQTT_PASSWORD", "")

    # --- Device Identity ---
    DEVICE_ID: str = os.getenv("DEVICE_ID", "RPi-Unknown")
    PLOT_ID: int   = int(os.getenv("PLOT_ID", "0"))

    # --- Heartbeat ---
    HEARTBEAT_INTERVAL: int = int(os.getenv("HEARTBEAT_INTERVAL", "60"))

    # --- Reconnect ---
    RECONNECT_MAX_ATTEMPTS: int  = int(os.getenv("RECONNECT_MAX_ATTEMPTS", "0"))   # 0 = unlimited
    RECONNECT_BASE_DELAY: float  = float(os.getenv("RECONNECT_BASE_DELAY", "1.0"))
    RECONNECT_MAX_DELAY: float   = float(os.getenv("RECONNECT_MAX_DELAY", "60.0"))

    # --- Logging ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

    # =========================================================================
    # Hardware / GPIO Configuration (BCM pin numbering)
    # =========================================================================
    #
    # A single servo motor controls the main gate barrier.
    #
    #   SERVO_PIN — BCM GPIO pin connected to servo signal wire
    #
    # Servo duty-cycle positions (50 Hz PWM, SG90/MG90S compatible):
    #   SERVO_OPEN_DUTY  — duty % when gate is open  (default 7.5% ≈ 90°)
    #   SERVO_CLOSE_DUTY — duty % when gate is closed (default 2.5% ≈ 0°)
    #   SERVO_OPEN_DURATION — seconds to keep gate open before auto-closing

    BUZZER_PIN: int          = int(os.getenv("BUZZER_PIN", "24"))
    BUZZER_DURATION: float   = float(os.getenv("BUZZER_DURATION", "3.0"))

    SERVO_PIN: int           = int(os.getenv("SERVO_PIN", "18"))
    SERVO_PWM_FREQ: int      = int(os.getenv("SERVO_PWM_FREQ", "50"))
    SERVO_OPEN_DUTY: float   = float(os.getenv("SERVO_OPEN_DUTY", "7.5"))
    SERVO_CLOSE_DUTY: float  = float(os.getenv("SERVO_CLOSE_DUTY", "2.5"))
    SERVO_OPEN_DURATION: int = int(os.getenv("SERVO_OPEN_DURATION", "5"))

    # --- Service gate (Phase 10.5): a 2nd servo for EV/storage service access ---
    # Stays OPEN for the whole service session: opens on service check-in,
    # closes on service check-out. auto_close is disabled (0) for this gate.
    SERVO_SERVICE_PIN: int   = int(os.getenv("SERVO_SERVICE_PIN", "13"))

    # =========================================================================
    # Camera / QR Configuration
    # =========================================================================
    #
    #   CAMERA_INDEX      — OpenCV camera index (0 = default/Pi Camera via V4L2)
    #   QR_SCAN_INTERVAL  — Seconds between scan attempts (reduce CPU load)
    #   QR_COOLDOWN       — Seconds to ignore re-scans of the same QR (dedup)
    #   CAMERA_WIDTH/HEIGHT — Capture resolution

    CAMERA_INDEX: int      = int(os.getenv("CAMERA_INDEX", "0"))
    QR_SCAN_INTERVAL: float = float(os.getenv("QR_SCAN_INTERVAL", "0.5"))
    QR_COOLDOWN: int       = int(os.getenv("QR_COOLDOWN", "10"))
    CAMERA_WIDTH: int      = int(os.getenv("CAMERA_WIDTH", "640"))
    CAMERA_HEIGHT: int     = int(os.getenv("CAMERA_HEIGHT", "480"))

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
        print(f"  Broker:           {cls.MQTT_BROKER}:{cls.MQTT_PORT}")
        print(f"  Username:         {cls.MQTT_USERNAME}")
        print(f"  Password:         {'*' * len(cls.MQTT_PASSWORD) if cls.MQTT_PASSWORD else '(not set)'}")
        print(f"  Device ID:        {cls.DEVICE_ID}")
        print(f"  Plot ID:          {cls.PLOT_ID}")
        print(f"  Heartbeat:        every {cls.HEARTBEAT_INTERVAL}s")
        print(f"  Servo pin:        GPIO{cls.SERVO_PIN}  (open={cls.SERVO_OPEN_DUTY}%, close={cls.SERVO_CLOSE_DUTY}%)")
        print(f"  Gate open for:    {cls.SERVO_OPEN_DURATION}s then auto-closes")
        print(f"  Service servo:    GPIO{cls.SERVO_SERVICE_PIN}  (stays open for the service session)")
        print(f"  Camera index:     {cls.CAMERA_INDEX}  ({cls.CAMERA_WIDTH}x{cls.CAMERA_HEIGHT})")
        print(f"  QR scan interval: {cls.QR_SCAN_INTERVAL}s  |  cooldown: {cls.QR_COOLDOWN}s")
        print(f"  Log Level:        {cls.LOG_LEVEL}")
        print("=" * 60)


# Module-level singleton
config = DeviceConfig()
