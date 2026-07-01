#!/usr/bin/env python3
"""
Klipper Firmware Config Analyzer — Validates printer.cfg and included config
files for common issues: MCU setup, thermistor types, stepper configuration,
endstop/probe wiring, macro definitions, and SAVE_CONFIG corruption.

Usage:
    python firmware_analyzer.py --config-path /path/to/printer.cfg --check all
    python firmware_analyzer.py --check thermistor
    python firmware_analyzer.py --check mcu
    python firmware_analyzer.py --check macros --config-path ./printer.cfg
"""

import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional


# ── Common config paths ───────────────────────────────────────────────────────
COMMON_CONFIG_PATHS = [
    "/home/pi/printer_data/config/printer.cfg",
    "/home/pi/klipper_config/printer.cfg",
    "~/printer_data/config/printer.cfg",
    "~/klipper_config/printer.cfg",
    "printer.cfg",
]


def find_config_path() -> Optional[str]:
    """Auto-detect printer.cfg location."""
    for path in COMMON_CONFIG_PATHS:
        expanded = os.path.expanduser(path)
        if os.path.exists(expanded):
            return expanded
    return None


# ── Validation rules ──────────────────────────────────────────────────────────

# Known good thermistor types
KNOWN_THERMISTORS = {
    "EPCOS 100K B57560G104F",
    "ATC Semitec 104GT-2",
    "ATC Semitec 104NT-4-R025H42G",
    "Honeywell 100K 135-104LAG-J01",
    "NTC 100K MGB18-104F39050L32",
    "SliceEngineering 450",
    "PT100 INA826",
    "MAX31865",
    "MAX6675",
    "MAX31855",
    "MAX31856",
    "Generic 3950",
    "AD595",
    "AD597",
}

# Common stepper driver types
KNOWN_DRIVERS = {
    "tmc2208", "tmc2209", "tmc2130", "tmc5160",
    "tmc2225", "tmc2226", "tmc2240", "tmc2660",
    "a4988", "drv8825", "lv8729",
}

# Known MCU connection types
KNOWN_MCU_CONNECTIONS = {"serial", "can", "canbus", "usb"}

# Critical config issues that will definitely cause problems
CRITICAL_CHECKS = {
    "missing_mcu": r"\[mcu\]",
    "missing_printer": r"\[printer\]",
    "missing_stepper_x": r"\[stepper_x\]",
    "missing_stepper_y": r"\[stepper_y\]",
    "missing_stepper_z": r"\[stepper_z\]",
    "missing_extruder": r"\[extruder\]",
    "missing_heater_bed": r"\[heater_bed\]",
    "missing_virtual_sdcard": r"\[virtual_sdcard\]",
    "missing_display_status": r"\[display_status\]",
    "missing_pause_resume": r"\[pause_resume\]",
}


