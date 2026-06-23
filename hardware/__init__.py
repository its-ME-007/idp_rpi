"""
NammaPark RPi Hardware Module

Provides hardware abstraction for the main gate servo controller.
The LED and slot-management modules have been removed in favour of
a simpler single-gate, QR-scan-driven architecture.
"""

from hardware.gate_controller import GateController

__all__ = ["GateController"]
