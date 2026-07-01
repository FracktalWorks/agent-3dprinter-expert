#!/usr/bin/env python3
"""
ControlCenter Reference — Searches the ControlCenter codebase for relevant
code patterns, debugging techniques, and implementation details to help
diagnose 3D printer software issues.

Usage:
    python controlcenter_reference.py --query "websocket reconnect"
    python controlcenter_reference.py --query "printer error handling"
    python controlcenter_reference.py --query "temperature polling" --module octoprint_client
    python controlcenter_reference.py --list-modules
"""

import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional


# ── Default ControlCenter path ────────────────────────────────────────────────
DEFAULT_CC_PATH = os.environ.get(
    "CONTROLCENTER_PATH",
    r"C:\Users\VijayRaghavVarada\Documents\Github\ControlCenter",
)


# ── Module registry with descriptions ─────────────────────────────────────────
MODULES = {
    "octoprint_client": {
        "path": "octoprint_ControlCenter/octoprint_client",
        "description": "OctoPrint REST API + WebSocket client (singleton pattern)",
        "key_files": ["octoprintAPI.py", "websocket_client.py", "octoprint_singleton.py"],
        "patterns": [
            "REST API: version, connection, printer state, job control, files, settings",
            "WebSocket: SockJS at ws://ip/sockjs/{server}/{uuid}/websocket",
            "OctoPrintWebSocket(QThread): heartbeat (120s), reconnect (max 5), SockJS framing",
            "Signals: temperatures_signal, status_signal, klipper_state_signal, printer_error_signal",
            "Plugin messages: Klipper state (regex: klipper\\s*state:), probe accuracy, errors",
            "Filament events: runout/jam/insert parsed from terminal messages",
            "Auth: passive login → GET /api/login → session key → WebSocket auth",
        ],
    },
    "controller": {
        "path": "octoprint_ControlCenter/controller",
        "description": "MainController — startup lifecycle, WebSocket wiring, error cascading prevention",
        "key_files": ["main_controller.py"],
        "patterns": [
            "startup: init → connectivity check → validate printer.cfg → load UI → init WS → firmware update check",
            "WebSocket signal wiring: temperatures → printer_model.updateTemperature, status → printer_model.updateStatus",
            "Error handling: CRITICAL_PRINTER_ERRORS (15 entries), IGNORED_PRINTER_ERRORS",
            "Error cascading prevention: _handling_critical_error guard, _klipper_restart_in_progress suppression",
            "Klipper restart: _end_klipper_restart_grace_period, transient MCU error suppression",
            "showPrinterError(): re-entrancy guard → ignore list → critical check → cancel+M112 → FIRMWARE_RESTART",
            "Printer state: onKlipperStateChanged, refresh_klipper_status, startup grace period (60s)",
            "Config validation: checkKlipperPrinterCFG, _ensure_valid_printer_config, backup management",
        ],
    },
    "firmware": {
        "path": "octoprint_ControlCenter/firmware",
        "description": "Production Klipper configs — Dragon, TwinDragon, Volterra printer definitions with PRINTER_VARIABLES",
        "key_files": ["printer.cfg", "PRINTER_DRAGON_400.cfg", "PRINTER_TWINDRAGON_600.cfg", "BASE_DRAGON.cfg", "BASE_TWINDRAGON.cfg", "CORE_GCODE_MACROS.cfg"],
        "patterns": [
            "PRINTER_VARIABLES macro: calibrationPosition, machineBuildSize, IS_DUAL_NOZZLE, HAS_DUAL_MATERIAL_BAY",
            "Config hierarchy: printer.cfg → [include PRINTER_*.cfg] → BASE_*.cfg + CORE_GCODE_MACROS.cfg + toolheads",
            "MCU: STM32H723 CAN bus bridge, RP2040 toolhead, gs_usb driver, CAN via USB adapter",
            "Steppers: TMC5160 X/Y (SPI, 1.2A), TMC2209 extruder (UART, 0.85A), rotation_distance: X/Y=32, extruder≈4.72",
            "Thermistors: EPCOS 100K B57560G104F, sensor_type in toolhead configs",
            "Dual carriage: [dual_carriage] for TwinDragon IDEX, [stepper_x1] for single-extruder Dragon",
            "Filament sensors: [filament_switch_sensor T0_RUNOUT], [filament_motion_sensor encoder_sensor_T0]",
            "Add-on modules: MAG_DOOR.cfg, CHAMBER_COOLING.cfg, filament sensors — enable by uncommenting [include]",
        ],
    },
    "models": {
        "path": "octoprint_ControlCenter/models",
        "description": "PrinterModel — central state with pyqtSignals for all printer data",
        "key_files": ["printer_model.py"],
        "patterns": [
            "State signals: temperatures_updated, status_updated, klipper_state_changed, printer_error_signal",
            "Temperature: tool0Actual/Target, tool1Actual/Target, bedActual/Target",
            "Klipper state tracking: 'ready', 'shutdown', 'error', 'startup' — propagated from WebSocket",
            "Dynamic config loading: _load_printer_configuration() from Klipper PRINTER_VARIABLES",
            "Tool bay state: tool0/tool1 with material_bay_a/b, filament, status, nozzle tracking",
            "Print progress: print_progress, print_time, print_time_left from WebSocket job data",
            "Position tracking: current_position {x,y,z}, updated via M114 responses",
            "Preferences: filament runout/jam sensor, print restore, firmware update check, advanced debugging",
        ],
    },
    "ui": {
        "path": "octoprint_ControlCenter/ui",
        "description": "PyQt5 UI — screens, widgets, resources",
        "key_files": [],
        "patterns": [
            "Touchscreen UI components",
            "Loading screen with progress",
            "Settings management UI",
            "Home screen layout",
        ],
    },
    "utils": {
        "path": "octoprint_ControlCenter/utils",
        "description": "Utilities — PrinterConfigManager (dynamic config), logger, helpers, dialogs",
        "key_files": ["printer_config_manager.py", "logger.py", "helpers.py", "printer_preference_store.py", "printer_ui_config.py"],
        "patterns": [
            "PrinterConfigManager: singleton, parses PRINTER_VARIABLES, manages firmware deployment + OctoPrint config",
            "Config priority: deployed Klipper config (/home/pi/) → firmware directory fallback",
            "parse_printer_variables_from_file(): extracts variable_* from [gcode_macro PRINTER_VARIABLES]",
            "copy_firmware_files(): deploys .cfg files, updates printer.cfg include, preserves MCU + SAVE_CONFIG sections",
            "update_octoprint_config(): updates config.yaml appearance name + _default.profile dimensions",
            "printer_ui_config.py: is_dual_nozzle_printer(), is_dual_material_bay_printer()",
            "RotatingFileHandler logging to ControlCenter.log with advanced_debugging toggle",
        ],
    },
    "documentation": {
        "path": "Documentation",
        "description": "Debug sessions, error handling docs, testing guides, architecture notes",
        "key_files": ["ERROR_HANDLING_IMPROVEMENTS.md", "DYNAMIC_PRINTER_CONFIG.md", "MANUAL_TESTING_GUIDE.md",
                      "WEBSOCKET_UI_UPDATE_FIXES.md", "SESSION_2026-06-10_DRAGON400_DEBUG.md"],
        "patterns": [
            "SESSION_*_DEBUG.md: real debug session logs with SSH commands, Klipper log analysis, root cause + fixes",
            "ERROR_HANDLING_IMPROVEMENTS.md: error cascading fix — re-entrancy guard, restart suppression, probe substring too broad",
            "DYNAMIC_PRINTER_CONFIG.md: PRINTER_VARIABLES parser, config priority chain, firmware file deployment",
            "WEBSOCKET_UI_UPDATE_FIXES.md: @run_async removal, direct printer_model access fix, reconnection backoff",
            "MANUAL_TESTING_GUIDE.md: comprehensive test cases for home screen, calibration, filament, print, sensors",
            "HYBRID_COREXY_IDEX_Y_BACKLASH_X_BUMP.md: CoreXY IDEX diagnostic — X bump at Y direction change",
            "DRAGON_V2_DUAL_MATERIAL_BAY_IMPLEMENTATION.md: dual material bay architecture for Dragon 400 V2",
        ],
    },
}


