#!/usr/bin/env python3
"""
Klipper Log Parser — Parses klippy.log for errors, warnings, shutdown
reasons, timing anomalies, and MCU communication issues.

Usage:
    python klipper_log_parser.py --log-path /path/to/klippy.log --days 3
    python klipper_log_parser.py --days 1  (auto-detect log path)
    python klipper_log_parser.py --summary  (quick summary only)
"""

import argparse
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# ── Common log paths ──────────────────────────────────────────────────────────
COMMON_LOG_PATHS = [
    "/home/pi/klipper_logs/klippy.log",
    "/tmp/klippy.log",
    "/var/log/klippy.log",
    "~/klipper_logs/klippy.log",
    "~/printer_data/logs/klippy.log",
]


def find_log_path() -> Optional[str]:
    """Try to auto-detect the klippy.log path."""
    for path in COMMON_LOG_PATHS:
        expanded = os.path.expanduser(path)
        if os.path.exists(expanded):
            return expanded
    return None


# ── Error pattern definitions ─────────────────────────────────────────────────
ERROR_PATTERNS = {
    "MCU_shutdown": re.compile(
        r"MCU '(\w+)' shutdown: (.+)", re.IGNORECASE
    ),
    "heater_error": re.compile(
        r"Heater (\w+) not heating at expected rate", re.IGNORECASE
    ),
    "ADC_out_of_range": re.compile(
        r"ADC out of range", re.IGNORECASE
    ),
    "thermistor_error": re.compile(
        r"(thermistor|temperature)\s*(sensor)?\s*(error|fault|disconnect|open|short)",
        re.IGNORECASE,
    ),
    "lost_communication": re.compile(
        r"Lost communication with MCU '(\w+)'", re.IGNORECASE
    ),
    "timer_too_close": re.compile(
        r"Timer too close", re.IGNORECASE
    ),
    "move_exceeds_extrusion": re.compile(
        r"Move exceeds maximum extrusion", re.IGNORECASE
    ),
    "unable_to_open_serial": re.compile(
        r"Unable to open (serial )?port", re.IGNORECASE
    ),
    "klipper_shutdown": re.compile(
        r"(?:Klipper|Firmware) shutdown:?\s*(.+)", re.IGNORECASE
    ),
    "connection_error": re.compile(
        r"(connection|connect)\s*(error|failed|timeout|refused|reset)",
        re.IGNORECASE,
    ),
    "config_error": re.compile(
        r"(config|option|section)\s*(error|unknown|invalid|missing)",
        re.IGNORECASE,
    ),
    "stepper_error": re.compile(
        r"(stepper|motor)\s*(error|overload|stall|overheat)",
        re.IGNORECASE,
    ),
    "probe_error": re.compile(
        r"(probe|bltouch|bed_mesh)\s*(error|failed|out of range)",
        re.IGNORECASE,
    ),
    "filament_error": re.compile(
        r"(filament|runout|jam)\s*(error|sensor|detected)",
        re.IGNORECASE,
    ),
    "gcode_error": re.compile(
        r"(Unknown command|Malformed command|gcode.*error)",
        re.IGNORECASE,
    ),
}

WARNING_PATTERNS = {
    "retry": re.compile(r"retry|retries|retrying", re.IGNORECASE),
    "timeout": re.compile(r"timeout|timed ?out", re.IGNORECASE),
    "deprecated": re.compile(r"deprecated", re.IGNORECASE),
    "unknown_command": re.compile(r"Unknown command", re.IGNORECASE),
    "resend": re.compile(r"(resend|Resend request)", re.IGNORECASE),
    "buffer_overrun": re.compile(r"buffer overrun", re.IGNORECASE),
    "stats_warning": re.compile(
        r"Stats (?:\d+\.\d+): (?!.*(?:bytes_retransmit=0|bytes_invalid=0))",
        re.IGNORECASE,
    ),
}


def parse_timestamp(line: str) -> Optional[datetime]:
    """Extract timestamp from a klippy.log line. Handles common formats."""
    patterns = [
        (re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[.,]\d+)"), "%Y-%m-%d %H:%M:%S"),
        (re.compile(r"^(\d{2}:\d{2}:\d{2})"), "%H:%M:%S"),
        (re.compile(r"^Stats (\d+\.\d+)"), None),  # epoch float
    ]
    for pat, fmt in patterns:
        m = pat.match(line)
        if m:
            ts_str = m.group(1)
            if fmt:
                ts_str = ts_str.replace(",", ".")
                try:
                    return datetime.strptime(ts_str, fmt)
                except ValueError:
                    return None
            else:
                try:
                    return datetime.fromtimestamp(float(ts_str))
                except (ValueError, OSError):
                    return None
    return None


