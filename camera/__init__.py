"""
NammaPark RPi Camera Module

Provides QR code scanning via the Pi Camera (OpenCV V4L2 backend).
"""

from camera.qr_scanner import QRScanner, parse_qr_payload

__all__ = ["QRScanner", "parse_qr_payload"]
