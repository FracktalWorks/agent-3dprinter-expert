#!/usr/bin/env python3
"""
Raspberry Pi System Diagnostics — SSH-based health checks for the printer's
Pi (CM4/Pi4/Pi3): power/undervoltage, thermal throttling, SD card health,
network, USB/serial devices, CAN bus, systemd services, boot configuration,
and kernel/journal errors.

Undervoltage and failing SD cards are the two most common root causes of
"random" Klipper MCU disconnects and Pi lockups — always rule them out first.

Usage:
    python pi_system_diagnostics.py --host 192.168.1.100 --check all
    python pi_system_diagnostics.py --host 192.168.1.100 --check power
    python pi_system_diagnostics.py --host 192.168.1.100 --check thermal
    python pi_system_diagnostics.py --host 192.168.1.100 --check storage
    python pi_system_diagnostics.py --host 192.168.1.100 --check network
    python pi_system_diagnostics.py --host 192.168.1.100 --check usb
    python pi_system_diagnostics.py --host 192.168.1.100 --check can
    python pi_system_diagnostics.py --host 192.168.1.100 --check services
    python pi_system_diagnostics.py --host 192.168.1.100 --check boot-config
    python pi_system_diagnostics.py --host 192.168.1.100 --check journal
    python pi_system_diagnostics.py --failures
"""

import argparse
import json
import os
import sys

DEFAULT_HOST = os.environ.get("PRINTER_SSH_HOST", "")
DEFAULT_USER = os.environ.get("PRINTER_SSH_USER", "pi")
DEFAULT_PASSWORD = os.environ.get("PRINTER_SSH_PASSWORD", "")
DEFAULT_KEY = os.environ.get("PRINTER_SSH_KEY", "")

# Services worth checking on a printer Pi (present ones only are reported)
PRINTER_SERVICES = ["klipper", "moonraker", "octoprint", "nginx",
                    "KlipperScreen", "crowsnest", "webcamd", "wpa_supplicant"]

# vcgencmd get_throttled bit meanings
THROTTLE_BITS = {
    0: "Under-voltage detected NOW",
    1: "ARM frequency capped NOW",
    2: "Currently throttled NOW",
    3: "Soft temperature limit active NOW",
    16: "Under-voltage has occurred since boot",
    17: "ARM frequency capping has occurred since boot",
    18: "Throttling has occurred since boot",
    19: "Soft temperature limit has occurred since boot",
}

FAILURE_MODES = {
    "undervoltage": {
        "symptom": "Random MCU disconnects, USB dropouts, Pi reboots, lightning-bolt icon",
        "causes": [
            "Undersized PSU or thin USB power cable (Pi4/CM4 needs 5V/3A minimum)",
            "Powering Pi from printer mainboard 5V rail that sags under load",
            "Long/thin wiring between PSU and Pi — voltage drop under load",
        ],
        "checks": ["--check power (decodes vcgencmd get_throttled)",
                   "dmesg | grep -i voltage"],
    },
    "sd_card_failing": {
        "symptom": "I/O errors, read-only filesystem, services fail to start, corrupted configs",
        "causes": ["Worn SD card (most common Pi failure)", "Power loss during writes",
                   "Counterfeit/low-quality card"],
        "checks": ["--check storage (dmesg mmc errors, read-only mounts)",
                   "Consider migrating to CM4 eMMC or USB SSD boot"],
    },
    "thermal_throttling": {
        "symptom": "Slow UI, Klipper 'Timer too close' during prints, temp > 80°C",
        "causes": ["No heatsink/fan in enclosed electronics bay",
                   "Chamber heat soaking into electronics compartment"],
        "checks": ["--check thermal", "Add cooling; verify electronics chamber fan works"],
    },
    "wifi_dropouts": {
        "symptom": "Mainsail/OctoPrint disconnects, laggy control, failed uploads",
        "causes": ["Weak signal (metal printer frame shields antenna)",
                   "Power-save mode on wlan0", "2.4GHz interference"],
        "checks": ["--check network (link quality, power_save state)",
                   "Prefer ethernet for production printers"],
    },
    "usb_serial_missing": {
        "symptom": "Klipper: 'Unable to open serial port' / mcu unreachable",
        "causes": ["Cable/connector, MCU not flashed, board in DFU/boot mode",
                   "USB autosuspend, brownout resets the MCU"],
        "checks": ["--check usb (lists /dev/serial/by-id)", "dmesg | grep -i usb"],
    },
    "can_bus_down": {
        "symptom": "CAN toolhead MCU timeout / 'Unable to find canbus_uuid'",
        "causes": ["can0 interface down or wrong bitrate (Fracktal uses 500k)",
                   "Missing 120Ω termination", "Toolhead board unpowered or firmware crashed"],
        "checks": ["--check can (interface state, bitrate, error counters)",
                   "~/klipper/scripts/canbus_query.py can0 to enumerate UUIDs"],
    },
}


