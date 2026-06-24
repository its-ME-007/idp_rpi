"""
mock_backend.py — NammaPark Mock Backend + App (runs on laptop)
===============================================================
Simulates the full backend + Android app behaviour so you can
test the RPi in isolation without the real server.

What it does automatically:
  entry_scan received  → validates QR token → gate_command: open
                       → entry_verified: verified
                       → auto gate_command: close after AUTO_CLOSE_AFTER seconds

  exit_scan received   → gate_command: open (exit)
                       → auto gate_command: close after AUTO_CLOSE_AFTER seconds

  heartbeat received   → logs device online

Manual CLI menu (simulates app user actions + backend events):
  1 → gate_command: open
  2 → gate_command: close
  3 → entry_verified: verified  (with last scanned booking info)
  4 → entry_verified: rejected
  5 → alert: unauthorised_qr
  6 → alert: device_offline
  q → quit

QR Schema (from roadmap §2.4):
  {
    "booking_id": <int>,
    "token":      "<secrets.token_hex(8)>",
    "plot_id":    <int>,
    "vehicle":    "<vehicle_number>",
    "issued_at":  "<ISO8601>"
  }

Usage:
    pip install paho-mqtt
    python mock_backend.py            # console menu (default)

    pip install qrcode Pillow         # extra deps for the GUI only
    python mock_backend.py --gui      # GUI: generate a scannable QR (roadmap §2.4)
                                      #      + manual command buttons

In --gui mode the auto-responder still runs in the background; the window lets you
generate a QR per the booking schema so a real RPi camera can scan it off-screen and
drive the full entry/exit loop. Falls back to the console menu if GUI deps are absent.

Credentials via env vars or CONFIG block below:
    export MQTT_BROKER=xxx.s1.eu.hivemq.cloud
    export MQTT_USERNAME=your_user
    export MQTT_PASSWORD=your_pass
    export PLOT_ID=1
"""

import json
import os
import ssl
import sys
import threading
import time
from datetime import datetime, timezone
import secrets
import paho.mqtt.client as mqtt

from pathlib import Path
from dotenv import load_dotenv

# Load credentials from the repo-root .env (two levels up from tests/laptop)
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

# Ensure Unicode output (box-drawing chars) works on Windows cp1252 consoles
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

# ── CONFIG ──────────────────────────────────────────────────────────────────
BROKER    = os.getenv("MQTT_BROKER",   "_.s1.eu.hivemq.cloud") # have to insert mqtt broker value
PORT      = int(os.getenv("MQTT_PORT", "8883"))
USERNAME  = os.getenv("MQTT_USERNAME", "your_mqtt_username")
PASSWORD  = os.getenv("MQTT_PASSWORD", "your_mqtt_password")
PLOT_ID   = int(os.getenv("PLOT_ID",  "1"))

# Simulated backend processing delay before responding (seconds)
BACKEND_RESPONSE_DELAY = 1.5

# Auto-close gate N seconds after auto-open (0 = don't auto-close)
AUTO_CLOSE_AFTER = 5
# ────────────────────────────────────────────────────────────────────────────

def t(suffix): return f"parking/plot/{PLOT_ID}/{suffix}"

TOPIC_HEARTBEAT     = t("heartbeat")
TOPIC_ENTRY_SCAN    = t("entry_scan")
TOPIC_EXIT_SCAN     = t("exit_scan")
TOPIC_GATE_COMMAND  = t("gate_command")
TOPIC_ENTRY_VERIFY  = t("entry_verified")
TOPIC_ALERTS        = t("alerts")

client: mqtt.Client = None
connected = False
stats = {"heartbeats": 0, "entry_scans": 0, "exit_scans": 0, "commands_sent": 0}

# Track last scan so manual menu can reuse it
_last_scan: dict = {}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")

def log(tag: str, msg: str):
    print(f"[{ts()}] [{tag}] {msg}")

def publish(topic: str, payload: dict, label: str = ""):
    if not connected:
        log("ERR", "Not connected — cannot publish")
        return
    raw = json.dumps(payload)
    client.publish(topic, raw, qos=1)
    stats["commands_sent"] += 1
    short = label or topic.split("/")[-1]
    log("SEND", f"{short} → {topic}")
    print(f"         payload: {raw}")


# ── QR token validation (mock) ───────────────────────────────────────────────