def parse_config(config_path: str) -> dict:
    """Parse printer.cfg and resolve all [include] directives."""
    if not os.path.exists(config_path):
        return {"error": f"Config file not found: {config_path}"}

    config_dir = os.path.dirname(os.path.abspath(config_path))
    sections: dict[str, list[dict]] = defaultdict(list)
    raw_lines: list[str] = []
    includes: list[str] = []
    parse_errors: list[dict] = []
    save_config_started = False

    def parse_file(filepath: str, depth: int = 0) -> None:
        nonlocal save_config_started
        if depth > 5:
            parse_errors.append({
                "file": filepath,
                "error": "Include depth exceeded (circular include?)",
            })
            return

        if not os.path.exists(filepath):
            parse_errors.append({
                "file": filepath,
                "error": "Included file not found",
            })
            return

        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                current_section = None
                current_options: dict[str, str] = {}

                for line_num, line in enumerate(f, 1):
                    stripped = line.strip()
                    raw_lines.append(stripped)

                    # Track SAVE_CONFIG block
                    if stripped.startswith("#*# <"):
                        save_config_started = True
                    if save_config_started:
                        continue

                    # Include directive
                    if stripped.startswith("[include "):
                        m = re.match(r"\[include\s+(.+?)\]", stripped)
                        if m:
                            inc_path = m.group(1).strip()
                            # Resolve relative to config dir
                            if not os.path.isabs(inc_path):
                                inc_path = os.path.join(
                                    config_dir, inc_path
                                )
                            includes.append(inc_path)
                            parse_file(inc_path, depth + 1)
                        continue

                    # Section header
                    if stripped.startswith("[") and stripped.endswith("]"):
                        # Save previous section
                        if current_section and current_options:
                            sections[current_section].append({
                                "file": filepath,
                                "line": line_num,
                                "options": dict(current_options),
                            })
                        current_section = stripped[1:-1].strip()
                        current_options = {}
                        continue

                    # Comment or empty
                    if not stripped or stripped.startswith("#"):
                        continue

                    # Key-value pair
                    if ":" in stripped:
                        key, _, val = stripped.partition(":")
                        key = key.strip()
                        val = val.strip()
                        # Remove inline comments
                        if "#" in val:
                            val = val[: val.index("#")].strip()
                        current_options[key] = val

                # Save last section
                if current_section and current_options:
                    sections[current_section].append({
                        "file": filepath,
                        "line": line_num,
                        "options": dict(current_options),
                    })

        except Exception as e:
            parse_errors.append({
                "file": filepath,
                "error": f"Parse error: {e}",
            })

    parse_file(config_path)

    return {
        "config_path": config_path,
        "sections": dict(sections),
        "includes": includes,
        "parse_errors": parse_errors,
        "line_count": len(raw_lines),
    }


def check_syntax(parsed: dict) -> list[str]:
    """Check for basic syntax and structural issues."""
    issues: list[str] = []
    sections = parsed.get("sections", {})

    for check_name, pattern in CRITICAL_CHECKS.items():
        section_name = check_name.replace("missing_", "")
        if section_name not in sections:
            issues.append(
                f"MISSING SECTION: [{section_name}] — this is required "
                f"for Klipper to function"
            )

    if parsed.get("parse_errors"):
        for err in parsed["parse_errors"]:
            issues.append(
                f"PARSE ERROR in {err['file']}: {err['error']}"
            )

    return issues


def check_mcu(parsed: dict) -> list[str]:
    """Check MCU configuration for common issues."""
    issues: list[str] = []
    mcu_sections = parsed.get("sections", {}).get("mcu", [])

    if not mcu_sections:
        issues.append("No [mcu] section found — printer cannot function")
        return issues

    for mcu in mcu_sections:
        opts = mcu.get("options", {})

        # Check for serial vs canbus
        serial = opts.get("serial")
        canbus_uuid = opts.get("canbus_uuid")

        if not serial and not canbus_uuid:
            issues.append(
                "MCU has neither 'serial' nor 'canbus_uuid' defined — "
                "Klipper won't know how to connect"
            )
        if serial:
            if not serial.startswith("/dev/"):
                issues.append(
                    f"MCU serial path '{serial}' doesn't start with "
                    f"/dev/ — may not be valid"
                )
        if canbus_uuid:
            if canbus_uuid == "XXXXXXXXXXX":
                issues.append(
                    "MCU canbus_uuid is placeholder 'XXXXXXXXXXX' — "
                    "run '~/klippy-env/bin/python ~/klipper/scripts/"
                    "canbus_query.py can0' to get actual UUID"
                )

        # Check baudrate for serial connections
        baudrate = opts.get("baudrate", "")
        if serial and not baudrate:
            issues.append(
                "MCU using serial but no baudrate specified. "
                "Default is 250000 — add 'baudrate: 250000' if unsure"
            )

    return issues


