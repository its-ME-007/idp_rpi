"""
rpi_pipeline_smoke.py — NammaPark RPi local pipeline smoke test
================================================================
Exercises the on-device pipeline (no broker, no camera, no Pi):
  1. GateController open/close (simulation)
  2. QR payload validation (parse_qr_payload)
  3. QRScanner injection + cooldown + plot_id filtering → mock publish
  4. GateCommandHandler routing (gate_command / entry_verified / alerts)

This is a runnable script, NOT a pytest test — it executes top-level code with
side effects and asserts. It lives under tests/laptop/ so pytest does not collect
it. Run it from anywhere:

    python tests/laptop/rpi_pipeline_smoke.py
"""

import json, logging, os, sys, time

# Make the project root importable regardless of the current working directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")

print("=== Test 1: Gate Controller (simulation) ===")
from hardware.gate_controller import GateController
gate = GateController(servo_pin=18, auto_close_seconds=2)
gate.setup()
gate.open()
print("is_open:", gate.is_open)
gate.close()
print("is_open after close:", gate.is_open)
gate.cleanup()
print()

print("=== Test 2: QR Payload Validation ===")
from camera.qr_scanner import parse_qr_payload

valid_qr = json.dumps({
    "booking_id": 101,
    "token": "b7f2d91ac88ef1",
    "plot_id": 1,
    "vehicle": "KA01AB1234",
    "issued_at": "2026-06-16T10:30:00Z"
})
result = parse_qr_payload(valid_qr)
print("Valid QR parsed:", result is not None)

bad_qr = json.dumps({"booking_id": 101, "token": "xyz"})
result2 = parse_qr_payload(bad_qr)
print("Missing-fields QR (expect None):", result2)

result3 = parse_qr_payload("not json at all")
print("Non-JSON QR (expect None):", result3)
print()

print("=== Test 3: QR Scanner injection + MQTT publish ===")
from camera.qr_scanner import QRScanner

published = []

def mock_publish(topic, payload, qos):
    published.append({"topic": topic, "payload": json.loads(payload)})
    print("  PUBLISHED ->", topic)
    return True

scanner = QRScanner(plot_id=1, publish_fn=mock_publish, cooldown_seconds=5)
scanner.start()

# Valid QR — should publish
scanner.inject_test_qr(valid_qr)

# Same QR again — cooldown active, should NOT publish
print("  Injecting same QR again (cooldown — expect no publish):")
scanner.inject_test_qr(valid_qr)

# Wrong plot_id — should be discarded
wrong_plot = json.dumps({
    "booking_id": 200,
    "token": "abc123",
    "plot_id": 99,
    "vehicle": "MH01XY9999",
    "issued_at": "2026-06-23T00:00:00Z"
})
print("  Injecting wrong plot_id QR (expect no publish):")
scanner.inject_test_qr(wrong_plot)

scanner.stop()
print("Total events published:", len(published), " (expected: 1)")
assert len(published) == 1, f"Expected 1, got {len(published)}"
payload0 = published[0]["payload"]
assert payload0["booking_token"] == valid_qr
print("Payload booking_token OK")
print()

print("=== Test 4: GateCommandHandler ===")
from mqtt.handlers import GateCommandHandler
gate2 = GateController(servo_pin=18, auto_close_seconds=2)
gate2.setup()
handler = GateCommandHandler(gate_controller=gate2)

handler.handle("parking/plot/1/gate_command", json.dumps({"action": "open"}))
print("After open command, gate.is_open:", gate2.is_open)

handler.handle("parking/plot/1/gate_command", json.dumps({"action": "close"}))
print("After close command, gate.is_open:", gate2.is_open)

handler.handle("parking/plot/1/entry_verified", json.dumps({
    "booking_id": 101,
    "vehicle_number": "KA01AB1234",
    "status": "verified",
    "timestamp": "2026-06-23T11:00:00Z"
}))
handler.handle("parking/plot/1/alerts", json.dumps({
    "type": "unauthorised_qr",
    "message": "Unknown token scanned",
    "timestamp": "2026-06-23T11:00:01Z"
}))

gate2.cleanup()
print()
print("=== All tests passed! ===")
