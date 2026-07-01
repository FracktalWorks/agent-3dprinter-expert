#!/usr/bin/env python3
"""
OctoPrint WebSocket Client — Real-time WebSocket connection to OctoPrint's
SockJS interface for live printer state monitoring, temperature streaming,
and event capture. Uses the same WebSocket protocol as Fracktal Works'
ControlCenter application.

Connects to OctoPrint at ws://<ip>/sockjs/<server_id>/<session>/websocket
for real-time updates on:
  - Temperature changes (per-heater actual + target)
  - Printer state changes (Operational, Printing, Paused, etc.)
  - Job progress (% complete, time remaining, filament used)
  - G-code responses and console output (terminal messages)
  - Event bus messages (PrintStarted, PrintDone, Error, etc.)
  - Plugin messages (Klipper state, firmware updater, softwareupdate)
  - Filament sensor events (runout, jam, insert)
  - Probe accuracy results

Usage:
    python octoprint_websocket_client.py --ip 192.168.1.100 --api-key KEY
    python octoprint_websocket_client.py --ip 192.168.1.100 --monitor temps
    python octoprint_websocket_client.py --ip 192.168.1.100 --event-log --duration 60
    python octoprint_websocket_client.py --ip 192.168.1.100 --trend tool0 --detect-anomalies
"""

import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime
from typing import Callable, Optional

DEFAULT_IP = os.environ.get("OCTOPRINT_IP", "localhost")
DEFAULT_PORT = os.environ.get("OCTOPRINT_PORT", "5000")
DEFAULT_API_KEY = os.environ.get("OCTOPRINT_API_KEY", "")

try:
    import websocket
except ImportError:
    print("ERROR: 'websocket-client' required. pip install websocket-client",
          file=sys.stderr)
    sys.exit(1)


# ── ControlCenter-compatible error classification ─────────────────────────
# Mirroring FracktalWorks/ControlCenter config.py CRITICAL_PRINTER_ERRORS
CRITICAL_PRINTER_ERRORS = [
    "Can not update MCU",
    "Probe triggered prior to movement",
    "PROBING_FAILED",
    "Error during homing move",
    "still triggered after retract",
    "'mcu' must be specified",
    "Unable to connect",
    "Shutdown due to M112",
    "Printer is not ready",
    "not heating at expected rate",
    "Timer too close",
    "ADC out of range",
    "Lost communication with MCU",
    "Missed scheduling of next",
    "Rescheduled timer in the past",
    "Stepper too far in past",
    "TMC reports error",
]

# Errors that are safe to ignore (non-critical)
IGNORED_PRINTER_ERRORS = [
    "Move out of range:",
]


