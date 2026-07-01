#!/usr/bin/env python3
"""
SSH Manager — Connects to a 3D printer's Raspberry Pi via SSH to read logs,
edit configuration files, manage services, and run diagnostic commands.

Usage:
    python ssh_manager.py --host 192.168.1.100 --action logs --tail 100
    python ssh_manager.py --host 192.168.1.100 --action read-config
    python ssh_manager.py --host 192.168.1.100 --action restart-klipper
    python ssh_manager.py --host 192.168.1.100 --action exec --cmd "dmesg | tail"
    python ssh_manager.py --host 192.168.1.100 --action edit-config --key sensor_type --value "ATC Semitec 104GT-2" --section extruder
    python ssh_manager.py --host 192.168.1.100 --action check-services
"""

import argparse
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Default paths on Raspberry Pi ─────────────────────────────────────────────
PI_DEFAULTS = {
    "klipper_log": "/home/pi/printer_data/logs/klippy.log",
    "moonraker_log": "/home/pi/printer_data/logs/moonraker.log",
    "octoprint_log": "/home/pi/.octoprint/logs/octoprint.log",
    "printer_cfg": "/home/pi/printer_data/config/printer.cfg",
    "config_dir": "/home/pi/printer_data/config",
    "variables_cfg": "/home/pi/variables.cfg",
    "dmesg": "dmesg | tail -50",
    "klipper_service": "klipper",
    "octoprint_service": "octoprint",
}


def _check_paramiko() -> None:
    """Ensure paramiko is available."""
    try:
        import paramiko  # noqa: F401
    except ImportError:
        print(
            "ERROR: 'paramiko' package required. pip install paramiko",
            file=sys.stderr,
        )
        sys.exit(1)


def _get_ssh_client(
    host: str,
    port: int = 22,
    username: str = "pi",
    password: Optional[str] = None,
    key_file: Optional[str] = None,
    timeout: int = 15,
):
    """Create and connect an SSH client."""
    _check_paramiko()
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_kwargs: dict = {
        "hostname": host,
        "port": port,
        "username": username,
        "timeout": timeout,
        "look_for_keys": True,
        "allow_agent": True,
    }

    if key_file:
        key_path = os.path.expanduser(key_file)
        if os.path.exists(key_path):
            connect_kwargs["key_filename"] = key_path
    if password:
        connect_kwargs["password"] = password

    try:
        client.connect(**connect_kwargs)
        return client
    except paramiko.AuthenticationException:
        raise ConnectionError(
            f"SSH authentication failed for {username}@{host}. "
            f"Ensure SSH key is set up or provide --password."
        )
    except paramiko.SSHException as e:
        raise ConnectionError(f"SSH connection error: {e}")
    except Exception as e:
        raise ConnectionError(f"Could not connect to {host}: {e}")


def _exec(
    client, command: str, timeout: int = 30
) -> tuple[int, str, str]:
    """Execute a command via SSH and return exit_code, stdout, stderr."""
    _check_paramiko()
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    exit_code = stdout.channel.recv_exit_status()
    return (
        exit_code,
        stdout.read().decode("utf-8", errors="replace"),
        stderr.read().decode("utf-8", errors="replace"),
    )


# ── Actions ───────────────────────────────────────────────────────────────────

def action_tail_log(
    client,
    log_path: str = PI_DEFAULTS["klipper_log"],
    lines: int = 100,
    grep: Optional[str] = None,
) -> str:
    """Tail the specified log file."""
    if grep:
        cmd = f"tail -n {lines} {log_path} | grep -i '{grep}'"
    else:
        cmd = f"tail -n {lines} {log_path}"
    exit_code, stdout, stderr = _exec(client, cmd)
    if exit_code != 0 and stderr:
        return f"ERROR: {stderr.strip()}"
    return stdout if stdout.strip() else "(no matching lines)"


def action_read_config(
    client,
    config_path: str = PI_DEFAULTS["printer_cfg"],
) -> str:
    """Read the printer.cfg file."""
    exit_code, stdout, stderr = _exec(client, f"cat {config_path}")
    if exit_code != 0:
        return f"ERROR reading config: {stderr.strip()}"
    return stdout