def find_cc_path() -> Optional[str]:
    """Find the ControlCenter repo path."""
    expanded = os.path.expanduser(DEFAULT_CC_PATH)
    if os.path.exists(expanded):
        return expanded

    # Try common alternatives
    alternatives = [
        os.path.expanduser("~/Documents/Github/ControlCenter"),
        os.path.expanduser("~/ControlCenter"),
        "/home/pi/ControlCenter",
    ]
    for alt in alternatives:
        if os.path.exists(alt):
            return alt

    return None


def search_module(
    cc_path: str, module_name: str, query: str,
) -> dict:
    """Search within a specific module for relevant code."""
    module_info = MODULES.get(module_name)
    if not module_info:
        return {"error": f"Unknown module: {module_name}"}

    module_path = os.path.join(cc_path, module_info["path"])
    if not os.path.exists(module_path):
        return {"error": f"Module path not found: {module_path}"}

    results: list[dict] = []
    query_terms = query.lower().split()

    # Walk all Python and config files in the module
    for root, dirs, files in os.walk(module_path):
        # Skip __pycache__
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for filename in files:
            if not filename.endswith((".py", ".cfg", ".yaml", ".md", ".conf")):
                continue
            filepath = os.path.join(root, filename)
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                    lines = content.split("\n")

                # Score the file based on query term matches
                content_lower = content.lower()
                score = sum(
                    1 for term in query_terms if term in content_lower
                )

                if score == 0:
                    continue

                # Find specific matching lines
                matching_lines: list[dict] = []
                for i, line in enumerate(lines, 1):
                    line_lower = line.lower()
                    if any(term in line_lower for term in query_terms):
                        # Get context (3 lines before and after)
                        ctx_start = max(0, i - 4)
                        ctx_end = min(len(lines), i + 3)
                        context = "\n".join(
                            f"  {j}: {lines[j-1].rstrip()}"
                            for j in range(ctx_start + 1, ctx_end + 1)
                        )
                        matching_lines.append({
                            "line": i,
                            "content": line.rstrip(),
                            "context": context,
                        })

                if matching_lines:
                    rel_path = os.path.relpath(filepath, cc_path)
                    # Extract function/class names near matches
                    funcs = set()
                    for ml in matching_lines:
                        # Look backward for def/class
                        for j in range(max(0, ml["line"] - 30), ml["line"]):
                            if j < len(lines):
                                line_j = lines[j]
                                def_m = re.match(
                                    r"^\s*(def|class)\s+(\w+)", line_j
                                )
                                if def_m:
                                    funcs.add(f"{def_m.group(1)} {def_m.group(2)}")

                    results.append({
                        "file": rel_path,
                        "score": score,
                        "matches": len(matching_lines),
                        "related_functions": sorted(funcs)[:10],
                        "sample_matches": matching_lines[:5],
                    })

            except Exception:
                continue

    # Sort by relevance score
    results.sort(key=lambda r: r["score"], reverse=True)

    return {
        "module": module_name,
        "description": module_info["description"],
        "query": query,
        "results": results[:20],
        "total_files_scanned": len(results),
    }