def validate_qr_token(booking_token_raw: str) -> tuple[bool, dict]:
    """
    Mock backend validation of the QR token.
    Schema (roadmap §2.4):
      { booking_id, token, plot_id, vehicle, issued_at }

    Rejects if:
      - not valid JSON
      - missing required fields
      - plot_id doesn't match this gate's PLOT_ID
      - token is empty
    Returns (is_valid, parsed_dict)
    """
    required = {"booking_id", "token", "plot_id", "vehicle", "issued_at"}
    try:
        data = json.loads(booking_token_raw)
    except Exception:
        return False, {}

    if not isinstance(data, dict):
        return False, {}
    if not required.issubset(data.keys()):
        missing = required - data.keys()
        log("VALIDATE", f"Missing fields: {missing}")
        return False, data
    if int(data["plot_id"]) != PLOT_ID:
        log("VALIDATE", f"plot_id mismatch: got {data['plot_id']}, expected {PLOT_ID}")
        return False, data
    if not data["token"]:
        log("VALIDATE", "Empty token — rejected")
        return False, data

    return True, data


# ── Auto-responders ──────────────────────────────────────────────────────────

def respond_to_entry_scan(scan_payload: dict):
    """
    Simulate backend processing an entry_scan:
      scan_payload = { "booking_token": "<raw QR json>", "timestamp": "..." }
    """
    global _last_scan

    def _respond():
        log("AUTO", "Entry scan received — validating QR token...")
        time.sleep(BACKEND_RESPONSE_DELAY)

        booking_token_raw = scan_payload.get("booking_token", "{}")
        is_valid, qr = validate_qr_token(booking_token_raw)

        if is_valid:
            _last_scan = qr
            booking_id = qr.get("booking_id", 0)
            vehicle    = qr.get("vehicle", "UNKNOWN")

            log("VALIDATE", f"✓ Valid QR — booking_id={booking_id} vehicle={vehicle}")

            # Backend opens gate
            publish(TOPIC_GATE_COMMAND,
                    {"action": "open"},
                    "gate_command: OPEN")

            # Backend sends entry_verified
            publish(TOPIC_ENTRY_VERIFY, {
                "booking_id":     booking_id,
                "vehicle_id":     1,
                "vehicle_number": vehicle,
                "timestamp":      now_iso(),
                "status":         "verified",
            }, "entry_verified: verified")

            # Auto-close
            if AUTO_CLOSE_AFTER > 0:
                log("AUTO", f"Gate auto-closes in {AUTO_CLOSE_AFTER}s...")
                time.sleep(AUTO_CLOSE_AFTER)
                publish(TOPIC_GATE_COMMAND,
                        {"action": "close"},
                        "gate_command: CLOSE (auto)")
        else:
            log("VALIDATE", "✗ Invalid QR token — rejected")
            publish(TOPIC_ENTRY_VERIFY, {
                "booking_id":     qr.get("booking_id", 0),
                "vehicle_number": qr.get("vehicle", "UNKNOWN"),
                "timestamp":      now_iso(),
                "status":         "rejected",
            }, "entry_verified: rejected")
            publish(TOPIC_ALERTS, {
                "type":      "unauthorised_qr",
                "message":   "QR validation failed at entry gate",
                "timestamp": now_iso(),
            }, "alert: unauthorised_qr")

    threading.Thread(target=_respond, daemon=True).start()


def respond_to_exit_scan(scan_payload: dict):
    """
    Simulate backend processing an exit_scan (same QR reused for exit).
    Booking must be in ACTIVE state — mock just opens gate.
    """
    def _respond():
        log("AUTO", "Exit scan received — validating QR token for exit...")
        time.sleep(BACKEND_RESPONSE_DELAY)

        booking_token_raw = scan_payload.get("booking_token", "{}")
        is_valid, qr = validate_qr_token(booking_token_raw)

        if is_valid:
            booking_id = qr.get("booking_id", 0)
            vehicle    = qr.get("vehicle", "UNKNOWN")
            log("VALIDATE", f"✓ Valid exit QR — booking_id={booking_id} vehicle={vehicle}")

            publish(TOPIC_GATE_COMMAND,
                    {"action": "open"},
                    "gate_command: OPEN (exit)")

            if AUTO_CLOSE_AFTER > 0:
                log("AUTO", f"Gate auto-closes in {AUTO_CLOSE_AFTER}s...")
                time.sleep(AUTO_CLOSE_AFTER)
                publish(TOPIC_GATE_COMMAND,
                        {"action": "close"},
                        "gate_command: CLOSE (auto)")
        else:
            log("VALIDATE", "✗ Invalid exit QR — rejected")
            publish(TOPIC_ALERTS, {
                "type":      "unauthorised_qr",
                "message":   "QR validation failed at exit gate",
                "timestamp": now_iso(),
            }, "alert: unauthorised_qr")

    threading.Thread(target=_respond, daemon=True).start()