def is_within_days(line: str, cutoff: datetime) -> bool:
    """Check if a log line's timestamp is within the cutoff window."""
    ts = parse_timestamp(line)
    if ts is None:
        return True  # Include lines without timestamps
    return ts >= cutoff


def parse_log(
    log_path: str, days: int = 1, summary_only: bool = False
) -> dict:
    """Parse klippy.log and return structured findings."""
    if not os.path.exists(log_path):
        return {"error": f"Log file not found: {log_path}"}

    cutoff = datetime.now() - timedelta(days=days)

    errors: list[dict] = []
    warnings: list[dict] = []
    shutdowns: list[str] = []
    mcu_events: list[dict] = []
    stats: list[dict] = []
    line_count = 0
    error_count = 0

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line_num, line in enumerate(f, 1):
                line_count += 1
                if not is_within_days(line, cutoff):
                    continue

                # Check for errors
                for category, pattern in ERROR_PATTERNS.items():
                    m = pattern.search(line)
                    if m:
                        error_count += 1
                        entry = {
                            "line": line_num,
                            "category": category,
                            "message": line.strip(),
                        }
                        if m.groups():
                            entry["details"] = m.groups()
                        errors.append(entry)

                        # Track shutdowns separately
                        if category == "klipper_shutdown":
                            shutdowns.append(line.strip())
                        # Track MCU events
                        if category in (
                            "MCU_shutdown",
                            "lost_communication",
                        ):
                            mcu_events.append(entry)
                        break  # One category per line

                # Check for warnings (only if not already flagged as error)
                if not summary_only:
                    for category, pattern in WARNING_PATTERNS.items():
                        if pattern.search(line):
                            warnings.append({
                                "line": line_num,
                                "category": category,
                                "message": line.strip(),
                            })
                            break

                # Collect Stats lines for timing analysis
                if line.startswith("Stats "):
                    stats.append({"line": line_num, "message": line.strip()})

    except Exception as e:
        return {"error": f"Failed to read log: {e}"}

    # ── Analyze stats for timing issues ───────────────────────────────────────
    timing_issues = []
    for stat in stats:
        msg = stat["message"]
        # Check for bytes_retransmit
        retransmit_m = re.search(r"bytes_retransmit=(\d+)", msg)
        if retransmit_m and int(retransmit_m.group(1)) > 0:
            timing_issues.append({
                "line": stat["line"],
                "issue": "bytes_retransmit",
                "value": retransmit_m.group(1),
            })
        # Check for bytes_invalid
        invalid_m = re.search(r"bytes_invalid=(\d+)", msg)
        if invalid_m and int(invalid_m.group(1)) > 0:
            timing_issues.append({
                "line": stat["line"],
                "issue": "bytes_invalid",
                "value": invalid_m.group(1),
            })

    # ── Error frequency analysis ──────────────────────────────────────────────
    error_freq = Counter(e["category"] for e in errors)

    return {
        "log_path": log_path,
        "days_scanned": days,
        "total_lines": line_count,
        "error_count": error_count,
        "warning_count": len(warnings),
        "shutdown_count": len(shutdowns),
        "error_frequency": dict(error_freq.most_common()),
        "errors": errors[:100] if summary_only else errors,
        "warnings": [] if summary_only else warnings[:50],
        "shutdowns": shutdowns[-10:],
        "mcu_events": mcu_events[-20:],
        "timing_issues": timing_issues[-50:],
    }


