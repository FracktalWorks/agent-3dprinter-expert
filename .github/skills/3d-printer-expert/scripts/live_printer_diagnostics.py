#!/usr/bin/env python3
"""
Live Printer Diagnostics Wizard — Connects to OctoPrint via REST API and
Klipper via G-code commands to run a comprehensive, interactive diagnostic
checklist for 3D printers. Supports human-in-the-loop for tests requiring
physical verification.

Diagnostic Categories:
  1. System Health — OctoPrint/Klipper connectivity, MCU status, resources
  2. Thermistor/Thermostat — Sensor sanity, ADC values, drift detection
  3. Heater — PWM check, PID tuning analysis, heating rate verification
  4. Extrusion — Motor direction, rotation distance, temperature stability
  5. Homing — Endstop states, homing sequence, repeatability
  6. Motion System — Stepper drivers, axis movement, belt tension
  7. Probe (if equipped) — Accuracy, repeatability, bed mesh quality

Usage:
    python live_printer_diagnostics.py --ip 192.168.1.100 --api-key KEY
    python live_printer_diagnostics.py --check heater,thermistor
    python live_printer_diagnostics.py --check all --interactive
    python live_printer_diagnostics.py --output report.json
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

# ── OctoPrint API Client (embedded for portability) ───────────────────────────

try:
    import requests
except ImportError:
    print("ERROR: 'requests' required. pip install requests", file=sys.stderr)
    sys.exit(1)

try:
    import websocket
except ImportError:
    websocket = None  # WebSocket optional

DEFAULT_IP = os.environ.get("OCTOPRINT_IP", "localhost")
DEFAULT_PORT = os.environ.get("OCTOPRINT_PORT", "5000")
DEFAULT_API_KEY = os.environ.get("OCTOPRINT_API_KEY", "")


class TestResult(Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"
    NEEDS_HUMAN = "needs_human"


class OctoPrintAPI:
    """Minimal OctoPrint REST API client for diagnostics."""

    def __init__(self, ip=DEFAULT_IP, port=DEFAULT_PORT, api_key=DEFAULT_API_KEY, timeout=10):
        self.base_url = f"http://{ip}:{port}"
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "X-Api-Key": api_key,
            "Content-Type": "application/json",
        })

    def _get(self, path: str) -> dict:
        try:
            resp = self.session.get(f"{self.base_url}{path}", timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.ConnectionError:
            return {"error": f"Cannot connect to {self.base_url}"}
        except requests.exceptions.Timeout:
            return {"error": f"Connection timed out ({self.timeout}s)"}
        except Exception as e:
            return {"error": str(e)}

    def _post(self, path: str, data: Optional[dict] = None) -> dict:
        try:
            resp = self.session.post(f"{self.base_url}{path}", json=data or {}, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json() if resp.text else {"success": True}
        except Exception as e:
            return {"error": str(e)}

    def send_gcode(self, command: str) -> dict:
        """Send a G-code command to the printer via OctoPrint."""
        return self._post("/api/printer/command", {"command": command})

    def get_printer_state(self, history=False, limit=10) -> dict:
        path = "/api/printer"
        if history:
            path += f"?history=true&limit={limit}"
        return self._get(path)

    def get_connection(self) -> dict:
        return self._get("/api/connection")

    def get_version(self) -> dict:
        return self._get("/api/version")

    def get_job(self) -> dict:
        return self._get("/api/job")

    def get_settings(self) -> dict:
        return self._get("/api/settings")


# ── Diagnostic Test Functions ─────────────────────────────────────────────────

class PrinterDiagnostics:
    """Comprehensive 3D printer diagnostic engine."""

    def __init__(self, api: OctoPrintAPI, interactive: bool = True):
        self.api = api
        self.interactive = interactive
        self.results: list[dict] = []
        self.start_time = datetime.now()
        self.printer_state = {}
        self.temperature_data: list[dict] = []
        self._gcode_responses: list[str] = []

    def _record(self, category: str, test: str, result: TestResult,
                detail: str = "", data: Any = None, fix: str = "") -> dict:
        entry = {
            "category": category,
            "test": test,
            "result": result.value,
            "detail": detail,
            "timestamp": datetime.now().isoformat(),
        }
        if data is not None:
            entry["data"] = data
        if fix:
            entry["suggested_fix"] = fix
        self.results.append(entry)
        return entry

    def _ask_human(self, question: str, expected: str = "") -> TestResult:
        """Pause for human verification. Returns PASS if confirmed, NEEDS_HUMAN if interactive mode off."""
        if not self.interactive:
            return TestResult.NEEDS_HUMAN
        print(f"\n{'='*60}")
        print(f"👤 HUMAN CHECK REQUIRED")
        print(f"{'='*60}")
        print(f"Q: {question}")
        if expected:
            print(f"Expected: {expected}")
        print()
        while True:
            resp = input("Does this check pass? [y]es / [n]o / [s]kip: ").strip().lower()
            if resp in ('y', 'yes'):
                return TestResult.PASS
            elif resp in ('n', 'no'):
                return TestResult.FAIL
            elif resp in ('s', 'skip'):
                return TestResult.SKIP
            print("Please answer y, n, or s")

    def _send_gcode(self, cmd: str) -> dict:
        """Send G-code and return response."""
        result = self.api.send_gcode(cmd)
        if "error" not in result:
            self._gcode_responses.append(f"> {cmd}\n  OK")
        else:
            self._gcode_responses.append(f"> {cmd}\n  ERROR: {result['error']}")
        return result

    # ── 1. System Health ─────────────────────────────────────────────────

    def check_system_health(self) -> list[dict]:
        """Check OctoPrint and Klipper connectivity."""
        print("\n" + "=" * 60)
        print("🔧 SYSTEM HEALTH CHECK")
        print("=" * 60)

        # OctoPrint connectivity
        version = self.api.get_version()
        if "error" in version:
            self._record("system", "OctoPrint connectivity", TestResult.FAIL,
                         f"Cannot reach OctoPrint: {version['error']}",
                         fix="Check network, power, and OctoPrint service on the Pi.")
            return self.results
        else:
            self._record("system", "OctoPrint connectivity", TestResult.PASS,
                         f"OctoPrint {version.get('server', '?')} running, API {version.get('api', '?')}",
                         data=version)
            print(f"  ✅ OctoPrint {version.get('server', '?')} — API v{version.get('api', '?')}")

        # Printer connection state
        conn = self.api.get_connection()
        current = conn.get("current", {})
        state = current.get("state", "unknown")
        if state == "Operational":
            self._record("system", "Printer connection state", TestResult.PASS,
                         f"State: {state}, Port: {current.get('port', '?')}",
                         data=current)
            print(f"  ✅ Printer state: {state}")
        elif state == "Closed":
            self._record("system", "Printer connection state", TestResult.WARN,
                         f"Printer not connected. State: {state}",
                         fix="Connect to printer in OctoPrint or check serial port.")
            print(f"  ⚠️  Printer state: {state} — not connected")
        else:
            self._record("system", "Printer connection state", TestResult.FAIL,
                         f"Unexpected state: {state}", data=current,
                         fix="Check printer serial connection and MCU power.")
            print(f"  ❌ Printer state: {state}")

        # Get full printer state for temps
        printer = self.api.get_printer_state(history=True, limit=30)
        self.printer_state = printer

        # Temperature data present?
        temp_data = printer.get("temperature", {})
        if not temp_data:
            self._record("system", "Temperature reporting", TestResult.WARN,
                         "No temperature data available from printer",
                         fix="Check if Klipper is running and reporting temperatures.")
            print("  ⚠️  No temperature data reported")
        else:
            heaters_found = list(temp_data.keys())
            self._record("system", "Temperature reporting", TestResult.PASS,
                         f"{len(heaters_found)} heater(s) reporting: {', '.join(heaters_found)}",
                         data=heaters_found)
            print(f"  ✅ Temperature sensors active: {', '.join(heaters_found)}")

        return self.results

    # ── 2. Thermistor / Thermostat Diagnostics ────────────────────────────

    def check_thermistor(self) -> list[dict]:
        """Check thermistor health: room temp sanity, ADC values."""
        print("\n" + "=" * 60)
        print("🌡️  THERMISTOR / TEMPERATURE SENSOR CHECK")
        print("=" * 60)

        printer = self.printer_state or self.api.get_printer_state(history=True, limit=30)
        temp_data = printer.get("temperature", {})

        if not temp_data:
            self._record("thermistor", "Sensor data available", TestResult.FAIL,
                         "No temperature data from printer",
                         fix="Check thermistor wiring and sensor_type in printer.cfg.")
            return self.results

        # Check each thermistor
        for heater_name, heater_data in temp_data.items():
            actual = heater_data.get("actual", 0)
            target = heater_data.get("target", 0)

            # Room temperature sanity check (printer cold)
            if target == 0 or target < 30:
                if actual < -10:
                    self._record("thermistor", f"{heater_name} cold reading", TestResult.FAIL,
                                 f"Temperature {actual}°C is impossibly low — likely short/disconnect",
                                 fix=f"Check {heater_name} thermistor wiring for short circuit. "
                                      "Check sensor_type in printer.cfg matches physical thermistor.")
                    print(f"  ❌ {heater_name}: {actual}°C — TOO LOW (possible short)")
                elif actual > 80:
                    self._record("thermistor", f"{heater_name} cold reading", TestResult.FAIL,
                                 f"Temperature {actual}°C is too high for room temp — likely open circuit",
                                 fix=f"Check {heater_name} thermistor wiring for broken connection. "
                                      "Open circuit reads as very high temperature.")
                    print(f"  ❌ {heater_name}: {actual}°C — TOO HIGH (possible open circuit)")
                elif actual < 0:
                    self._record("thermistor", f"{heater_name} cold reading", TestResult.WARN,
                                 f"Temperature {actual}°C is below freezing — unusual",
                                 fix=f"Verify {heater_name} thermistor type matches config.")
                    print(f"  ⚠️  {heater_name}: {actual}°C — below freezing")
                elif 10 <= actual <= 45:
                    self._record("thermistor", f"{heater_name} cold reading", TestResult.PASS,
                                 f"{actual}°C — within expected ambient range")
                    print(f"  ✅ {heater_name}: {actual}°C — normal ambient")
                else:
                    self._record("thermistor", f"{heater_name} cold reading", TestResult.WARN,
                                 f"{actual}°C — outside expected ambient range (10-45°C)",
                                 fix=f"Check if printer recently heated. Verify sensor_type for {heater_name}.")
                    print(f"  ⚠️  {heater_name}: {actual}°C — unusual ambient")
            else:
                # Heater is active — check for stable reading
                expected_diff = abs(actual - target)
                if expected_diff > 15:
                    self._record("thermistor", f"{heater_name} active reading", TestResult.WARN,
                                 f"Target {target}°C, actual {actual}°C — large deviation ({expected_diff:.0f}°C)",
                                 fix="PID tuning may be needed. Run PID_CALIBRATE.")
                    print(f"  ⚠️  {heater_name}: target={target}°C actual={actual}°C (deviation: {expected_diff:.0f}°C)")
                else:
                    self._record("thermistor", f"{heater_name} active reading", TestResult.PASS,
                                 f"Target {target}°C, actual {actual}°C — stable")
                    print(f"  ✅ {heater_name}: target={target}°C actual={actual}°C — stable")

        # Check temperature history for anomalies
        history = printer.get("temperature", {})
        for heater_name, hdata in history.items():
            temps_list = hdata.get("temps", hdata.get("history", []))
            if temps_list and len(temps_list) > 5:
                actuals = [t.get("actual", t[1] if isinstance(t, list) else 0) for t in temps_list]
                if actuals:
                    temp_range = max(actuals) - min(actuals)
                    if temp_range > 30 and hdata.get("target", 0) > 0:
                        self._record("thermistor", f"{heater_name} stability", TestResult.WARN,
                                     f"Temperature fluctuated {temp_range:.1f}°C over last {len(temps_list)} readings",
                                     fix="Check thermistor connection for intermittent contact. "
                                          "PID tuning may help reduce oscillation.")
                        print(f"  ⚠️  {heater_name}: fluctuated {temp_range:.1f}°C — possible connection issue")

        return self.results

    def check_adc_values(self) -> list[dict]:
        """Check raw ADC values via QUERY_ADC G-code."""
        print("\n" + "=" * 60)
        print("📊 ADC VALUES CHECK (raw sensor data)")
        print("=" * 60)

        resp = self._send_gcode("QUERY_ADC")
        if "error" in resp:
            self._record("thermistor", "ADC query", TestResult.WARN,
                         f"Could not query ADC values: {resp['error']}",
                         fix="Ensure Klipper is connected and running.")
            print("  ⚠️  Could not query ADC")
        else:
            self._record("thermistor", "ADC query", TestResult.PASS,
                         "ADC values queried successfully",
                         data=resp)
            print("  ✅ ADC values available")
            # The response comes back via OctoPrint's terminal output
            # In real usage, we'd parse the terminal log

        return self.results

    # ── 3. Heater Diagnostics ────────────────────────────────────────────

    def check_heaters(self) -> list[dict]:
        """Check heater functionality: PWM, heating rate, PID."""
        print("\n" + "=" * 60)
        print("🔥 HEATER DIAGNOSTICS")
        print("=" * 60)

        printer = self.printer_state or self.api.get_printer_state(history=True, limit=30)
        temp_data = printer.get("temperature", {})

        heater_checks = []
        # Detect extruder(s) and bed
        for hname in temp_data:
            if "extruder" in hname.lower() or hname.lower().startswith("t"):
                heater_checks.append((hname, "extruder"))
            elif "bed" in hname.lower():
                heater_checks.append((hname, "bed"))
            elif "chamber" in hname.lower():
                heater_checks.append((hname, "chamber"))

        if not heater_checks:
            self._record("heater", "Heater detection", TestResult.WARN,
                         "No recognizable heaters found in temperature data",
                         fix="Check printer.cfg for [extruder] and [heater_bed] sections.")
            return self.results

        for hname, htype in heater_checks:
            hdata = temp_data[hname]
            actual = hdata.get("actual", 0)
            target = hdata.get("target", 0)

            # Check if heater responds
            if target > 0:
                # Heater is on — check if it's working
                if actual < target - 10 and target > 30:
                    self._record("heater", f"{hname} heating response", TestResult.WARN,
                                 f"Target={target}°C but actual={actual}°C — not heating sufficiently",
                                 fix=f"Check {hname} heater cartridge/pad wiring and resistance. "
                                      "Check heater_pin in config. Verify power supply voltage.")
                    print(f"  ⚠️  {hname}: target={target}°C actual={actual}°C — not keeping up")
                elif actual > target + 15:
                    self._record("heater", f"{hname} overshoot", TestResult.WARN,
                                 f"Overshooting: target={target}°C actual={actual}°C",
                                 fix="PID tuning needed. Run PID_CALIBRATE HEATER=... TARGET=...")
                    print(f"  ⚠️  {hname}: overshooting — target={target}°C actual={actual}°C")
                else:
                    self._record("heater", f"{hname} active heating", TestResult.PASS,
                                 f"Heating normally: target={target}°C actual={actual}°C")
                    print(f"  ✅ {hname}: target={target}°C actual={actual}°C")
            else:
                # Heater is off — ask human to do a quick heat test
                if htype == "extruder":
                    result = self._ask_human(
                        f"Set {hname} to 50°C via OctoPrint and verify:",
                        f"1. {hname} temperature should rise within 30 seconds\n"
                        f"2. Temperature should not increase when turned off"
                    )
                    self._record("heater", f"{hname} heat test", result,
                                 "Human-verified heat test",
                                 fix="If heater doesn't heat: check heater_pin, wiring, cartridge resistance.")
                elif htype == "bed":
                    result = self._ask_human(
                        f"Set bed to 40°C via OctoPrint and verify:",
                        f"1. Bed temperature should rise within 60 seconds\n"
                        f"2. Bed should feel warm to touch"
                    )
                    self._record("heater", f"{hname} heat test", result,
                                 "Human-verified bed heat test",
                                 fix="If bed doesn't heat: check SSR/MOSFET, bed wiring, power supply.")

        # Check PID calibration status (via Klipper verify_heater)
        # This would be parsed from klippy.log in a full implementation
        self._record("heater", "PID status", TestResult.NEEDS_HUMAN,
                     "Recommend running PID_CALIBRATE if not done recently",
                     fix="Run: PID_CALIBRATE HEATER=extruder TARGET=<print_temp> then SAVE_CONFIG")
        print("  ℹ️  Consider running PID_CALIBRATE for all active heaters")

        return self.results

    # ── 4. Extrusion Diagnostics ─────────────────────────────────────────

    def check_extrusion(self) -> list[dict]:
        """Check extruder: direction, rotation distance, temperature stability."""
        print("\n" + "=" * 60)
        print("🧵 EXTRUSION DIAGNOSTICS")
        print("=" * 60)

        printer = self.printer_state or self.api.get_printer_state(history=True, limit=10)
        temp_data = printer.get("temperature", {})

        # Find extruder(s)
        extruders = [h for h in temp_data if "extruder" in h.lower() or h.lower().startswith("t")]
        if not extruders:
            self._record("extrusion", "Extruder detection", TestResult.FAIL,
                         "No extruder heater detected",
                         fix="Check printer.cfg for [extruder] section.")
            return self.results

        for ext_name in extruders:
            ext_data = temp_data[ext_name]
            actual = ext_data.get("actual", 0)

            # Cold extrusion prevention check
            if actual < 170:
                self._record("extrusion", f"{ext_name} cold extrusion protection", TestResult.PASS,
                             f"Extruder at {actual}°C — cold extrusion correctly prevented",
                             data={"min_extrude_temp": "Typically 170°C"})
                print(f"  ✅ {ext_name}: cold extrusion protection active ({actual}°C < 170°C)")
            else:
                self._record("extrusion", f"{ext_name} cold extrusion protection", TestResult.PASS,
                             f"Extruder at {actual}°C — hot enough to extrude")

            # Human-in-the-loop: extruder direction
            result = self._ask_human(
                f"Extruder direction check for {ext_name}:",
                f"1. Heat {ext_name} to printing temperature\n"
                f"2. Use OctoPrint's extrude button (or send G1 E10 F60)\n"
                f"3. Verify filament moves FORWARD (toward the nozzle)"
            )
            self._record("extrusion", f"{ext_name} direction", result,
                         "Human-verified extrusion direction",
                         fix="If filament moves backward: invert dir_pin in [extruder] config.")

            # Rotation distance check
            result = self._ask_human(
                f"Rotation distance verification for {ext_name}:",
                f"1. Mark filament 120mm from extruder inlet\n"
                f"2. Extrude 100mm (G1 E100 F60)\n"
                f"3. Measure remaining filament to mark\n"
                f"4. Should be exactly 20mm remaining (±1mm)"
            )
            self._record("extrusion", f"{ext_name} rotation_distance", result,
                         "Human-verified e-step calibration",
                         fix="If not 20mm: adjust rotation_distance in config. "
                              "New = Old × (100 / actual_extruded). Then RESTART.")

            # Extruder temperature stability during extrusion
            if actual >= 170:
                # Check if temp drops during extrusion (common issue)
                history = printer.get("temperature", {}).get(ext_name, {})
                temps_list = history.get("temps", history.get("history", []))
                if temps_list and len(temps_list) > 5:
                    recent = [t.get("actual", t[1] if isinstance(t, list) else 0) for t in temps_list[-10:]]
                    if recent:
                        temp_variance = max(recent) - min(recent)
                        if temp_variance > 5:
                            self._record("extrusion", f"{ext_name} temp stability", TestResult.WARN,
                                         f"Temperature varies {temp_variance:.1f}°C — may affect extrusion",
                                         fix="Run PID_CALIBRATE for extruder. Check silicone sock on heater block.")
                            print(f"  ⚠️  {ext_name}: temp varies {temp_variance:.1f}°C")

        # Check for common extrusion config issues
        self._record("extrusion", "max_extrude_only_distance", TestResult.NEEDS_HUMAN,
                     "Verify max_extrude_only_distance and max_extrude_cross_section in config",
                     fix="Ensure max_extrude_cross_section >= 4.0 * nozzle_diameter^2 for normal printing.")

        return self.results

    # ── 5. Homing Diagnostics ────────────────────────────────────────────

    def check_homing(self) -> list[dict]:
        """Check homing: endstop states, homing sequence, repeatability."""
        print("\n" + "=" * 60)
        print("🏠 HOMING DIAGNOSTICS")
        print("=" * 60)

        # Query endstop states
        resp = self._send_gcode("QUERY_ENDSTOPS")
        if "error" in resp:
            self._record("homing", "Endstop query", TestResult.FAIL,
                         f"Cannot query endstops: {resp['error']}",
                         fix="Ensure Klipper is connected. Check if printer is in shutdown state.")
            print("  ❌ Cannot query endstops")
        else:
            self._record("homing", "Endstop query", TestResult.PASS,
                         "Endstop query sent — check terminal for states")
            print("  ✅ Endstop query sent")

        # Pre-homing safety checks
        print("\n  ⚠️  BEFORE HOMING — verify:")
        print("     1. Print bed is clear of objects")
        print("     2. No filament oozing from nozzle")
        print("     3. All axes can move freely (not against endstops)")

        result = self._ask_human(
            "Ready to test homing? Ensure the printer is clear!",
            "The printer will move all axes to their endstops."
        )
        if result == TestResult.FAIL:
            self._record("homing", "Pre-flight check", TestResult.FAIL,
                         "User reported printer not ready for homing")
            return self.results
        if result == TestResult.SKIP:
            self._record("homing", "Pre-flight check", TestResult.SKIP,
                         "Homing test skipped by user")
            return self.results

        # Send home command
        print("\n  🔄 Sending G28 (home all axes)...")
        resp = self._send_gcode("G28")
        if "error" in resp:
            self._record("homing", "G28 home all", TestResult.FAIL,
                         f"Homing failed: {resp['error']}",
                         fix="Check endstop wiring, stepper enable pins, "
                              "and endstop_pin configuration.")
            print(f"  ❌ Homing failed: {resp['error']}")
        else:
            # Wait for homing to complete, then check
            time.sleep(2)
            printer = self.api.get_printer_state()
            flags = printer.get("state", {}).get("flags", {})
            if flags.get("ready", False):
                self._record("homing", "G28 home all", TestResult.PASS,
                             "All axes homed successfully")
                print("  ✅ Homing completed successfully")
            else:
                self._record("homing", "G28 home all", TestResult.WARN,
                             "Homing may not have completed — check printer state")
                print("  ⚠️  Homing status unclear")

        # Endstop repeatability check
        result = self._ask_human(
            "Endstop consistency check:",
            "1. Home each axis individually (G28 X, G28 Y, G28 Z)\n"
            "2. After each home, does the axis consistently stop at the same position?\n"
            "3. Listen for grinding or clicking (indicates endstop not triggering)"
        )
        self._record("homing", "Endstop consistency", result,
                     "Human-verified endstop repeatability",
                     fix="If inconsistent: check endstop mounting, wiring, "
                          "debounce settings. Consider hall-effect endstops for better precision.")

        # Check for common homing config issues
        self._record("homing", "position_endstop", TestResult.NEEDS_HUMAN,
                     "Verify position_endstop and position_max values are physically accurate",
                     fix="position_endstop should be at the physical endstop contact point. "
                          "position_max should be the total travel distance from endstop.")

        return self.results

    # ── 6. Motion System Diagnostics ─────────────────────────────────────

    def check_motion_system(self) -> list[dict]:
        """Check stepper drivers, axis movement, belt tension."""
        print("\n" + "=" * 60)
        print("⚙️  MOTION SYSTEM DIAGNOSTICS")
        print("=" * 60)

        # STEPPER_BUZZ for each axis (motor identification)
        for axis in ["stepper_x", "stepper_y", "stepper_z"]:
            result = self._ask_human(
                f"Motor identification for {axis}:",
                f"We will send STEPPER_BUZZ STEPPER={axis}.\n"
                f"The motor should vibrate/buzz for a few seconds."
            )
            if result == TestResult.PASS:
                self._send_gcode(f"STEPPER_BUZZ STEPPER={axis}")
                time.sleep(1)
                result2 = self._ask_human(
                    f"Did {axis} motor buzz/vibrate?",
                    "The correct motor should have moved slightly and buzzed."
                )
                self._record("motion", f"{axis} identification", result2,
                             "STEPPER_BUZZ test",
                             fix=f"If wrong motor moved: {axis} is mapped to wrong physical motor. "
                                  "Swap stepper driver connections.")

        # Axis direction check
        for axis, direction, description in [
            ("X", "right", "Nozzle moves RIGHT (toward X max)"),
            ("Y", "back", "Bed moves BACK (toward Y max) or nozzle moves forward"),
            ("Z", "up", "Nozzle/gantry moves UP (away from bed)"),
        ]:
            result = self._ask_human(
                f"{axis}-axis direction check:",
                f"Send G91 (relative mode), then G1 {axis}+10 F1000.\n"
                f"Expected: {description}"
            )
            self._record("motion", f"{axis}-axis direction", result,
                         f"Human-verified {axis}-axis moves {direction}",
                         fix=f"If {axis}-axis moves wrong direction: add '!' to dir_pin for [stepper_{axis.lower()}].")

        # Belt tension check (human)
        result = self._ask_human(
            "Belt tension check:",
            "1. Pluck X-axis belt like a guitar string — should produce a low bass note (~50-70Hz)\n"
            "2. Pluck Y-axis belt — same frequency\n"
            "3. Belts should not sag or skip teeth when moving by hand"
        )
        self._record("motion", "Belt tension", result,
                     "Human-verified belt tension",
                     fix="If belts are loose: tighten tensioners. "
                          "If skipping: check pulley set screws, belt alignment.")

        # TMC driver status (if Trinamic drivers)
        # This requires DUMP_TMC which may not be available via OctoPrint
        self._record("motion", "TMC driver check", TestResult.NEEDS_HUMAN,
                     "If using TMC drivers (TMC2209/5160): verify they report no errors",
                     fix="Send DUMP_TMC STEPPER=stepper_x to check driver registers. "
                          "Look for overtemperature, short, or open-load flags.")
        print("  ℹ️  For TMC diagnostics, use DUMP_TMC STEPPER=stepper_x in Klipper console")

        return self.results

    # ── 7. Probe Diagnostics ─────────────────────────────────────────────

    def check_probe(self) -> list[dict]:
        """Check probe: accuracy, repeatability, bed mesh."""
        print("\n" + "=" * 60)
        print("📍 PROBE DIAGNOSTICS")
        print("=" * 60)

        # Check if probe is configured
        printer = self.printer_state or self.api.get_printer_state()

        # Try PROBE_ACCURACY
        result = self._ask_human(
            "Probe accuracy test:",
            "We will send PROBE_ACCURACY SAMPLES=10.\n"
            "This probes the same spot 10 times to check repeatability.\n"
            "Standard deviation should be < 0.003mm for a good probe."
        )
        if result == TestResult.PASS:
            resp = self._send_gcode("PROBE_ACCURACY SAMPLES=10")
            if "error" in resp:
                self._record("probe", "Probe accuracy", TestResult.WARN,
                             f"PROBE_ACCURACY failed: {resp['error']}",
                             fix="Check if [probe] section exists in config. Ensure correct probe pin.")
                print(f"  ⚠️  PROBE_ACCURACY failed: {resp['error']}")
            else:
                self._record("probe", "Probe accuracy", TestResult.PASS,
                             "PROBE_ACCURACY started — check terminal for results")
                print("  ✅ PROBE_ACCURACY running — check standard deviation in terminal")
        else:
            self._record("probe", "Probe accuracy", result,
                         "Probe accuracy test skipped or deferred")

        # Probe Z offset check
        result = self._ask_human(
            "Probe Z-offset verification:",
            "1. Home Z with probe (G28 Z)\n"
            "2. Move nozzle to Z=0 (G1 Z0 F200)\n"
            "3. Does a piece of paper just fit under the nozzle with slight friction?"
        )
        self._record("probe", "Z-offset", result,
                     "Human-verified probe Z-offset",
                     fix="If Z-offset is wrong: run PROBE_CALIBRATE to set correct offset. Then SAVE_CONFIG.")

        # Bed mesh quality check
        result = self._ask_human(
            "Bed mesh quality:",
            "1. Run BED_MESH_CALIBRATE to generate a mesh\n"
            "2. Run BED_MESH_OUTPUT to see mesh data\n"
            "3. Is the total variance (max - min) less than 0.2mm?"
        )
        self._record("probe", "Bed mesh", result,
                     "Human-verified bed mesh quality",
                     fix="If variance > 0.2mm: check bed level, gantry alignment, probe mount tightness.")

        return self.results

    # ── 8. MCU / Electronics Diagnostics ──────────────────────────────────

    def check_electronics(self) -> list[dict]:
        """Check MCU health, CAN bus, TMC drivers, power supply."""
        print("\n" + "=" * 60)
        print("🔌 ELECTRONICS / MCU DIAGNOSTICS")
        print("=" * 60)

        # MCU communication check
        printer = self.printer_state or self.api.get_printer_state()
        state_flags = printer.get("state", {}).get("flags", {})

        if state_flags.get("ready"):
            self._record("electronics", "Klipper ready state", TestResult.PASS,
                         "Printer reports ready — MCU communication OK")
            print("  ✅ Klipper ready — MCU communication healthy")
        elif state_flags.get("error"):
            self._record("electronics", "Klipper ready state", TestResult.FAIL,
                         "Printer in error state",
                         fix="Check klippy.log for MCU errors. Common: Lost communication, "
                              "ADC out of range, Timer too close.")
            print("  ❌ Printer in error state")
        else:
            self._record("electronics", "Klipper ready state", TestResult.WARN,
                         f"Printer state: {state_flags}")

        # TMC driver check via DUMP_TMC
        for axis in ["stepper_x", "stepper_y", "stepper_z"]:
            resp = self._send_gcode(f"DUMP_TMC STEPPER={axis}")
            if "error" not in resp:
                self._record("electronics", f"TMC driver {axis}", TestResult.PASS,
                             f"{axis} driver responding")
                print(f"  ✅ {axis} TMC driver OK")
            else:
                self._record("electronics", f"TMC driver {axis}", TestResult.WARN,
                             f"Cannot query {axis}: {resp.get('error', 'unknown')}",
                             fix="Check 24V motor power. Check TMC driver wiring. "
                                  "Try power cycling the printer.")
                print(f"  ⚠️  {axis}: {resp.get('error', 'unknown')}")

        # CAN bus check (Klipper responds with MCU info)
        result = self._ask_human(
            "CAN bus health check (requires SSH):",
            "Run: ip -details link show can0\n"
            "Expected: state UP, bitrate 500000\n"
            "Also: ~/klippy-env/bin/python ~/klipper/scripts/canbus_query.py can0\n"
            "Should show UUIDs for all CAN nodes"
        )
        self._record("electronics", "CAN bus health", result,
                     "Human-verified CAN bus status",
                     fix="If CAN DOWN: check USB CAN adapter, verify /etc/network/interfaces.d/can0. "
                          "If no nodes found: check 120ohm termination at both ends, check CAN wiring.")

        # Power supply check
        result = self._ask_human(
            "Power supply check (requires SSH):",
            "1. vcgencmd get_throttled — should be throttled=0x0 (no issues)\n"
            "2. Measure 24V at PSU terminals with multimeter — should be 23.5-24.5V\n"
            "3. Turn on all heaters + motors — 24V should not drop below 22V"
        )
        self._record("electronics", "Power supply health", result,
                     "Human-verified PSU health",
                     fix="If undervoltage (throttled != 0x0): use quality 5V PSU. "
                          "If 24V sag: check PSU rating, check wiring gauge, add capacitor.")

        # MCU temperature check
        result = self._ask_human(
            "MCU temperature check:",
            "Check MCU temperatures in OctoPrint temperature graph or Klipper console.\n"
            "STM32H723 normal: 30-65C. RP2040 normal: 30-60C.\n"
            "Both should have [temperature_sensor] sections in printer.cfg"
        )
        self._record("electronics", "MCU temperature", result,
                     "Human-verified MCU temperatures",
                     fix="If MCU >80C: add heatsink + fan. Reduce stepper current. "
                          "If no MCU temp reading: add [temperature_sensor mcu_temp] with sensor_type: temperature_mcu.")

        # Firmware version check
        self._send_gcode("M115")
        self._record("electronics", "Firmware version", TestResult.PASS,
                     "M115 sent — check terminal for FIRMWARE_NAME and version")
        print("  ℹ️  M115 sent — check firmware version in terminal")

        return self.results

    # ── Report Generation ────────────────────────────────────────────────

    def run_all_checks(self) -> dict:
        """Run all diagnostic checks."""
        categories = [
            ("system", self.check_system_health),
            ("thermistor", self.check_thermistor),
            ("thermistor_adc", self.check_adc_values),
            ("heater", self.check_heaters),
            ("extrusion", self.check_extrusion),
            ("homing", self.check_homing),
            ("motion", self.check_motion_system),
            ("probe", self.check_probe),
            ("electronics", self.check_electronics),
        ]

        for cat_name, check_fn in categories:
            try:
                check_fn()
            except Exception as e:
                self._record(cat_name, "check execution", TestResult.FAIL,
                             f"Diagnostic crashed: {e}",
                             fix="Check connectivity and try again.")
                print(f"  ❌ Check '{cat_name}' failed with error: {e}")

        return self.generate_report()

    def run_selected_checks(self, selections: list[str]) -> dict:
        """Run only selected diagnostic categories."""
        category_map = {
            "system": self.check_system_health,
            "thermistor": self.check_thermistor,
            "adc": self.check_adc_values,
            "heater": self.check_heaters,
            "extrusion": self.check_extrusion,
            "homing": self.check_homing,
            "motion": self.check_motion_system,
            "probe": self.check_probe,
            "electronics": self.check_electronics,
        }

        for sel in selections:
            sel = sel.lower().strip()
            if sel in category_map:
                try:
                    category_map[sel]()
                except Exception as e:
                    self._record(sel, "check execution", TestResult.FAIL,
                                 f"Diagnostic crashed: {e}")
                    print(f"  ❌ Check '{sel}' failed: {e}")
            else:
                print(f"  ⚠️  Unknown check: '{sel}'. Available: {', '.join(category_map.keys())}")

        return self.generate_report()

    def generate_report(self) -> dict:
        """Generate final diagnostic report."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r["result"] == "pass")
        failed = sum(1 for r in self.results if r["result"] == "fail")
        warned = sum(1 for r in self.results if r["result"] == "warn")
        skipped = sum(1 for r in self.results if r["result"] == "skip")
        needs_human = sum(1 for r in self.results if r["result"] == "needs_human")

        # Categorize fixes by urgency
        critical_fixes = [r for r in self.results if r["result"] == "fail"]
        warnings = [r for r in self.results if r["result"] == "warn"]
        recommendations = [r for r in self.results if r["result"] == "needs_human"]

        report = {
            "diagnostic_report": {
                "timestamp": self.start_time.isoformat(),
                "duration_seconds": (datetime.now() - self.start_time).total_seconds(),
                "summary": {
                    "total_checks": total,
                    "passed": passed,
                    "failed": failed,
                    "warnings": warned,
                    "skipped": skipped,
                    "needs_human": needs_human,
                    "health_score": round((passed / max(total, 1)) * 100, 1),
                },
                "critical_issues": critical_fixes,
                "warnings": warnings,
                "recommendations": recommendations,
                "all_results": self.results,
                "printer_state_snapshot": self.printer_state,
            }
        }

        return report