# ── MQTT callbacks ───────────────────────────────────────────────────────────

def on_connect(mqttc, userdata, flags, rc):
    global connected
    if rc == 0:
        connected = True
        for topic in (TOPIC_HEARTBEAT, TOPIC_ENTRY_SCAN, TOPIC_EXIT_SCAN):
            mqttc.subscribe(topic, qos=1)
        log("OK", f"Connected to {BROKER}:{PORT}")
        log("OK", f"Listening on: heartbeat | entry_scan | exit_scan")
        print()
    else:
        codes = {1:"Bad protocol", 2:"Bad client ID", 3:"Unavailable",
                 4:"Bad credentials", 5:"Not authorised"}
        log("ERR", f"Connect failed: {codes.get(rc, f'rc={rc}')}")

def on_disconnect(mqttc, userdata, rc):
    global connected
    connected = False
    if rc != 0:
        log("WARN", f"Unexpected disconnect rc={rc} — paho will reconnect")

def on_message(mqttc, userdata, msg):
    suffix = msg.topic.split("/")[-1]
    try:
        data = json.loads(msg.payload.decode("utf-8"))
    except Exception:
        data = {"raw": msg.payload.decode("utf-8")}

    if suffix == "heartbeat":
        stats["heartbeats"] += 1
        log("HB", f"device={data.get('device_id','?')}  status={data.get('status','?')}  ts={data.get('timestamp','?')}")

    elif suffix == "entry_scan":
        stats["entry_scans"] += 1
        log("SCAN", "▶ entry_scan received")
        print(f"         raw: {json.dumps(data)}")
        respond_to_entry_scan(data)

    elif suffix == "exit_scan":
        stats["exit_scans"] += 1
        log("SCAN", "▶ exit_scan received")
        print(f"         raw: {json.dumps(data)}")
        respond_to_exit_scan(data)

    else:
        log("RECV", f"[{msg.topic}] {json.dumps(data)}")


# ── Manual CLI ───────────────────────────────────────────────────────────────

def manual_open():
    publish(TOPIC_GATE_COMMAND, {"action": "open"}, "gate_command: OPEN")

def manual_close():
    publish(TOPIC_GATE_COMMAND, {"action": "close"}, "gate_command: CLOSE")

def manual_verified():
    b = _last_scan
    publish(TOPIC_ENTRY_VERIFY, {
        "booking_id":     b.get("booking_id", 101),
        "vehicle_id":     1,
        "vehicle_number": b.get("vehicle", "KA01AB1234"),
        "timestamp":      now_iso(),
        "status":         "verified",
    }, "entry_verified: verified")

def manual_rejected():
    b = _last_scan
    publish(TOPIC_ENTRY_VERIFY, {
        "booking_id":     b.get("booking_id", 999),
        "vehicle_number": b.get("vehicle", "MH02XX0000"),
        "timestamp":      now_iso(),
        "status":         "rejected",
    }, "entry_verified: rejected")

def manual_alert_unauth():
    publish(TOPIC_ALERTS, {
        "type":      "unauthorised_qr",
        "message":   "Unknown QR token scanned at gate",
        "timestamp": now_iso(),
    }, "alert: unauthorised_qr")

def manual_alert_offline():
    publish(TOPIC_ALERTS, {
        "type":      "device_offline",
        "message":   f"Device at plot {PLOT_ID} missed heartbeat threshold",
        "timestamp": now_iso(),
    }, "alert: device_offline")

def print_stats():
    print(f"\n  ── Stats ─────────────────────────────────")
    print(f"  Heartbeats received  : {stats['heartbeats']}")
    print(f"  Entry scans received : {stats['entry_scans']}")
    print(f"  Exit scans received  : {stats['exit_scans']}")
    print(f"  Commands sent        : {stats['commands_sent']}")
    if _last_scan:
        print(f"  Last QR booking_id   : {_last_scan.get('booking_id','?')}")
        print(f"  Last QR vehicle      : {_last_scan.get('vehicle','?')}")
    print()