# ── SSH helper ────────────────────────────────────────────────────────────────

def get_client(host: str, user: str, password: str, key_file: str):
    try:
        import paramiko
    except ImportError:
        print("ERROR: 'paramiko' package required. pip install paramiko", file=sys.stderr)
        sys.exit(1)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs: dict = {"hostname": host, "username": user, "timeout": 15,
                    "look_for_keys": True, "allow_agent": True}
    if key_file and os.path.exists(os.path.expanduser(key_file)):
        kwargs["key_filename"] = os.path.expanduser(key_file)
    if password:
        kwargs["password"] = password
    try:
        client.connect(**kwargs)
    except Exception as e:
        print(f"ERROR: SSH connection to {host} failed: {e}", file=sys.stderr)
        sys.exit(1)
    return client


def run(client, cmd: str, timeout: int = 25) -> str:
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace").strip()
    err = stderr.read().decode(errors="replace").strip()
    return out if out else err


# ── Checks ────────────────────────────────────────────────────────────────────

def decode_throttled(raw: str) -> dict:
    """Decode vcgencmd get_throttled hex value into human-readable flags."""
    try:
        value = int(raw.split("=")[-1], 16)
    except (ValueError, IndexError):
        return {"raw": raw, "error": "could not parse"}
    flags = [desc for bit, desc in THROTTLE_BITS.items() if value & (1 << bit)]
    return {
        "raw": raw.strip(),
        "value": hex(value),
        "healthy": value == 0,
        "active_flags": flags or ["none — power and thermals OK"],
    }


def check_power(client) -> dict:
    throttled = run(client, "vcgencmd get_throttled 2>/dev/null || echo unavailable")
    volts = run(client, "vcgencmd measure_volts core 2>/dev/null || echo unavailable")
    dmesg_uv = run(client, "dmesg | grep -i 'voltage' | tail -5")
    result = {
        "throttled": decode_throttled(throttled) if "=" in throttled else throttled,
        "core_voltage": volts,
        "dmesg_voltage_events": dmesg_uv or "(none)",
    }
    t = result["throttled"]
    if isinstance(t, dict) and not t.get("healthy", True):
        result["verdict"] = ("⚠ POWER/THERMAL FLAGS SET — undervoltage or throttling "
                             "detected. This causes random MCU disconnects and SD corruption. "
                             "Fix the power supply before chasing other symptoms.")
    else:
        result["verdict"] = "OK"
    return result


def check_thermal(client) -> dict:
    temp = run(client, "vcgencmd measure_temp 2>/dev/null || "
                       "awk '{printf \"temp=%.1f'\"'\"'C\\n\", $1/1000}' "
                       "/sys/class/thermal/thermal_zone0/temp")
    clock = run(client, "vcgencmd measure_clock arm 2>/dev/null || echo unavailable")
    result = {"soc_temperature": temp, "arm_clock": clock}
    try:
        deg = float(temp.split("=")[1].split("'")[0])
        if deg >= 80:
            result["verdict"] = "⚠ HOT (≥80°C) — actively throttling; add cooling"
        elif deg >= 70:
            result["verdict"] = "⚠ WARM (≥70°C) — approaching throttle threshold"
        else:
            result["verdict"] = "OK"
    except (IndexError, ValueError):
        result["verdict"] = "Could not parse temperature"
    return result