def check_thermistor(parsed: dict) -> list[str]:
    """Check thermistor/sensor configurations."""
    issues: list[str] = []
    heater_sections = [
        "extruder", "extruder1", "extruder2",
        "heater_bed", "heater_chamber",
    ]

    for section_name in heater_sections:
        for section in parsed.get("sections", {}).get(section_name, []):
            opts = section.get("options", {})
            sensor_type = opts.get("sensor_type", "")
            sensor_pin = opts.get("sensor_pin", "")
            max_temp = opts.get("max_temp", "")

            if not sensor_type:
                issues.append(
                    f"[{section_name}] has no sensor_type defined"
                )
            elif sensor_type not in KNOWN_THERMISTORS:
                # Not necessarily an error — custom thermistor tables exist
                issues.append(
                    f"[{section_name}] sensor_type '{sensor_type}' is "
                    f"not a standard thermistor name. If using a custom "
                    f"thermistor table, this is fine."
                )

            if not sensor_pin:
                issues.append(
                    f"[{section_name}] has no sensor_pin defined"
                )

            if max_temp:
                try:
                    max_val = float(max_temp)
                    if max_val < 200:
                        issues.append(
                            f"[{section_name}] max_temp is {max_val}°C "
                            f"— very low, check if this is intentional"
                        )
                    elif max_val > 500:
                        issues.append(
                            f"[{section_name}] max_temp is {max_val}°C "
                            f"— very high, ensure thermistor can handle it"
                        )
                except ValueError:
                    issues.append(
                        f"[{section_name}] max_temp '{max_temp}' is not "
                        f"a valid number"
                    )

    return issues


def check_stepper(parsed: dict) -> list[str]:
    """Check stepper motor configurations."""
    issues: list[str] = []
    stepper_sections = [
        k for k in parsed.get("sections", {}).keys()
        if k.startswith("stepper_")
    ]

    for section_name in stepper_sections:
        for section in parsed.get("sections", {}).get(section_name, []):
            opts = section.get("options", {})

            # Required pins
            for pin in ["step_pin", "dir_pin", "enable_pin"]:
                if pin not in opts:
                    issues.append(
                        f"[{section_name}] missing required '{pin}'"
                    )

            # Driver type
            driver_type = ""
            for tmcdrv in [k for k in opts if k.startswith("[tmc")]:
                pass  # TMC sections are separate
            # Check for common driver configs in the section
            for key in opts:
                if key.startswith("driver_"):
                    driver_type = opts.get("driver_type", "")
                    break

            # Check rotation_distance
            rotation = opts.get("rotation_distance", "")
            if rotation:
                try:
                    rot_val = float(rotation)
                    if rot_val <= 0:
                        issues.append(
                            f"[{section_name}] rotation_distance must "
                            f"be positive, got {rot_val}"
                        )
                except ValueError:
                    issues.append(
                        f"[{section_name}] rotation_distance '{rotation}'"
                        f" is not a valid number"
                    )
            elif not section_name.startswith("stepper_"):
                pass  # Some special steppers may not need it
            else:
                issues.append(
                    f"[{section_name}] missing rotation_distance"
                )

            # Check position_endstop vs position_max
            pos_endstop = opts.get("position_endstop", "")
            pos_max = opts.get("position_max", "")
            if pos_endstop and pos_max:
                try:
                    pe = float(pos_endstop)
                    pm = float(pos_max)
                    if pe > pm and section_name in (
                        "stepper_x", "stepper_y",
                    ):
                        issues.append(
                            f"[{section_name}] position_endstop ({pe}) "
                            f"> position_max ({pm}) — axis may not home "
                            f"correctly"
                        )
                except ValueError:
                    pass

    return issues