def action_list_config_dir(
    client,
    config_dir: str = PI_DEFAULTS["config_dir"],
) -> str:
    """List all files in the config directory with sizes."""
    cmd = f"ls -lhS {config_dir}/*.cfg {config_dir}/*.conf 2>/dev/null"
    exit_code, stdout, stderr = _exec(client, cmd)
    return stdout if stdout.strip() else "(no .cfg files found)"


def action_restart_service(
    client, service: str,
) -> str:
    """Restart a systemd service (klipper or octoprint)."""
    valid_services = ["klipper", "octoprint"]
    if service not in valid_services:
        return f"ERROR: Unknown service '{service}'. Use one of {valid_services}"

    # Restart the service
    exit_code, stdout, stderr = _exec(
        client, f"sudo systemctl restart {service}"
    )
    if exit_code != 0:
        return f"ERROR restarting {service}: {stderr.strip()}"

    # Check status after restart
    _, status_out, _ = _exec(
        client,
        f"systemctl is-active {service} && systemctl status {service} --no-pager -l | head -5",
    )
    return f"✓ {service} restarted successfully.\n\n{status_out.strip()}"


def action_check_services(client) -> str:
    """Check status of Klipper and OctoPrint services."""
    lines = []
    lines.append("=" * 50)
    lines.append("SERVICE STATUS")
    lines.append("=" * 50)

    for service in ["klipper", "octoprint"]:
        _, stdout, _ = _exec(
            client,
            f"systemctl is-active {service} 2>/dev/null && "
            f"systemctl status {service} --no-pager -l 2>/dev/null | head -8",
        )
        lines.append(stdout.strip() if stdout.strip() else f"{service}: NOT FOUND")
        lines.append("")

    # Also check for klipper screen or other services
    _, extra, _ = _exec(
        client,
        "systemctl list-units --type=service --state=running 2>/dev/null | "
        "grep -E 'klipper|octoprint|moonraker|webcam|mjpg' || echo '(none)'",
    )
    if extra.strip() and extra.strip() != "(none)":
        lines.append("Other related services:")
        lines.append(extra.strip())

    return "\n".join(lines)


def action_exec_command(client, command: str) -> str:
    """Execute an arbitrary command on the Pi."""
    exit_code, stdout, stderr = _exec(client, command, timeout=60)
    result = []
    if stdout.strip():
        result.append(stdout.strip())
    if stderr.strip():
        result.append(f"STDERR:\n{stderr.strip()}")
    if not result:
        result.append(f"(command completed with exit code {exit_code}, no output)")
    return "\n".join(result)


def action_get_system_info(client) -> str:
    """Get system info: uptime, disk, memory, temperature."""
    lines = []
    lines.append("=" * 50)
    lines.append("SYSTEM INFORMATION")
    lines.append("=" * 50)

    # Uptime
    _, uptime, _ = _exec(client, "uptime")
    lines.append(f"Uptime: {uptime.strip()}")

    # Disk usage
    _, disk, _ = _exec(client, "df -h / /home/pi 2>/dev/null | tail -2")
    lines.append(f"Disk:\n{disk.strip()}")

    # Memory
    _, mem, _ = _exec(client, "free -h | head -2")
    lines.append(f"Memory:\n{mem.strip()}")

    # CPU temperature
    _, temp, _ = _exec(
        client, "vcgencmd measure_temp 2>/dev/null || "
        "cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || "
        "echo 'N/A'"
    )
    temp_str = temp.strip()
    if temp_str.isdigit():
        temp_str = f"{float(temp_str) / 1000:.1f}°C"
    lines.append(f"CPU Temperature: {temp_str}")

    # Kernel messages (last 5)
    _, dmesg, _ = _exec(client, "dmesg | tail -5")
    lines.append(f"\nRecent kernel messages:\n{dmesg.strip()}")

    return "\n".join(lines)