def format_report(data: dict) -> str:
    """Format parsed log data into a readable report."""
    if "error" in data:
        return f"ERROR: {data['error']}"

    lines = []
    lines.append("=" * 60)
    lines.append("KLIPPER LOG ANALYSIS REPORT")
    lines.append("=" * 60)
    lines.append(f"Log file: {data['log_path']}")
    lines.append(f"Period: last {data['days_scanned']} day(s)")
    lines.append(f"Lines scanned: {data['total_lines']}")
    lines.append("")

    # ── Summary ───────────────────────────────────────────────────────────────
    lines.append("--- SUMMARY ---")
    lines.append(f"Total errors: {data['error_count']}")
    lines.append(f"Total warnings: {data['warning_count']}")
    lines.append(f"Shutdown events: {data['shutdown_count']}")
    lines.append(f"MCU communication events: {len(data['mcu_events'])}")
    lines.append(f"Timing issues (bytes_retransmit/invalid): {len(data['timing_issues'])}")
    lines.append("")

    # ── Error breakdown ───────────────────────────────────────────────────────
    if data["error_frequency"]:
        lines.append("--- ERROR BREAKDOWN ---")
        for cat, count in data["error_frequency"].items():
            lines.append(f"  {cat}: {count}")
        lines.append("")

    # ── Recent shutdowns ──────────────────────────────────────────────────────
    if data["shutdowns"]:
        lines.append("--- RECENT SHUTDOWNS (last 10) ---")
        for s in data["shutdowns"]:
            lines.append(f"  {s[:120]}")
        lines.append("")

    # ── MCU events ────────────────────────────────────────────────────────────
    if data["mcu_events"]:
        lines.append("--- MCU COMMUNICATION EVENTS (last 20) ---")
        for e in data["mcu_events"]:
            lines.append(f"  Line {e['line']}: [{e['category']}] {e['message'][:100]}")
        lines.append("")

    # ── Timing issues ─────────────────────────────────────────────────────────
    if data["timing_issues"]:
        lines.append("--- TIMING ISSUES ---")
        lines.append("  (bytes_retransmit > 0 indicates USB/communication problems)")
        for t in data["timing_issues"]:
            lines.append(
                f"  Line {t['line']}: {t['issue']}={t['value']}"
            )
        lines.append("")

    # ── Recent errors ─────────────────────────────────────────────────────────
    if data["errors"]:
        lines.append(f"--- RECENT ERRORS (showing up to 50) ---")
        for e in data["errors"][:50]:
            lines.append(f"  Line {e['line']}: [{e['category']}] {e['message'][:130]}")
        lines.append("")

    # ── Diagnosis hints ───────────────────────────────────────────────────────
    lines.append("--- DIAGNOSIS HINTS ---")
    hints = []
    freq = data["error_frequency"]

    if "lost_communication" in freq or "connection_error" in freq:
        hints.append(
            "• MCU communication issues detected. Check USB cable, power "
            "supply, and try a different USB port. Consider adding a "
            "powered USB hub if using Raspberry Pi."
        )
    if "heater_error" in freq:
        hints.append(
            "• Heater errors detected. Check heater cartridge resistance "
            "(should be ~3-5Ω for 40W), verify thermistor is seated "
            "properly, and re-run PID tuning."
        )
    if "ADC_out_of_range" in freq or "thermistor_error" in freq:
        hints.append(
            "• Thermistor/sensor errors detected. Check wiring for shorts "
            "or breaks. Verify sensor_type in printer.cfg matches the "
            "actual thermistor (common: ATC Semitec 104GT-2 = 'ATC "
            "Semitec 104GT-2')."
        )
    if "timer_too_close" in freq:
        hints.append(
            "• Timer-too-close errors. Reduce microsteps, increase "
            "stepper pulse duration, or lower printing speed."
        )
    if "config_error" in freq:
        hints.append(
            "• Configuration errors detected. Run "
            "analyze_firmware_config.py to validate printer.cfg."
        )
    if data["timing_issues"]:
        hints.append(
            "• USB communication timing issues (bytes_retransmit > 0). "
            "This often indicates USB bandwidth saturation. Reduce "
            "microsteps, lower baudrate if using serial, or switch to "
            "CANbus for multi-MCU setups."
        )

    if hints:
        lines.extend(hints)
    else:
        lines.append("  No specific diagnosis hints generated. Review errors above.")

    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Parse Klipper firmware logs for errors and anomalies"
    )
    parser.add_argument(
        "--log-path",
        help="Path to klippy.log (auto-detected if omitted)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="How many days of logs to analyze (default: 1)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Show only summary, not full error list",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of formatted report",
    )
    args = parser.parse_args()

    log_path = args.log_path or find_log_path()
    if not log_path:
        print(
            "ERROR: Could not auto-detect klippy.log. Provide --log-path.",
            file=sys.stderr,
        )
        sys.exit(1)

    data = parse_log(log_path, args.days, args.summary)

    if args.json:
        import json

        print(json.dumps(data, indent=2, default=str))
    else:
        print(format_report(data))

    if "error" in data:
        sys.exit(1)


if __name__ == "__main__":
    main()