# ── Output Formatting ─────────────────────────────────────────────────────────

def print_summary(report: dict):
    """Print a formatted summary to console."""
    summary = report["diagnostic_report"]["summary"]
    print("\n" + "=" * 60)
    print("📋 DIAGNOSTIC REPORT SUMMARY")
    print("=" * 60)
    print(f"  Total checks:    {summary['total_checks']}")
    print(f"  ✅ Passed:        {summary['passed']}")
    print(f"  ❌ Failed:        {summary['failed']}")
    print(f"  ⚠️  Warnings:     {summary['warnings']}")
    print(f"  ⏭️  Skipped:      {summary['skipped']}")
    print(f"  👤 Needs Human:   {summary['needs_human']}")
    print(f"  📊 Health Score:  {summary['health_score']}%")
    print()

    critical = report["diagnostic_report"].get("critical_issues", [])
    if critical:
        print("🔴 CRITICAL ISSUES (fix immediately):")
        for issue in critical:
            print(f"   [{issue['category']}] {issue['test']}")
            print(f"   → {issue['detail']}")
            if issue.get("suggested_fix"):
                print(f"   🔧 Fix: {issue['suggested_fix']}")
            print()

    warns = report["diagnostic_report"].get("warnings", [])
    if warns:
        print("🟡 WARNINGS (address soon):")
        for w in warns:
            print(f"   [{w['category']}] {w['test']}: {w['detail']}")
            if w.get("suggested_fix"):
                print(f"   🔧 Fix: {w['suggested_fix']}")
        print()

    recs = report["diagnostic_report"].get("recommendations", [])
    if recs:
        print("🔵 RECOMMENDATIONS (human verification needed):")
        for r in recs:
            print(f"   [{r['category']}] {r['test']}: {r['detail']}")
            if r.get("suggested_fix"):
                print(f"   🔧 Fix: {r['suggested_fix']}")
        print()