def search_all(cc_path: str, query: str) -> dict:
    """Search all modules for the query."""
    all_results: dict[str, dict] = {}
    for module_name in MODULES:
        result = search_module(cc_path, module_name, query)
        if "error" not in result and result.get("results"):
            all_results[module_name] = result

    return {
        "query": query,
        "modules_with_results": list(all_results.keys()),
        "module_results": all_results,
    }


def format_results(data: dict) -> str:
    """Format search results into readable text."""
    lines = []
    lines.append("=" * 60)

    if "error" in data:
        lines.append(f"ERROR: {data['error']}")
        lines.append("=" * 60)
        return "\n".join(lines)

    # Single module result
    if "module" in data:
        lines.append(
            f"CONTROLCENTER REFERENCE: {data['module'].upper()}"
        )
        lines.append(f"Description: {data['description']}")
        lines.append(f"Query: {data['query']}")
        lines.append(f"Files with matches: {data['total_files_scanned']}")
        lines.append("=" * 60)
        lines.append("")

        for r in data.get("results", []):
            lines.append(f"--- {r['file']} (relevance: {r['score']}, matches: {r['matches']})")
            if r.get("related_functions"):
                lines.append(
                    f"    Related: {', '.join(r['related_functions'])}"
                )
            lines.append("")
            for m in r.get("sample_matches", [])[:3]:
                lines.append(f"  Line {m['line']}: {m['content'][:100]}")
            lines.append("")

    # Multi-module result
    elif "module_results" in data:
        lines.append("CONTROLCENTER REFERENCE: ALL MODULES")
        lines.append(f"Query: {data['query']}")
        lines.append(
            f"Modules with results: {', '.join(data['modules_with_results'])}"
        )
        lines.append("=" * 60)
        lines.append("")

        for mod_name, mod_result in data["module_results"].items():
            lines.append(
                f"[{mod_name}] — {mod_result['total_files_scanned']} files matched"
            )
            for r in mod_result.get("results", [])[:5]:
                lines.append(f"  {r['file']} (score: {r['score']})")
                if r.get("related_functions"):
                    lines.append(
                        f"    → {', '.join(r['related_functions'][:5])}"
                    )
            lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Search ControlCenter codebase for 3D Printer Expertging patterns"
    )
    parser.add_argument(
        "--query", "-q",
        default="",
        help="What to search for (e.g., 'websocket reconnect', 'error handling')",
    )
    parser.add_argument(
        "--module", "-m",
        choices=list(MODULES.keys()),
        help="Limit search to a specific module",
    )
    parser.add_argument(
        "--cc-path",
        help=f"Path to ControlCenter repo (default: {DEFAULT_CC_PATH})",
    )
    parser.add_argument(
        "--list-modules",
        action="store_true",
        help="List available modules and exit",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    if args.list_modules:
        print("CONTROLCENTER MODULES:")
        print("=" * 40)
        for name, info in MODULES.items():
            print(f"  {name}: {info['description']}")
            if info["key_files"]:
                print(f"    Key files: {', '.join(info['key_files'])}")
            print()
        return

    cc_path = args.cc_path or find_cc_path()
    if not cc_path:
        print(
            "ERROR: ControlCenter repo not found. Set CONTROLCENTER_PATH "
            "or use --cc-path.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not os.path.exists(cc_path):
        print(f"ERROR: Path does not exist: {cc_path}", file=sys.stderr)
        sys.exit(1)

    if args.module:
        data = search_module(cc_path, args.module, args.query)
    else:
        data = search_all(cc_path, args.query)

    if args.json:
        import json

        print(json.dumps(data, indent=2, default=str))
    else:
        print(format_results(data))


if __name__ == "__main__":
    main()