class OctoPrintWebSocketClient:
    """
    Real-time WebSocket client for OctoPrint's SockJS interface.
    Captures temperature updates, printer state changes, job progress,
    console messages, plugin events, and filament sensor states.
    
    Protocol: SockJS WebSocket at ws://<ip>/sockjs/<server>/<session>/websocket
    Same architecture as ControlCenter's OctoPrintWebSocket(QThread).
    """

    def __init__(self, ip: str = DEFAULT_IP, port: str = DEFAULT_PORT,
                 api_key: str = DEFAULT_API_KEY):
        self.ip = ip
        self.port = port
        self.api_key = api_key
        # ControlCenter-compatible WebSocket URL pattern
        import random
        import uuid
        server_id = f"{random.randrange(0, 999):03d}"
        session = str(uuid.uuid4())
        self.ws_url = (
            f"ws://{ip}:{port}/sockjs/{server_id}/{session}/websocket"
        )
        self._ws: Optional[websocket.WebSocketApp] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

        # Event callbacks
        self.on_temperature: Optional[Callable] = None
        self.on_printer_state: Optional[Callable] = None
        self.on_job_progress: Optional[Callable] = None
        self.on_console_output: Optional[Callable] = None
        self.on_event: Optional[Callable] = None
        self.on_klipper_state: Optional[Callable] = None
        self.on_printer_error: Optional[Callable] = None
        self.on_connected: Optional[Callable] = None
        self.on_error: Optional[Callable] = None

        # Data buffers
        self.temperature_history: list[dict] = []
        self.event_log: list[dict] = []
        self.console_output: list[str] = []
        self.error_events: list[dict] = []
        self.current_state: dict = {}
        self.current_job: dict = {}
        self.klipper_state: str = "unknown"
        self._max_history = 1000

    # ── WebSocket lifecycle (mirrors ControlCenter patterns) ────────────

    def _on_open(self, ws):
        print(f"🔌 Connected to OctoPrint at {self.ip}:{self.port}")
        auth_msg = json.dumps({"auth": f"{self.api_key}"})
        ws.send(auth_msg)
        if self.on_connected:
            self.on_connected()

    def _on_message(self, ws, message: str):
        try:
            # SockJS frame format: message_type + payload
            msg_type = message[0] if message else ""
            if msg_type == "h":  # heartbeat
                return
            if msg_type in ("o", "c"):  # open/close
                return
            # Type 'a' = array (JSON payload)
            body = message[1:]
            if not body:
                return
            data = json.loads(body)
            if isinstance(data, list) and len(data) > 0:
                self._process_message(data[0])
            elif isinstance(data, dict):
                self._process_message(data)
        except (json.JSONDecodeError, IndexError):
            pass

    def _process_message(self, data: dict):
        """Route messages — mirrors ControlCenter OctoPrintWebSocket.process()."""
        timestamp = datetime.now().isoformat()

        # ── Event messages ──────────────────────────────────────────
        if "event" in data:
            event_data = data["event"]
            event_type = event_data.get("type", "unknown")
            event_entry = {"timestamp": timestamp, "event": event_type,
                           "payload": event_data}
            self.event_log.append(event_entry)
            if self.on_event:
                self.on_event(event_type, event_data)

        # ── Plugin messages (Klipper state, errors, firmware) ──────
        if "plugin" in data:
            plugin = data["plugin"]
            plugin_name = plugin.get("plugin", "")
            plugin_data = plugin.get("data", {})

            if plugin_name == "klipper" and isinstance(plugin_data, dict):
                # Klipper error messages
                if plugin_data.get("subtype") == "error":
                    error_msg = str(plugin_data.get(
                        "payload", plugin_data.get("title", ""))).strip()
                    if error_msg:
                        self.error_events.append({
                            "timestamp": timestamp, "error": error_msg,
                            "critical": any(e in error_msg
                                for e in CRITICAL_PRINTER_ERRORS),
                        })
                        if self.on_printer_error:
                            self.on_printer_error(error_msg)

                # Klipper state messages (parsed from terminal output)
                import re
                for key in ("title", "payload"):
                    text = str(plugin_data.get(key, ""))
                    m = re.search(r"klipper\s*state:\s*([^\n\r]+)",
                                  text, re.IGNORECASE)
                    if m:
                        state = m.group(1).strip().lower()
                        self.klipper_state = state
                        if self.on_klipper_state:
                            self.on_klipper_state(state)
                        break

        # ── Current state data ─────────────────────────────────────
        if "current" in data:
            current = data["current"]

            # Temperature data
            temps_list = current.get("temps", [])
            if temps_list and len(temps_list) > 0:
                temp_entry = {"timestamp": timestamp, "heaters": {}}
                for t in temps_list:
                    if isinstance(t, dict):
                        for tool, vals in t.items():
                            temp_entry["heaters"][tool] = {
                                "actual": vals.get("actual", 0),
                                "target": vals.get("target", 0),
                            }
                self.temperature_history.append(temp_entry)
                if self.on_temperature:
                    self.on_temperature(temp_entry)

            # Printer status
            state = current.get("state", {})
            if state.get("text"):
                self.current_state = state
                if self.on_printer_state:
                    self.on_printer_state(state["text"])

            # Job progress
            job = current.get("job", {})
            progress = current.get("progress", {})
            if job and job.get("file", {}).get("name"):
                self.current_job = {
                    "file": job["file"]["name"],
                    "progress": progress.get("completion", 0),
                    "print_time": progress.get("printTime", 0),
                    "time_left": progress.get("printTimeLeft", 0),
                }
                if self.on_job_progress:
                    self.on_job_progress(self.current_job)

            # Console output (terminal messages)
            logs = current.get("logs") or current.get("messages") or []
            for log_entry in logs:
                self.console_output.append(str(log_entry))
                if self.on_console_output:
                    self.on_console_output(str(log_entry))

    def _on_error(self, ws, error):
        msg = f"WebSocket error: {error}"
        print(f"❌ {msg}", file=sys.stderr)
        if self.on_error:
            self.on_error(msg)

    def _on_close(self, ws, code, msg):
        print(f"🔌 Disconnected (code={code})")
        self._running = False

    def connect(self, blocking: bool = False):
        self._running = True
        self._ws = websocket.WebSocketApp(
            self.ws_url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        if blocking:
            self._ws.run_forever()
        else:
            self._thread = threading.Thread(
                target=self._ws.run_forever, daemon=True)
            self._thread.start()
            time.sleep(0.5)

    def disconnect(self):
        self._running = False
        if self._ws:
            self._ws.close()
        if self._thread:
            self._thread.join(timeout=2)

    # ── Diagnostic Helpers ─────────────────────────────────────────────

    def get_temperature_trend(self, heater: str = "tool0",
                              minutes: int = 5) -> dict:
        now = datetime.now()
        relevant = []
        for entry in self.temperature_history:
            try:
                ts = datetime.fromisoformat(entry["timestamp"])
                if (now - ts).total_seconds() <= minutes * 60:
                    data = entry["heaters"].get(heater, {})
                    if data:
                        relevant.append({
                            "timestamp": entry["timestamp"],
                            "actual": data.get("actual", 0),
                            "target": data.get("target", 0),
                        })
            except (ValueError, KeyError):
                continue
        if not relevant:
            return {"error": f"No data for {heater} in last {minutes}m"}
        actuals = [r["actual"] for r in relevant]
        targets = [r["target"] for r in relevant]
        return {
            "heater": heater, "data_points": len(relevant),
            "current": actuals[-1] if actuals else 0,
            "target": targets[-1] if targets else 0,
            "min": min(actuals), "max": max(actuals),
            "mean": sum(actuals) / len(actuals),
            "std_dev": (sum((a - sum(actuals) / len(actuals)) ** 2
                            for a in actuals) / len(actuals)) ** 0.5,
            "is_stable": abs(actuals[-1] - (targets[-1] or 0)) < 3,
            "has_oscillation": abs(max(actuals) - min(actuals)) > 10,
        }

    def detect_anomalies(self) -> list[dict]:
        anomalies = []
        if not self.temperature_history:
            return [{"type": "no_data", "detail": "No temperature data"}]
        for i in range(1, len(self.temperature_history)):
            prev = self.temperature_history[i - 1]
            curr = self.temperature_history[i]
            for heater in curr.get("heaters", {}):
                pt = prev.get("heaters", {}).get(heater, {}).get("actual", 0)
                ct = curr.get("heaters", {}).get(heater, {}).get("actual", 0)
                if pt > 100 and ct < 10:
                    anomalies.append({
                        "type": "rapid_temp_drop", "heater": heater,
                        "detail": f"{heater}: {pt:.0f}→{ct:.0f}°C",
                        "likely_cause": "Thermistor disconnect or broken wire",
                    })
        for heater in set().union(*(e.get("heaters", {}).keys()
                                     for e in self.temperature_history[-30:])):
            temps = [e.get("heaters", {}).get(heater, {}).get("actual", 0)
                     for e in self.temperature_history[-30:] if e.get(
                         "heaters", {}).get(heater, {}).get("actual")]
            if len(temps) > 10:
                variance = max(temps) - min(temps)
                if variance > 15:
                    anomalies.append({
                        "type": "temperature_oscillation", "heater": heater,
                        "detail": f"{heater} oscillates {variance:.0f}°C",
                        "likely_cause": "Poor PID tuning",
                    })
        return anomalies

    def get_critical_errors(self) -> list[dict]:
        """Return errors matching ControlCenter CRITICAL_PRINTER_ERRORS."""
        return [e for e in self.error_events if e.get("critical")]


# ── CLI ─────────────────────────────────────────────────────────────────

def print_temps(data: dict):
    heaters = data.get("heaters", {})
    parts = [f"{n}:{v['actual']:.1f}/{v['target']:.1f}°C"
             if v.get('target') else f"{n}:{v['actual']:.1f}°C"
             for n, v in heaters.items()]
    if parts:
        print(f"🌡️  {' | '.join(parts)}")


def print_event(name: str, payload: dict):
    print(f"📢 Event: {name}")


def main():
    parser = argparse.ArgumentParser(
        description="OctoPrint WebSocket — Real-time printer monitoring "
                    "(ControlCenter-compatible)")
    parser.add_argument("--ip", default=DEFAULT_IP)
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--api-key", default=DEFAULT_API_KEY)
    parser.add_argument("--monitor", choices=["temps", "events", "all"],
                        default="all")
    parser.add_argument("--event-log", action="store_true")
    parser.add_argument("--duration", type=int, default=0,
                        help="Seconds to monitor (0=indefinite)")
    parser.add_argument("--trend",
                        help="Analyze temperature trend for a heater")
    parser.add_argument("--detect-anomalies", action="store_true")
    args = parser.parse_args()

    print(f"🔌 Connecting to OctoPrint at {args.ip}:{args.port}...")
    client = OctoPrintWebSocketClient(
        ip=args.ip, port=args.port, api_key=args.api_key)

    if args.monitor in ("temps", "all"):
        client.on_temperature = print_temps
    if args.monitor in ("events", "all") and args.event_log:
        client.on_event = print_event

    client.connect(blocking=False)

    try:
        if args.duration > 0:
            print(f"📡 Monitoring for {args.duration}s...")
            time.sleep(args.duration)
        else:
            print("📡 Monitoring indefinitely (Ctrl+C to stop)...")
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        print("\n⏹️  Stopping...")
    finally:
        client.disconnect()

    if args.trend:
        print(f"\n📊 Trend for {args.trend}:")
        print(json.dumps(client.get_temperature_trend(args.trend),
                         indent=2, default=str))

    if args.detect_anomalies:
        print("\n🔍 Anomaly scan:")
        for a in client.detect_anomalies():
            print(f"  ⚠️  [{a['type']}] {a['detail']}")
            if a.get("likely_cause"):
                print(f"      → {a['likely_cause']}")


if __name__ == "__main__":
    main()