def check_storage(client) -> dict:
    df = run(client, "df -h / /boot 2>/dev/null | head -5")
    ro = run(client, "grep ' ro,' /proc/mounts | grep -v -E 'tmpfs|proc|sys' || echo none")
    mmc_err = run(client, "dmesg | grep -i -E 'mmc[0-9]|i/o error|ext4.*error' | tail -10")
    result = {
        "disk_usage": df,
        "read_only_mounts": ro,
        "mmc_io_errors": mmc_err or "(none)",
    }
    problems = []
    if ro != "none" and ro:
        problems.append("filesystem mounted read-only (classic failing-SD symptom)")
    if mmc_err and "error" in mmc_err.lower():
        problems.append("mmc/I-O errors in dmesg")
    for line in df.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 5 and parts[4].rstrip("%").isdigit() and int(parts[4].rstrip("%")) >= 90:
            problems.append(f"partition {parts[-1]} at {parts[4]} capacity")
    result["verdict"] = ("⚠ " + "; ".join(problems)) if problems else "OK"
    return result


def check_network(client) -> dict:
    ip_addr = run(client, "hostname -I")
    wifi = run(client, "iwconfig wlan0 2>/dev/null | grep -E 'ESSID|Link Quality|Bit Rate' || echo 'no wlan0'")
    power_save = run(client, "iw wlan0 get power_save 2>/dev/null || echo unavailable")
    gateway = run(client, "ip route | awk '/default/ {print $3; exit}'")
    ping = run(client, f"ping -c 2 -W 2 {gateway or '8.8.8.8'} 2>&1 | tail -2")
    return {
        "ip_addresses": ip_addr,
        "wifi": wifi,
        "wifi_power_save": power_save,
        "default_gateway": gateway,
        "gateway_ping": ping,
    }


def check_usb(client) -> dict:
    serial_ids = run(client, "ls -la /dev/serial/by-id/ 2>/dev/null || echo 'no serial devices'")
    lsusb = run(client, "lsusb")
    usb_err = run(client, "dmesg | grep -i -E 'usb.*(disconnect|reset|error)' | tail -8")
    return {
        "serial_by_id": serial_ids,
        "lsusb": lsusb,
        "recent_usb_events": usb_err or "(none)",
        "hint": "Klipper [mcu] serial: should use the stable /dev/serial/by-id/ path",
    }


def check_can(client) -> dict:
    link = run(client, "ip -details -s link show can0 2>/dev/null || echo 'no can0 interface'")
    result: dict = {"can0": link}
    if "no can0" in link:
        result["verdict"] = ("No can0 — expected on CAN-toolhead printers. Check "
                             "/etc/network/interfaces.d/can0 and that the Manta's "
                             "USB-to-CAN bridge is enumerated (lsusb).")
        return result
    if "DOWN" in link:
        result["verdict"] = "⚠ can0 exists but is DOWN — sudo ip link set can0 up type can bitrate 500000"
    elif "bus-off" in link.lower() or "BUS-OFF" in link:
        result["verdict"] = "⚠ BUS-OFF — wiring/termination fault; check 120Ω terminators"
    else:
        result["verdict"] = "OK (verify bitrate 500000 matches firmware and error counters ≈ 0)"
    uuids = run(client, "~/klippy-env/bin/python ~/klipper/scripts/canbus_query.py can0 "
                        "2>/dev/null | head -5 || echo 'canbus_query unavailable "
                        "(klipper must be stopped to query)'")
    result["canbus_query"] = uuids
    return result