def check_endstop(parsed: dict) -> list[str]:
    """Check endstop configurations."""
    issues: list[str] = []
    stepper_sections = [
        k for k in parsed.get("sections", {}).keys()
        if k.startswith("stepper_")
    ]

    for section_name in stepper_sections:
        for section in parsed.get("sections", {}).get(section_name, []):
            opts = section.get("options", {})
            endstop_pin = opts.get("endstop_pin", "")

            if not endstop_pin and section_name not in (
                "stepper_x", "stepper_y", "stepper_z",
            ):
                continue  # Extruders don't need endstops

            if not endstop_pin:
                issues.append(
                    f"[{section_name}] missing endstop_pin"
                )
                continue

            # Check for common pull-up inversion mistakes
            if "^" not in endstop_pin and "!" not in endstop_pin:
                if section_name in ("stepper_x", "stepper_y"):
                    issues.append(
                        f"[{section_name}] endstop_pin '{endstop_pin}' "
                        f"has no pull-up (^) or invert (!) — may need "
                        f"^! for normally-closed endstops"
                    )

    return issues


def check_probe(parsed: dict) -> list[str]:
    """Check bed probe / bed_mesh configurations."""
    issues: list[str] = []
    sections = parsed.get("sections", {})

    probe_sections = sections.get("probe", [])
    bltouch_sections = sections.get("bltouch", [])
    bed_mesh_sections = sections.get("bed_mesh", [])

    for probe in probe_sections:
        opts = probe.get("options", {})
        if "z_offset" not in opts:
            issues.append(
                "[probe] missing z_offset — run PROBE_CALIBRATE"
            )
        if "pin" not in opts:
            issues.append("[probe] missing pin definition")

    for bltouch in bltouch_sections:
        opts = bltouch.get("options", {})
        for pin in ["sensor_pin", "control_pin"]:
            if pin not in opts:
                issues.append(f"[bltouch] missing {pin}")

    for bm in bed_mesh_sections:
        opts = bm.get("options", {})
        if "mesh_min" not in opts or "mesh_max" not in opts:
            issues.append(
                "[bed_mesh] missing mesh_min and/or mesh_max — "
                "define the probe area"
            )

    return issues


def check_macros(parsed: dict) -> list[str]:
    """Check G-code macros for common issues."""
    issues: list[str] = []
    sections = parsed.get("sections", {})

    gcode_macros = sections.get("gcode_macro", [])

    for macro in gcode_macros:
        opts = macro.get("options", {})
        gcode = opts.get("gcode", "")

        if not gcode:
            # gcode_macro with rename_existing is valid
            if "rename_existing" not in opts:
                issues.append(
                    f"gcode_macro has no 'gcode' body and no "
                    f"'rename_existing' — macro does nothing"
                )
            continue

        # Check for common dangerous patterns
        if "M112" in gcode:
            issues.append(
                "gcode_macro contains M112 (emergency stop) — this is "
                "usually not needed in macros"
            )

    # Check for duplicate macro names
    macro_names = [
        m.get("options", {}).get("name", "")
        for m in gcode_macros
        if m.get("options", {}).get("name")
    ]
    from collections import Counter
    duplicates = [
        name for name, count in Counter(macro_names).items() if count > 1
    ]
    for dup in duplicates:
        issues.append(
            f"Duplicate gcode_macro name: {dup}"
        )

    return issues


def check_includes(parsed: dict) -> list[str]:
    """Check included files for issues."""
    issues: list[str] = []
    includes = parsed.get("includes", [])

    for inc in includes:
        if not os.path.exists(inc):
            issues.append(f"Included file not found: {inc}")

    # Check if multiple printer configs are uncommented
    full_text = ""
    try:
        with open(parsed["config_path"], "r") as f:
            full_text = f.read()
    except Exception:
        pass

    # Count uncommented [include PRINTER_ lines
    printer_includes = re.findall(
        r"^\[include PRINTER_.+?\]", full_text, re.MULTILINE
    )
    if len(printer_includes) > 1:
        issues.append(
            f"Multiple printer config includes are active: "
            f"{printer_includes}. Only ONE should be uncommented."
        )

    return issues