MENU = """
┌────────────────────────────────────────────────────┐
│   NammaPark Mock Backend  (plot_id={plot_id:<3})            │
│   Auto-responds to entry_scan / exit_scan from RPi │
├────────────────────────────────────────────────────┤
│  Manual commands (simulate app / backend):         │
│   1 → gate_command: open                           │
│   2 → gate_command: close                          │
│   3 → entry_verified: verified  (last scan info)   │
│   4 → entry_verified: rejected  (last scan info)   │
│   5 → alert: unauthorised_qr                       │
│   6 → alert: device_offline                        │
│   s → stats                                        │
│   q → quit                                         │
└────────────────────────────────────────────────────┘
Enter command: """

ACTIONS = {
    "1": manual_open,
    "2": manual_close,
    "3": manual_verified,
    "4": manual_rejected,
    "5": manual_alert_unauth,
    "6": manual_alert_offline,
    "s": print_stats,
}

def cli_loop():
    print(MENU.format(plot_id=PLOT_ID), end="", flush=True)
    while True:
        try:
            choice = input().strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break
        if choice == "q":
            break
        elif choice in ACTIONS:
            ACTIONS[choice]()
        elif choice != "":
            print(f"  Unknown: '{choice}'")
        print("Enter command: ", end="", flush=True)


# ── QR generator GUI ─────────────────────────────────────────────────────────
# Stands in for the Android app's QR-generation role. Builds a QR per the
# backend's schema (roadmap §2.4) so a real RPi camera can scan it off-screen
# and drive the full entry/exit loop against this mock backend.

def build_qr_payload(booking_id: int, plot_id: int, vehicle: str, token: str) -> str:
    """
    Build the raw QR JSON string per roadmap §2.4.

    The ENTIRE compact JSON string is what gets encoded as plain text into the
    QR image. The RPi (camera/qr_scanner.py) wraps this into the entry_scan
    envelope { "booking_token": <this>, "timestamp": ... } when it publishes.
    Schema fields are exactly what validate_qr_token() requires.
    """
    return json.dumps({
        "booking_id": booking_id,
        "token":      token,
        "plot_id":    plot_id,
        "vehicle":    vehicle,
        "issued_at":  now_iso(),
    }, separators=(",", ":"))