def check_services(client) -> dict:
    result: dict = {}
    for svc in PRINTER_SERVICES:
        state = run(client, f"systemctl is-active {svc} 2>/dev/null")
        if state and state != "inactive" or state == "failed":
            result[svc] = state
    failed = [s for s, st in result.items() if st == "failed"]
    result["verdict"] = (f"⚠ failed services: {', '.join(failed)} — "
                         f"journalctl -u <svc> -n 50" if failed else "OK")
    return result


def check_boot_config(client) -> dict:
    cfg_path = run(client, "ls /boot/firmware/config.txt 2>/dev/null || ls /boot/config.txt 2>/dev/null")
    content = run(client, f"grep -v -E '^\\s*#|^\\s*$' {cfg_path} 2>/dev/null" if cfg_path
                  else "echo 'config.txt not found'")
    cmdline = run(client, "cat /boot/firmware/cmdline.txt 2>/dev/null || cat /boot/cmdline.txt 2>/dev/null")
    model = run(client, "cat /proc/device-tree/model 2>/dev/null | tr -d '\\0'")
    os_rel = run(client, "grep PRETTY_NAME /etc/os-release | cut -d= -f2")
    return {
        "pi_model": model,
        "os": os_rel,
        "config_txt_path": cfg_path or "not found",
        "config_txt_active_lines": content,
        "cmdline_txt": cmdline,
    }


def check_journal(client) -> dict:
    errors = run(client, "journalctl -p 3 -n 25 --no-pager 2>/dev/null | tail -25")
    oom = run(client, "dmesg | grep -i 'out of memory' | tail -3")
    reboots = run(client, "last reboot 2>/dev/null | head -5")
    mem = run(client, "free -m | head -2")
    uptime = run(client, "uptime")
    return {
        "uptime": uptime,
        "memory_mb": mem,
        "recent_priority3_errors": errors or "(none)",
        "oom_events": oom or "(none)",
        "recent_reboots": reboots,
    }


def print_failures(key: str = "") -> None:
    modes = {key: FAILURE_MODES[key]} if key in FAILURE_MODES else FAILURE_MODES
    for name, mode in modes.items():
        print(f"\n══ {name} ══")
        print(f"  Symptom: {mode['symptom']}")
        print("  Likely causes:")
        for c in mode["causes"]:
            print(f"    • {c}")
        print("  Checks:")
        for c in mode["checks"]:
            print(f"    → {c}")


CHECKS = {
    "power": check_power,
    "thermal": check_thermal,
    "storage": check_storage,
    "network": check_network,
    "usb": check_usb,
    "can": check_can,
    "services": check_services,
    "boot-config": check_boot_config,
    "journal": check_journal,
}


def main():
    parser = argparse.ArgumentParser(description="Raspberry Pi system diagnostics via SSH")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Pi host/IP (or PRINTER_SSH_HOST)")
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--key-file", default=DEFAULT_KEY)
    parser.add_argument("--check", default="all",
                        choices=["all"] + list(CHECKS.keys()))
    parser.add_argument("--failures", nargs="?", const="", default=None,
                        help="Print known failure-mode reference (optionally one key)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.failures is not None:
        print_failures(args.failures)
        return

    if not args.host:
        print("ERROR: --host required (or set PRINTER_SSH_HOST)", file=sys.stderr)
        sys.exit(1)

    client = get_client(args.host, args.user, args.password, args.key_file)
    try:
        if args.check == "all":
            report = {name: fn(client) for name, fn in CHECKS.items()}
        else:
            report = {args.check: CHECKS[args.check](client)}
    finally:
        client.close()

    print(json.dumps(report, indent=2, default=str))

    warnings = [f"{name}: {c['verdict']}" for name, c in report.items()
                if isinstance(c, dict) and str(c.get("verdict", "")).startswith("⚠")]
    if warnings:
        print("\n".join(["", "── Attention required ──"] + warnings), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