def check_save_config(parsed: dict) -> list[str]:
    """Check SAVE_CONFIG block for corruption."""
    issues: list[str] = []
    try:
        with open(parsed["config_path"], "r") as f:
            content = f.read()
    except Exception:
        return issues

    if "#*#" not in content:
        return issues  # No SAVE_CONFIG block — normal for fresh installs

    save_config_lines = []
    in_save = False
    for line in content.split("\n"):
        if line.strip().startswith("#*# <"):
            in_save = True
        if in_save:
            save_config_lines.append(line)

    if not save_config_lines:
        return issues

    # Check for common corruption: comment markers inside values
    for line in save_config_lines:
        if line.count("#*#") > 1:
            issues.append(
                "SAVE_CONFIG block may be corrupted — multiple '#*#' "
                "markers on one line. Do NOT manually edit SAVE_CONFIG."
            )

    issues.append(
        f"SAVE_CONFIG block found ({len(save_config_lines)} lines). "
        f"Do NOT manually edit this section — it's auto-generated."
    )

    return issues


# ── Check registry ────────────────────────────────────────────────────────────
CHECKS = {
    "syntax": check_syntax,
    "mcu": check_mcu,
    "thermistor": check_thermistor,
    "stepper": check_stepper,
    "endstop": check_endstop,
    "probe": check_probe,
    "macros": check_macros,
    "includes": check_includes,
    "save_config": check_save_config,
}


def format_report(parsed: dict, results: dict) -> str:
    """Format analysis results into a readable report."""
    lines = []
    lines.append("=" * 60)
    lines.append("FIRMWARE CONFIG ANALYSIS REPORT")
    lines.append("=" * 60)
    lines.append(f"Config file: {parsed['config_path']}")
    lines.append(f"Lines parsed: {parsed['line_count']}")
    lines.append(
        f"Included files: {len(parsed.get('includes', []))}"
    )
    lines.append(
        f"Sections found: {len(parsed.get('sections', {}))}"
    )
    lines.append("")

    total_issues = sum(len(v) for v in results.values())
    lines.append(f"--- TOTAL ISSUES FOUND: {total_issues} ---")
    lines.append("")

    for check_name in CHECKS:
        check_results = results.get(check_name, [])
        if check_results:
            lines.append(f"[{check_name.upper()}] — {len(check_results)} issue(s):")
            for issue in check_results:
                lines.append(f"  • {issue}")
            lines.append("")
        else:
            lines.append(f"[{check_name.upper()}] ✓ No issues found")
            lines.append("")

    lines.append("=" * 60)

    if total_issues > 0:
        lines.append("")
        lines.append("NEXT STEPS:")
        lines.append(
            "1. Fix CRITICAL issues first (missing sections, MCU setup)"
        )
        lines.append(
            "2. Address warnings about sensor types and pin definitions"
        )
        lines.append(
            "3. Run 'RESTART' in Klipper after making changes"
        )
        lines.append(
            "4. Check klippy.log for any remaining errors after restart"
        )

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Validate Klipper printer.cfg for common issues"
    )
    parser.add_argument(
        "--config-path",
        help="Path to printer.cfg (auto-detected if omitted)",
    )
    parser.add_argument(
        "--check",
        default="all",
        choices=["all"] + list(CHECKS.keys()),
        help="Which check to run (default: all)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of formatted report",
    )
    args = parser.parse_args()

    config_path = args.config_path or find_config_path()
    if not config_path:
        print(
            "ERROR: Could not auto-detect printer.cfg. "
            "Provide --config-path.",
            file=sys.stderr,
        )
        sys.exit(1)

    parsed = parse_config(config_path)
    if "error" in parsed:
        print(f"ERROR: {parsed['error']}", file=sys.stderr)
        sys.exit(1)

    # Run selected checks
    results: dict[str, list[str]] = {}
    if args.check == "all":
        for name, func in CHECKS.items():
            results[name] = func(parsed)
    else:
        results[args.check] = CHECKS[args.check](parsed)

    if args.json:
        import json

        output = {
            "config_path": parsed["config_path"],
            "sections_found": list(parsed["sections"].keys()),
            "includes": parsed["includes"],
            "parse_errors": parsed["parse_errors"],
            "issues": results,
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        print(format_report(parsed, results))


if __name__ == "__main__":
    main()