def action_backup_config(
    client,
    config_path: str = PI_DEFAULTS["printer_cfg"],
) -> str:
    """Create a timestamped backup of printer.cfg."""
    backup_name = (
        f"printer.cfg.backup-"
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    backup_path = (
        f"{os.path.dirname(config_path)}/{backup_name}"
    )
    _, stdout, stderr = _exec(
        client, f"cp {config_path} {backup_path} && echo 'Backup: {backup_path}'"
    )
    if stderr.strip():
        return f"ERROR: {stderr.strip()}"
    return stdout.strip()


def action_edit_config(
    client,
    config_path: str,
    section: str,
    key: str,
    value: str,
    backup: bool = True,
) -> str:
    """Edit a specific key in a specific section of printer.cfg.

    Uses sed for in-place editing. Always validates the section exists.
    Creates a backup before editing unless --no-backup is specified.
    """
    # First verify the config file exists
    _, check, _ = _exec(client, f"test -f {config_path} && echo 'OK'")
    if "OK" not in check:
        return f"ERROR: Config file not found: {config_path}"

    # Verify the section exists
    _, section_check, _ = _exec(
        client, f"grep -c '^\\[{section}\\]' {config_path}"
    )
    if section_check.strip() == "0":
        return f"ERROR: Section [{section}] not found in {config_path}"

    # Create backup
    if backup:
        backup_result = action_backup_config(client, config_path)
        if "ERROR" in backup_result:
            return backup_result

    # Read current value
    _, current_val, _ = _exec(
        client,
        f"sed -n '/^\\[{section}\\]/,/^\\[/p' {config_path} | "
        f"grep '^{key}:' | head -1",
    )

    if not current_val.strip():
        return (
            f"ERROR: Key '{key}' not found in section [{section}]. "
            f"Add it manually or use a different key name."
        )

    # Edit: replace the value in the correct section
    # This sed command: within the [section] block, replace the key's value
    sed_cmd = (
        f"sed -i '/^\\[{section}\\]/,/^\\[/ "
        f"s/^{key}:.*$/{key}: {value}/' {config_path}"
    )
    exit_code, stdout, stderr = _exec(client, sed_cmd)

    if exit_code != 0:
        return f"ERROR editing config: {stderr.strip()}"

    # Read the new value to confirm
    _, new_val, _ = _exec(
        client,
        f"sed -n '/^\\[{section}\\]/,/^\\[/p' {config_path} | "
        f"grep '^{key}:' | head -1",
    )

    return (
        f"✓ Changed [{section}] {key}\n"
        f"  Before: {current_val.strip()}\n"
        f"  After:  {new_val.strip()}\n"
        f"  Backup saved with timestamp."
    )


def action_get_klipper_errors(client, lines: int = 200) -> str:
    """Extract only error/shutdown lines from klippy.log."""
    log_path = PI_DEFAULTS["klipper_log"]
    cmd = (
        f"grep -n -E 'shutdown|ERROR|error|MCU.*shutdown|"
        f"Heater.*not heating|ADC out of range|"
        f"Lost communication|Timer too close|"
        f"Move exceeds maximum|Unable to open' "
        f"{log_path} | tail -{lines}"
    )
    exit_code, stdout, stderr = _exec(client, cmd, timeout=30)
    if not stdout.strip():
        return "✓ No recent errors found in klippy.log"
    return stdout


def action_update_firmware(client, mode: str = "check") -> str:
    """Check for or update Klipper firmware via KIAUH or manual git pull."""
    if mode == "check":
        # Check current versions
        _, klipper_ver, _ = _exec(
            client,
            "cd ~/klipper && git log --oneline -1 2>/dev/null || echo 'not found'"
        )
        _, os_ver, _ = _exec(
            client,
            "cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | head -1"
        )
        _, python_ver, _ = _exec(client, "python3 --version 2>/dev/null")

        lines = []
        lines.append("=" * 40)
        lines.append("VERSION INFORMATION")
        lines.append("=" * 40)
        lines.append(f"Klipper: {klipper_ver.strip()}")
        lines.append(f"OS: {os_ver.strip()}")
        lines.append(f"Python: {python_ver.strip()}")

        # Check for available updates
        _, updates, _ = _exec(
            client,
            "cd ~/klipper && git fetch --dry-run 2>&1 | head -3 || echo 'check failed'"
        )
        lines.append(f"\nUpdate check: {updates.strip()}")
        return "\n".join(lines)

    elif mode == "update":
        return (
            "WARNING: Automatic firmware updates via SSH are disabled for "
            "safety. To update:\n"
            "1. SSH into the Pi: ssh pi@<ip>\n"
            "2. cd ~/klipper && git pull\n"
            "3. sudo systemctl restart klipper\n"
            "4. Verify with: python klipper_log_parser.py --days 1"
        )

    return f"Unknown mode: {mode}"


# ── Action registry ───────────────────────────────────────────────────────────

ACTIONS = {
    "logs": action_tail_log,
    "read-config": action_read_config,
    "list-configs": action_list_config_dir,
    "restart-klipper": lambda c: action_restart_service(c, "klipper"),
    "restart-octoprint": lambda c: action_restart_service(c, "octoprint"),
    "check-services": action_check_services,
    "exec": action_exec_command,
    "system-info": action_get_system_info,
    "backup-config": action_backup_config,
    "edit-config": action_edit_config,
    "klipper-errors": action_get_klipper_errors,
    "update-check": lambda c: action_update_firmware(c, "check"),
}


def main():
    parser = argparse.ArgumentParser(
        description="SSH into 3D printer Raspberry Pi for diagnostics"
    )
    parser.add_argument(
        "--host", "-H",
        default=os.environ.get("PRINTER_SSH_HOST", ""),
        help="Printer Pi IP/hostname (env: PRINTER_SSH_HOST)",
    )
    parser.add_argument(
        "--port", "-P",
        type=int,
        default=22,
        help="SSH port (default: 22)",
    )
    parser.add_argument(
        "--username", "-u",
        default=os.environ.get("PRINTER_SSH_USER", "pi"),
        help="SSH username (default: pi)",
    )
    parser.add_argument(
        "--password", "-p",
        default=os.environ.get("PRINTER_SSH_PASSWORD", None),
        help="SSH password (prefer key-based auth)",
    )
    parser.add_argument(
        "--key-file", "-k",
        default=os.environ.get("PRINTER_SSH_KEY", None),
        help="Path to SSH private key",
    )
    parser.add_argument(
        "--action", "-a",
        required=True,
        choices=list(ACTIONS.keys()),
        help="What to do on the printer",
    )
    parser.add_argument(
        "--tail", type=int, default=100, help="Lines to tail (for logs action)"
    )
    parser.add_argument(
        "--grep", help="Filter log lines (for logs action)"
    )
    parser.add_argument(
        "--cmd", help="Command to execute (for exec action)"
    )
    parser.add_argument(
        "--config-path",
        default=PI_DEFAULTS["printer_cfg"],
        help="Path to printer.cfg on the Pi",
    )
    parser.add_argument(
        "--section", help="Config section to edit (for edit-config)"
    )
    parser.add_argument(
        "--key", help="Config key to edit (for edit-config)"
    )
    parser.add_argument(
        "--value", help="New value (for edit-config)"
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip backup before editing config",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="SSH command timeout in seconds",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    if not args.host:
        print(
            "ERROR: --host is required (or set PRINTER_SSH_HOST env var).",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        client = _get_ssh_client(
            host=args.host,
            port=args.port,
            username=args.username,
            password=args.password,
            key_file=args.key_file,
            timeout=args.timeout,
        )
    except ConnectionError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        # Route to the appropriate action
        action_name = args.action

        if action_name == "logs":
            result = ACTIONS[action_name](
                client,
                log_path=PI_DEFAULTS["klipper_log"],
                lines=args.tail,
                grep=args.grep,
            )
        elif action_name == "exec":
            if not args.cmd:
                print(
                    "ERROR: --cmd required for 'exec' action.",
                    file=sys.stderr,
                )
                sys.exit(1)
            result = ACTIONS[action_name](client, args.cmd)
        elif action_name == "edit-config":
            if not all([args.section, args.key, args.value]):
                print(
                    "ERROR: --section, --key, and --value required for "
                    "'edit-config' action.",
                    file=sys.stderr,
                )
                sys.exit(1)
            result = ACTIONS[action_name](
                client,
                config_path=args.config_path,
                section=args.section,
                key=args.key,
                value=args.value,
                backup=not args.no_backup,
            )
        elif action_name in ("read-config", "list-configs", "backup-config"):
            result = ACTIONS[action_name](
                client,
                config_path=args.config_path,
            )
        else:
            result = ACTIONS[action_name](client)
    except Exception as e:
        result = f"ERROR: {e}"
    finally:
        client.close()

    if args.json:
        import json
        print(json.dumps({"action": args.action, "result": result}, indent=2))
    else:
        print(result)


if __name__ == "__main__":
    main()
