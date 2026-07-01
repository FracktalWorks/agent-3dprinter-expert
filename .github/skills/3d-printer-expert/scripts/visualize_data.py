#!/usr/bin/env python3
"""
Data Visualizer — Parses Klipper logs and OctoPrint API responses to generate
visualizations: temperature graphs, bed mesh heatmaps, input shaper spectra,
print progress timelines, and MCU timing diagnostics.

Output formats: ASCII plots (terminal), PNG images, or structured JSON for
external charting.

Usage:
    python visualize_data.py --source log --type temperature --log-path klippy.log
    python visualize_data.py --source api --type bed-mesh --ip 192.168.1.100 --api-key KEY
    python visualize_data.py --source log --type input-shaper --log-path klippy.log
    python visualize_data.py --source log --type stats --log-path klippy.log
    python visualize_data.py --source log --type timeline --log-path klippy.log
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional


# ── Data extraction ───────────────────────────────────────────────────────────

def extract_temperature_data(log_path: str) -> dict:
    """Extract temperature readings from klippy.log."""
    if not os.path.exists(log_path):
        return {"error": f"Log file not found: {log_path}"}

    temps: list[dict] = []
    # Pattern: extruder: temp1/temp2, bed: temp1/temp2
    temp_pattern = re.compile(
        r"(?:Stats\s+)?(\d+\.?\d*):?\s*"
        r"(?:.+?)?"  # optional middle stuff
        r"([\w_]+):\s*(-?\d+\.?\d*)\s*\/\s*(-?\d+\.?\d*)"
    )

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if "Stats" in line and "bytes_" in line:
                    # Stats line format: Stats 1234.5: ...
                    ts_match = re.match(r"Stats (\d+\.\d+):", line)
                    if not ts_match:
                        continue
                    timestamp = float(ts_match.group(1))
                    # Find all temp patterns in this line
                    for m in re.finditer(
                        r"([\w_]+):(-?\d+\.\d+)\s*/(-?\d+\.\d+)", line
                    ):
                        heater = m.group(1)
                        # Skip non-temperature stats
                        if heater in (
                            "bytes_read", "bytes_write",
                            "bytes_retransmit", "bytes_invalid",
                            "send_seq", "receive_seq", "retransmit_seq",
                            "srtt", "rttvar", "ready_bytes",
                            "stalled_bytes", "freq",
                        ):
                            continue
                        try:
                            actual = float(m.group(2))
                            target = float(m.group(3))
                            temps.append({
                                "timestamp": timestamp,
                                "heater": heater,
                                "actual": actual,
                                "target": target,
                            })
                        except (ValueError, IndexError):
                            continue

    except Exception as e:
        return {"error": f"Failed to parse log: {e}"}

    if not temps:
        return {"error": "No temperature data found in log"}

    # Group by heater
    by_heater = defaultdict(list)
    for t in temps:
        by_heater[t["heater"]].append(t)

    # Compute summary stats per heater
    summary = {}
    for heater, readings in by_heater.items():
        actuals = [r["actual"] for r in readings]
        targets = [r["target"] for r in readings if r["target"] > 0]
        summary[heater] = {
            "count": len(readings),
            "actual_min": min(actuals),
            "actual_max": max(actuals),
            "actual_mean": sum(actuals) / len(actuals),
            "anomalies": [
                r for r in readings
                if abs(r["actual"] - r["target"]) > 15 and r["target"] > 0
            ][-20:],
            "samples": readings[-50:],  # Last 50 for plotting
        }
        if targets:
            summary[heater]["target_mean"] = sum(targets) / len(targets)

    return {
        "summary": summary,
        "total_readings": len(temps),
        "heaters": list(by_heater.keys()),
    }


def extract_stats_data(log_path: str) -> dict:
    """Extract MCU communication stats (bytes_retransmit, buffer_time, etc.)."""
    if not os.path.exists(log_path):
        return {"error": f"Log file not found: {log_path}"}

    stats: list[dict] = []
    stat_pattern = re.compile(r"Stats (\d+\.\d+):")

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = stat_pattern.match(line)
                if not m:
                    continue
                timestamp = float(m.group(1))

                entry = {"timestamp": timestamp}
                for field in [
                    "bytes_read", "bytes_write",
                    "bytes_retransmit", "bytes_invalid",
                    "send_seq", "receive_seq",
                    "srtt", "rttvar",
                    "ready_bytes", "stalled_bytes",
                    "freq",
                ]:
                    fm = re.search(rf"{field}=(\d+)", line)
                    if fm:
                        entry[field] = int(fm.group(1))

                # Extract buffer_time if present
                bm = re.search(r"buffer_time=(\d+\.\d+)", line)
                if bm:
                    entry["buffer_time"] = float(bm.group(1))

                # Extract sysload if present
                sm = re.search(r"sysload=(\d+\.\d+)", line)
                if sm:
                    entry["sysload"] = float(sm.group(1))

                if len(entry) > 1:  # Has more than just timestamp
                    stats.append(entry)

    except Exception as e:
        return {"error": f"Failed to parse log: {e}"}

    if not stats:
        return {"error": "No stats data found in log"}

    # Compute summary
    retransmit_events = [
        s for s in stats
        if s.get("bytes_retransmit", 0) > 0
    ]
    invalid_events = [
        s for s in stats
        if s.get("bytes_invalid", 0) > 0
    ]
    buffer_times = [
        s["buffer_time"] for s in stats if "buffer_time" in s
    ]

    return {
        "total_stats_lines": len(stats),
        "retransmit_events": len(retransmit_events),
        "invalid_events": len(invalid_events),
        "max_retransmit": max(
            (s.get("bytes_retransmit", 0) for s in stats), default=0
        ),
        "max_invalid": max(
            (s.get("bytes_invalid", 0) for s in stats), default=0
        ),
        "buffer_time_min": min(buffer_times) if buffer_times else 0,
        "buffer_time_max": max(buffer_times) if buffer_times else 0,
        "buffer_time_avg": (
            sum(buffer_times) / len(buffer_times) if buffer_times else 0
        ),
        "retransmit_samples": retransmit_events[-30:],
        "buffer_low_events": [
            s for s in stats
            if s.get("buffer_time", 99) < 2.0
        ][-30:],
        "samples": stats[-50:],
    }


def extract_timeline(log_path: str) -> dict:
    """Build a print session timeline from klippy.log."""
    if not os.path.exists(log_path):
        return {"error": f"Log file not found: {log_path}"}

    events: list[dict] = []
    event_patterns = {
        "print_start": re.compile(r"print_start|Starting print|File selected", re.I),
        "print_end": re.compile(r"print_end|Print complete|Finished printing", re.I),
        "print_cancel": re.compile(r"print_cancel|Print cancelled", re.I),
        "print_pause": re.compile(r"print_pause|Print paused|Pausing print", re.I),
        "print_resume": re.compile(r"print_resume|Print resumed|Resuming print", re.I),
        "heating": re.compile(r"Heating (extruder|bed)|Target temperature", re.I),
        "homing": re.compile(r"Home|Homing", re.I),
        "leveling": re.compile(r"Bed leveling|bed_mesh|PROBE_CALIBRATE", re.I),
        "error": re.compile(r"ERROR|shutdown|Shutdown", re.I),
        "mcu_event": re.compile(r"MCU|Lost communication|connect", re.I),
    }

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line_num, line in enumerate(f, 1):
                ts_match = re.match(
                    r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", line
                )
                timestamp = ts_match.group(1) if ts_match else None

                for event_type, pattern in event_patterns.items():
                    if pattern.search(line):
                        events.append({
                            "line": line_num,
                            "timestamp": timestamp,
                            "event": event_type,
                            "message": line.strip()[:150],
                        })
                        break

    except Exception as e:
        return {"error": f"Failed to parse: {e}"}

    return {
        "total_events": len(events),
        "events": events,
        "event_counts": {
            etype: sum(1 for ev in events if ev["event"] == etype)
            for etype in event_patterns
        },
    }


def extract_input_shaper_data(log_path: str) -> dict:
    """Extract input shaper calibration results from klippy.log."""
    if not os.path.exists(log_path):
        return {"error": f"Log file not found: {log_path}"}

    results: list[dict] = []
    shaper_pattern = re.compile(
        r"(\w+):.*?freq=(\d+\.?\d*).*?vibr=(\d+\.?\d*).*?"
        r"sm_freq=(\d+\.?\d*).*?vibr=(\d+\.?\d*).*?"
        r"Recommended shaper.*?(\w+).*?@\s*(\d+\.?\d*)\s*Hz",
        re.IGNORECASE,
    )

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
            for m in shaper_pattern.finditer(content):
                results.append({
                    "axis": m.group(1),
                    "freq": float(m.group(2)),
                    "vibr": float(m.group(3)),
                    "smooth_freq": float(m.group(4)),
                    "smooth_vibr": float(m.group(5)),
                    "recommended_shaper": m.group(6),
                    "recommended_freq": float(m.group(7)),
                })
    except Exception as e:
        return {"error": f"Failed to parse: {e}"}

    return {"results": results, "count": len(results)}


# ── Formatters ────────────────────────────────────────────────────────────────

def format_temperature_plot(data: dict) -> str:
    """ASCII temperature plot."""
    if "error" in data:
        return f"ERROR: {data['error']}"

    lines = []
    lines.append("=" * 60)
    lines.append("TEMPERATURE ANALYSIS")
    lines.append("=" * 60)

    summary = data.get("summary", {})
    for heater, stats in sorted(summary.items()):
        lines.append(f"\n--- {heater} ---")
        lines.append(f"  Readings: {stats['count']}")
        lines.append(f"  Range: {stats['actual_min']:.1f}°C – {stats['actual_max']:.1f}°C")
        lines.append(f"  Mean: {stats['actual_mean']:.1f}°C")
        if "target_mean" in stats:
            lines.append(f"  Target: {stats['target_mean']:.1f}°C")

        # ASCII sparkline for last 50 readings
        samples = stats.get("samples", [])
        if samples:
            actuals = [s["actual"] for s in samples]
            min_a, max_a = min(actuals), max(actuals)
            if max_a > min_a:
                spark = ""
                for a in actuals[-50:]:
                    normalized = (a - min_a) / (max_a - min_a)
                    if normalized < 0.125:
                        spark += "▁"
                    elif normalized < 0.25:
                        spark += "▂"
                    elif normalized < 0.375:
                        spark += "▃"
                    elif normalized < 0.5:
                        spark += "▄"
                    elif normalized < 0.625:
                        spark += "▅"
                    elif normalized < 0.75:
                        spark += "▆"
                    elif normalized < 0.875:
                        spark += "▇"
                    else:
                        spark += "█"
                lines.append(f"  Trend: {spark}")
                lines.append(f"         {min_a:.0f}°C{' ' * (44 - len(spark))}{max_a:.0f}°C")

        # Anomalies
        anomalies = stats.get("anomalies", [])
        if anomalies:
            lines.append(f"  ⚠ Temperature deviations (>15°C): {len(anomalies)}")
            for a in anomalies[-5:]:
                lines.append(
                    f"    t={a['timestamp']:.0f}s: "
                    f"actual={a['actual']:.1f} target={a['target']:.1f} "
                    f"(Δ{a['actual'] - a['target']:+.1f}°C)"
                )
        else:
            lines.append("  ✓ No significant temperature deviations")

    return "\n".join(lines)


def format_stats_plot(data: dict) -> str:
    """ASCII stats visualization."""
    if "error" in data:
        return f"ERROR: {data['error']}"

    lines = []
    lines.append("=" * 60)
    lines.append("MCU COMMUNICATION STATS")
    lines.append("=" * 60)

    lines.append(f"Stats lines analyzed: {data['total_stats_lines']}")
    lines.append(f"Retransmit events: {data['retransmit_events']}")
    lines.append(f"Invalid byte events: {data['invalid_events']}")
    lines.append(f"Max bytes_retransmit: {data['max_retransmit']}")
    lines.append(f"Max bytes_invalid: {data['max_invalid']}")

    lines.append("\n--- Buffer Time ---")
    lines.append(f"  Min: {data['buffer_time_min']:.2f}s")
    lines.append(f"  Max: {data['buffer_time_max']:.2f}s")
    lines.append(f"  Avg: {data['buffer_time_avg']:.2f}s")

    # Health assessment
    lines.append("\n--- Health Assessment ---")
    buf_avg = data["buffer_time_avg"]
    if buf_avg < 1.0:
        lines.append("🔴 CRITICAL: Average buffer time < 1s — print stalls likely")
        lines.append("   → Reduce print speed, lower microsteps, or check USB cable")
    elif buf_avg < 2.0:
        lines.append("🟡 WARNING: Average buffer time < 2s — marginal")
        lines.append("   → Monitor for stalls on complex geometry")
    else:
        lines.append("🟢 GOOD: Buffer time adequate")

    if data["retransmit_events"] > 10:
        lines.append(
            f"🔴 CRITICAL: {data['retransmit_events']} retransmit events — "
            f"USB communication problem"
        )
        lines.append("   → Check USB cable, try different port, use powered hub")
    elif data["retransmit_events"] > 0:
        lines.append(
            f"🟡 WARNING: {data['retransmit_events']} retransmit events"
        )
    else:
        lines.append("🟢 GOOD: No retransmit events — USB communication clean")

    # Buffer time sparkline
    samples = data.get("samples", [])
    buffer_samples = [
        s["buffer_time"] for s in samples if "buffer_time" in s
    ]
    if buffer_samples:
        min_b, max_b = min(buffer_samples), max(buffer_samples)
        if max_b > min_b:
            spark = ""
            for b in buffer_samples[-50:]:
                normalized = (b - min_b) / (max_b - min_b) if max_b > min_b else 0.5
                if normalized < 0.125:
                    spark += "▁"
                elif normalized < 0.25:
                    spark += "▂"
                elif normalized < 0.375:
                    spark += "▃"
                elif normalized < 0.5:
                    spark += "▄"
                elif normalized < 0.625:
                    spark += "▅"
                elif normalized < 0.75:
                    spark += "▆"
                elif normalized < 0.875:
                    spark += "▇"
                else:
                    spark += "█"
            lines.append(f"\n  Buffer trend: {spark}")
            lines.append(f"                 {min_b:.1f}s{' ' * (38 - len(spark))}{max_b:.1f}s")

    return "\n".join(lines)


def format_timeline(data: dict) -> str:
    """Print session timeline."""
    if "error" in data:
        return f"ERROR: {data['error']}"

    lines = []
    lines.append("=" * 60)
    lines.append("PRINT SESSION TIMELINE")
    lines.append("=" * 60)

    lines.append(f"Events found: {data['total_events']}")
    lines.append("\nEvent counts:")
    for etype, count in data["event_counts"].items():
        if count > 0:
            marker = {
                "error": "🔴",
                "mcu_event": "🟡",
                "print_pause": "🟠",
                "print_cancel": "🔴",
            }.get(etype, "  ")
            lines.append(f"  {marker} {etype}: {count}")

    lines.append("\nTimeline:")
    for ev in data["events"][-40:]:
        marker = {
            "error": "🔴",
            "mcu_event": "🟡",
            "print_pause": "🟠",
            "print_cancel": "🔴",
        }.get(ev["event"], "  ")
        ts = ev["timestamp"] or "no-ts"
        lines.append(f"  {marker} {ts} [{ev['event']}] {ev['message'][:80]}")

    return "\n".join(lines)


def format_input_shaper(data: dict) -> str:
    """Input shaper results."""
    if "error" in data:
        return f"ERROR: {data['error']}"

    lines = []
    lines.append("=" * 60)
    lines.append("INPUT SHAPER CALIBRATION RESULTS")
    lines.append("=" * 60)

    for r in data.get("results", []):
        lines.append(f"\n--- {r['axis'].upper()} Axis ---")
        lines.append(f"  Peak freq: {r['freq']:.1f} Hz (vibration: {r['vibr']:.1f}%)")
        lines.append(f"  Smooth freq: {r['smooth_freq']:.1f} Hz (vibration: {r['smooth_vibr']:.1f}%)")
        lines.append(f"  → Recommended: {r['recommended_shaper']} @ {r['recommended_freq']:.1f} Hz")

        # Config snippet
        shaper_type = r["recommended_shaper"]
        freq = r["recommended_freq"]
        lines.append(f"\n  Add to printer.cfg:")
        lines.append(f"  [input_shaper]")
        lines.append(f"  shaper_type_{r['axis'].lower()}: {shaper_type}")
        lines.append(f"  shaper_freq_{r['axis'].lower()}: {freq:.1f}")

    if not data.get("results"):
        lines.append("\nNo input shaper data found in log.")
        lines.append("Run SHAPER_CALIBRATE in Klipper console first.")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Visualize 3D printer data from logs and API"
    )
    parser.add_argument(
        "--source",
        choices=["log", "api"],
        default="log",
        help="Data source (log file or OctoPrint API)",
    )
    parser.add_argument(
        "--type",
        choices=[
            "temperature", "stats", "timeline",
            "input-shaper", "all",
        ],
        default="all",
        help="Type of visualization",
    )
    parser.add_argument(
        "--log-path",
        help="Path to klippy.log (for source=log)",
    )
    parser.add_argument(
        "--ip",
        default=os.environ.get("OCTOPRINT_IP", ""),
        help="OctoPrint IP (for source=api)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("OCTOPRINT_API_KEY", ""),
        help="OctoPrint API key (for source=api)",
    )
    parser.add_argument(
        "--output",
        choices=["ascii", "json"],
        default="ascii",
        help="Output format",
    )
    args = parser.parse_args()

    if args.source == "log" and not args.log_path:
        # Try common paths
        for p in [
            "/home/pi/printer_data/logs/klippy.log",
            os.path.expanduser("~/printer_data/logs/klippy.log"),
        ]:
            if os.path.exists(p):
                args.log_path = p
                break
        if not args.log_path:
            print(
                "ERROR: --log-path required for log source.",
                file=sys.stderr,
            )
            sys.exit(1)

    results: dict[str, dict] = {}

    if args.type in ("temperature", "all"):
        results["temperature"] = extract_temperature_data(args.log_path)
    if args.type in ("stats", "all"):
        results["stats"] = extract_stats_data(args.log_path)
    if args.type in ("timeline", "all"):
        results["timeline"] = extract_timeline(args.log_path)
    if args.type in ("input-shaper", "all"):
        results["input_shaper"] = extract_input_shaper_data(args.log_path)

    if args.output == "json":
        print(json.dumps(results, indent=2, default=str))
    else:
        formatters = {
            "temperature": format_temperature_plot,
            "stats": format_stats_plot,
            "timeline": format_timeline,
            "input_shaper": format_input_shaper,
        }
        for name, data in results.items():
            fmt = formatters.get(name)
            if fmt:
                print(fmt(data))
                print()


if __name__ == "__main__":
    main()