def gui_loop():
    """
    Simple Tkinter GUI to generate a scannable QR + fire manual backend commands.

    Falls back to the console menu if tkinter / qrcode / Pillow aren't available,
    so console mode never depends on the QR libraries.
    """
    try:
        import tkinter as tk
        from tkinter import messagebox
    except Exception as exc:
        log("ERR", f"tkinter unavailable ({exc}) — falling back to console menu.")
        cli_loop()
        return
    try:
        import qrcode
        from PIL import ImageTk
    except Exception as exc:
        log("ERR", f"QR deps missing ({exc}) — run: pip install qrcode Pillow")
        log("ERR", "Falling back to console menu.")
        cli_loop()
        return

    global _last_scan

    root = tk.Tk()
    root.title(f"NammaPark Mock Backend — QR Generator (plot {PLOT_ID})")
    root.resizable(False, False)

    # Keep a reference so the rendered QR isn't garbage-collected
    qr_image_ref = {"img": None}

    # ── Input fields ─────────────────────────────────────────────────────────
    form = tk.Frame(root, padx=12, pady=12)
    form.grid(row=0, column=0, sticky="n")

    tk.Label(form, text="QR booking details", font=("", 11, "bold")).grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

    tk.Label(form, text="booking_id").grid(row=1, column=0, sticky="e", padx=4, pady=2)
    booking_var = tk.StringVar(value="101")
    tk.Entry(form, textvariable=booking_var, width=24).grid(row=1, column=1, pady=2)

    tk.Label(form, text="plot_id").grid(row=2, column=0, sticky="e", padx=4, pady=2)
    plot_var = tk.StringVar(value=str(PLOT_ID))
    tk.Entry(form, textvariable=plot_var, width=24).grid(row=2, column=1, pady=2)

    tk.Label(form, text="vehicle").grid(row=3, column=0, sticky="e", padx=4, pady=2)
    vehicle_var = tk.StringVar(value="KA01AB1234")
    tk.Entry(form, textvariable=vehicle_var, width=24).grid(row=3, column=1, pady=2)

    tk.Label(form, text="token").grid(row=4, column=0, sticky="e", padx=4, pady=2)
    token_var = tk.StringVar(value=secrets.token_hex(8))
    tk.Entry(form, textvariable=token_var, width=24, state="readonly").grid(
        row=4, column=1, pady=2)

    def regen_token():
        token_var.set(secrets.token_hex(8))

    tk.Button(form, text="Regenerate token", command=regen_token).grid(
        row=5, column=1, sticky="e", pady=(2, 8))

    # ── QR display ───────────────────────────────────────────────────────────
    qr_label = tk.Label(form)
    qr_label.grid(row=7, column=0, columnspan=2, pady=8)

    json_box = tk.Text(form, width=46, height=4, wrap="char")
    json_box.grid(row=8, column=0, columnspan=2)
    json_box.configure(state="disabled")

    def generate_qr():
        try:
            booking_id = int(booking_var.get().strip())
            plot_id    = int(plot_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid input", "booking_id and plot_id must be integers.")
            return
        vehicle = vehicle_var.get().strip()
        if not vehicle:
            messagebox.showerror("Invalid input", "vehicle must not be empty.")
            return

        payload = build_qr_payload(booking_id, plot_id, vehicle, token_var.get())

        # Render the compact JSON into a QR image
        qr = qrcode.QRCode(border=2, box_size=8)
        qr.add_data(payload)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        photo = ImageTk.PhotoImage(img)
        qr_image_ref["img"] = photo          # prevent GC
        qr_label.configure(image=photo)

        json_box.configure(state="normal")
        json_box.delete("1.0", "end")
        json_box.insert("1.0", payload)
        json_box.configure(state="disabled")

        # Remember it so the manual verified/rejected buttons reuse this booking
        _last_scan.clear()
        _last_scan.update({"booking_id": booking_id, "vehicle": vehicle,
                           "plot_id": plot_id, "token": token_var.get()})
        log("QR", f"Generated QR — booking_id={booking_id} plot_id={plot_id} vehicle={vehicle}")

    tk.Button(form, text="Generate QR", width=18, command=generate_qr).grid(
        row=6, column=0, columnspan=2, pady=4)

    # ── Manual backend commands (mirror the console menu) ────────────────────
    cmds = tk.LabelFrame(root, text="Manual backend commands", padx=10, pady=10)
    cmds.grid(row=0, column=1, sticky="n", padx=(0, 12), pady=12)

    buttons = [
        ("gate_command: open",        manual_open),
        ("gate_command: close",       manual_close),
        ("entry_verified: verified",  manual_verified),
        ("entry_verified: rejected",  manual_rejected),
        ("alert: unauthorised_qr",    manual_alert_unauth),
        ("alert: device_offline",     manual_alert_offline),
        ("show stats",                print_stats),
    ]
    for i, (label, fn) in enumerate(buttons):
        tk.Button(cmds, text=label, width=24, anchor="w", command=fn).grid(
            row=i, column=0, pady=2)

    status = tk.Label(root, text="Auto-responds to entry_scan / exit_scan from the RPi.",
                      fg="gray", padx=12, pady=4)
    status.grid(row=1, column=0, columnspan=2, sticky="w")

    generate_qr()  # render an initial QR on open
    root.mainloop()


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    global client

    print("═" * 54)
    print(f"  NammaPark Mock Backend + App")
    print(f"  Broker  : {BROKER}:{PORT}  |  Plot ID: {PLOT_ID}")
    print(f"  Response delay : {BACKEND_RESPONSE_DELAY}s  |  Auto-close: {AUTO_CLOSE_AFTER}s")
    print("═" * 54)
    print()

    client = mqtt.Client(
        client_id=f"NammaPark_MockBackend_{int(time.time())}",
        protocol=mqtt.MQTTv311,
    )
    client.username_pw_set(USERNAME, PASSWORD)
    client.tls_set(tls_version=ssl.PROTOCOL_TLS)
    client.tls_insecure_set(False)
    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect
    client.on_message    = on_message

    log("...", f"Connecting to {BROKER}:{PORT}")
    client.connect(BROKER, PORT, keepalive=60)
    client.loop_start()

    deadline = time.time() + 10
    while not connected and time.time() < deadline:
        time.sleep(0.2)

    if not connected:
        log("ERR", "Could not connect within 10s. Check credentials.")
        client.loop_stop()
        sys.exit(1)

    use_gui = "--gui" in sys.argv
    try:
        if use_gui:
            gui_loop()
        else:
            cli_loop()
    finally:
        print_stats()
        client.loop_stop()
        client.disconnect()
        log("BYE", "Disconnected")

if __name__ == "__main__":
    main()