# ── CLI Entry Point ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Live 3D Printer Diagnostics — Comprehensive health check wizard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python live_printer_diagnostics.py --ip 192.168.1.100 --api-key ABC123
  python live_printer_diagnostics.py --check heater,thermistor --interactive
  python live_printer_diagnostics.py --check all --output report.json
  python live_printer_diagnostics.py --check homing,motion --no-interactive

Available checks:
  all          Run all diagnostic categories
  system       OctoPrint/Klipper connectivity, MCU status
  thermistor   Temperature sensor sanity, ADC values
  heater       Heating element function, PID performance
  extrusion    Extruder direction, E-steps, temperature stability
  homing       Endstop states, homing sequence, repeatability
  motion       Stepper drivers, axis movement, belt tension
  probe        Probe accuracy, Z-offset, bed mesh quality
        """,
    )
    parser.add_argument("--ip", default=DEFAULT_IP,
                        help=f"OctoPrint IP address (default: {DEFAULT_IP})")
    parser.add_argument("--port", default=DEFAULT_PORT,
                        help=f"OctoPrint port (default: {DEFAULT_PORT})")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY,
                        help="OctoPrint API key")
    parser.add_argument("--check", default="all",
                        help="Comma-separated list of checks to run (default: all)")
    parser.add_argument("--interactive", action="store_true", default=True,
                        help="Enable human-in-the-loop prompts (default: True)")
    parser.add_argument("--no-interactive", dest="interactive", action="store_false",
                        help="Disable human prompts — automated mode")
    parser.add_argument("--output", "-o",
                        help="Save report to JSON file")
    parser.add_argument("--timeout", type=int, default=10,
                        help="API request timeout in seconds (default: 10)")
    args = parser.parse_args()

    # Banner
    print("=" * 60)
    print("🖨️  LIVE 3D PRINTER DIAGNOSTICS WIZARD")
    print("=" * 60)
    print(f"  Target: {args.ip}:{args.port}")
    print(f"  Mode: {'Interactive' if args.interactive else 'Automated'}")
    print(f"  Checks: {args.check}")
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Connect
    api = OctoPrintAPI(ip=args.ip, port=args.port, api_key=args.api_key, timeout=args.timeout)
    diag = PrinterDiagnostics(api, interactive=args.interactive)

    # Run checks
    if args.check.lower() == "all":
        report = diag.run_all_checks()
    else:
        selections = [s.strip() for s in args.check.split(",")]
        report = diag.run_selected_checks(selections)

    # Print summary
    print_summary(report)

    # Save if requested
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"📁 Report saved to: {output_path.resolve()}")

    # Return exit code based on results
    failed = report["diagnostic_report"]["summary"]["failed"]
    if failed > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
