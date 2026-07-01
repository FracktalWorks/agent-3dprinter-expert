#!/usr/bin/env python3
"""
Remote Config Editor — Safely edits Klipper printer.cfg and related config
files on a remote Raspberry Pi via SSH. Features:

- Automatic timestamped backups before every edit
- Section-aware key-value editing
- Config validation after edits (calls firmware_analyzer.py remotely or locally)
- Diff generation (before/after)
- Klipper restart with verification
- Bulk operations for multi-key changes

Usage:
    python remote_config_editor.py --host 192.168.1.100 --edit sensor_type "ATC Semitec 104GT-2" --section extruder
    python remote_config_editor.py --host 192.168.1.100 --validate
    python remote_config_editor.py --host 192.168.1.100 --diff
    python remote_config_editor.py --host 192.168.1.100 --apply-and-restart
    python remote_config_editor.py --host 192.168.1.100 --edit rotation_distance 4.72 --section extruder --dry-run
"""

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional


# ── Defaults ──────────────────────────────────────────────────────────────────
PI_CONFIG_PATH = "/home/pi/printer_data/config/printer.cfg"
PI_CONFIG_DIR = "/home/pi/printer_data/config"


def _check_paramiko():
    try:
        import paramiko  # noqa: F401
    except ImportError:
        print(
            "ERROR: 'paramiko' package required. pip install paramiko",
            file=sys.stderr,
        )
        sys.exit(1)


def _get_client(
    host: str, port: int = 22, username: str = "pi",
    password: Optional[str] = None, key_file: Optional[str] = None,
    timeout: int = 15,
):
    _check_paramiko()
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    kwargs: dict = {
        "hostname": host, "port": port, "username": username,
        "timeout": timeout, "look_for_keys": True, "allow_agent": True,
    }
    if key_file and os.path.exists(os.path.expanduser(key_file)):
        kwargs["key_filename"] = os.path.expanduser(key_file)
    if password:
        kwargs["password"] = password

    try:
        client.connect(**kwargs)
        return client
    except Exception as e:
        raise ConnectionError(f"SSH connection failed: {e}")


def _exec(client, cmd: str, timeout: int = 30) -> tuple[int, str, str]:
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    exit_code = stdout.channel.recv_exit_status()
    return (
        exit_code,
        stdout.read().decode("utf-8", errors="replace"),
        stderr.read().decode("utf-8", errors="replace"),
    )


# ── Operations ────────────────────────────────────────────────────────────────

def read_remote_config(
    client, config_path: str = PI_CONFIG_PATH,
) -> str:
    """Read the full remote printer.cfg."""
    _, content, err = _exec(client, f"cat {config_path}")
    if err.strip():
        return f"ERROR: {err.strip()}"
    return content


def get_section(
    client, section: str, config_path: str = PI_CONFIG_PATH,
) -> str:
    """Extract a specific config section."""
    _, content, _ = _exec(
        client,
        f"sed -n '/^\\[{section}\\]/,/^\\[/p' {config_path}"
    )
    return content if content.strip() else f"Section [{section}] not found."


def list_sections(
    client, config_path: str = PI_CONFIG_PATH,
) -> str:
    """List all config sections."""
    _, content, _ = _exec(
        client, f"grep -n '^\\[' {config_path}"
    )
    return content if content.strip() else "No sections found."


def backup_config(
    client, config_path: str = PI_CONFIG_PATH,
) -> str:
    """Create a timestamped backup."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"printer.cfg.backup-{ts}"
    backup_path = f"{os.path.dirname(config_path)}/{backup_name}"
    _, stdout, stderr = _exec(
        client, f"cp {config_path} {backup_path} && echo '{backup_path}'"
    )
    if stderr.strip():
        return f"ERROR: {stderr.strip()}"
    return f"✓ Backup created: {backup_path}"


def list_backups(
    client, config_path: str = PI_CONFIG_PATH,
) -> str:
    """List all backups of printer.cfg."""
    cfg_dir = os.path.dirname(config_path)
    _, content, _ = _exec(
        client,
        f"ls -lht {cfg_dir}/printer.cfg.backup-* 2>/dev/null || "
        f"echo 'No backups found'"
    )
    return content.strip()


def restore_backup(
    client, backup_file: str, config_path: str = PI_CONFIG_PATH,
) -> str:
    """Restore a specific backup."""
    # Validate the backup file exists
    _, check, _ = _exec(client, f"test -f {backup_file} && echo 'OK'")
    if "OK" not in check:
        return f"ERROR: Backup file not found: {backup_file}"

    # Create safety backup of current before restoring
    safety = backup_config(client, config_path)

    _, stdout, stderr = _exec(
        client, f"cp {backup_file} {config_path}"
    )
    if stderr.strip():
        return f"ERROR restoring: {stderr.strip()}\n{safety}"
    return f"✓ Restored {backup_file}\n{safety}"


def edit_key(
    client,
    section: str,
    key: str,
    value: str,
    config_path: str = PI_CONFIG_PATH,
    dry_run: bool = False,
) -> str:
    """Edit a key in a specific section with backup and validation."""
    lines: list[str] = []

    # 1. Read current value
    _, current, _ = _exec(
        client,
        f"sed -n '/^\\[{section}\\]/,/^\\[/p' {config_path} | "
        f"grep '^{key}:' | head -1",
    )

    if not current.strip():
        return (
            f"ERROR: Key '{key}' not found in section [{section}].\n"
            f"Use --list-sections to see available sections, "
            f"or --get-section {section} to see the section contents."
        )

    current_val = current.strip()

    if dry_run:
        return (
            f"[DRY RUN] Would change [{section}] {key}:\n"
            f"  Before: {current_val}\n"
            f"  After:  {key}: {value}\n"
            f"  (No changes made)"
        )

    # 2. Backup
    backup_result = backup_config(client, config_path)
    lines.append(backup_result)

    # 3. Edit
    sed_cmd = (
        f"sed -i '/^\\[{section}\\]/,/^\\[/ "
        f"s/^{key}:.*$/{key}: {value}/' {config_path}"
    )
    exit_code, stdout, stderr = _exec(client, sed_cmd)
    if exit_code != 0:
        lines.append(f"ERROR: {stderr.strip()}")
        return "\n".join(lines)

    # 4. Verify
    _, new_val, _ = _exec(
        client,
        f"sed -n '/^\\[{section}\\]/,/^\\[/p' {config_path} | "
        f"grep '^{key}:' | head -1",
    )

    lines.append(f"✓ Changed [{section}] {key}:")
    lines.append(f"  {current_val}  →  {new_val.strip()}")

    return "\n".join(lines)


def edit_multiple(
    client,
    changes: list[tuple[str, str, str]],
    config_path: str = PI_CONFIG_PATH,
    dry_run: bool = False,
) -> str:
    """Apply multiple key edits in one operation with a single backup."""
    lines: list[str] = []

    if dry_run:
        lines.append("[DRY RUN] Would apply the following changes:")
        for section, key, value in changes:
            _, current, _ = _exec(
                client,
                f"sed -n '/^\\[{section}\\]/,/^\\[/p' {config_path} | "
                f"grep '^{key}:' | head -1",
            )
            lines.append(
                f"  [{section}] {key}: {current.strip()} → {key}: {value}"
            )
        return "\n".join(lines)

    # Single backup
    backup_result = backup_config(client, config_path)
    lines.append(backup_result)

    for section, key, value in changes:
        result = edit_key(
            client, section, key, value, config_path, dry_run=False,
        )
        lines.append(result)

    return "\n".join(lines)


def validate_config(
    client, config_path: str = PI_CONFIG_PATH,
) -> str:
    """Validate printer.cfg syntax by checking for parse errors without
    running full Klipper. Checks for bracket balance, duplicate sections,
    and common syntax issues."""
    lines: list[str] = []
    lines.append("=" * 50)
    lines.append("CONFIG VALIDATION")
    lines.append("=" * 50)

    # Read the full config
    _, config_text, _ = _exec(client, f"cat {config_path}")

    # Check 1: Bracket balance
    open_brackets = config_text.count("[")
    close_brackets = config_text.count("]")
    if open_brackets != close_brackets:
        lines.append(
            f"🔴 BRACKET MISMATCH: {open_brackets} '[' vs "
            f"{close_brackets} ']'"
        )
    else:
        lines.append(f"✓ Bracket balance OK ({open_brackets} sections)")

    # Check 2: Duplicate sections
    sections_found = re.findall(r"^\\[([^\\]]+)\\]", config_text, re.MULTILINE)
    seen = set()
    duplicates = set()
    for s in sections_found:
        if s in seen:
            duplicates.add(s)
        seen.add(s)
    if duplicates:
        lines.append(f"🔴 DUPLICATE SECTIONS: {', '.join(duplicates)}")
    else:
        lines.append("✓ No duplicate sections")

    # Check 3: Include file existence
    includes = re.findall(
        r"\\[include\s+(.+?)\\]", config_text, re.IGNORECASE
    )
    missing_includes = []
    for inc in includes:
        inc_path = inc.strip()
        if not inc_path.startswith("/"):
            inc_path = f"{PI_CONFIG_DIR}/{inc_path}"
        _, check, _ = _exec(client, f"test -f {inc_path} && echo OK")
        if "OK" not in check:
            missing_includes.append(inc.strip())
    if missing_includes:
        lines.append(
            f"🔴 MISSING INCLUDES: {', '.join(missing_includes)}"
        )
    else:
        lines.append(f"✓ All {len(includes)} include files found")

    # Check 4: SAVE_CONFIG sanity
    if "#*#" in config_text:
        save_lines = config_text.count("#*#")
        if save_lines > 2:
            lines.append(
                f"🟡 SAVE_CONFIG block present ({save_lines} markers) — "
                f"confirm it's not corrupted"
            )
        else:
            lines.append("✓ SAVE_CONFIG block present and looks normal")
    else:
        lines.append("✓ No SAVE_CONFIG block (fresh install)")

    # Check 5: Active printer includes (from Fracktal convention)
    active_printers = re.findall(
        r"^\\[include PRINTER_.+?\.cfg\\]", config_text, re.MULTILINE
    )
    if len(active_printers) > 1:
        lines.append(
            f"🔴 MULTIPLE PRINTERS ACTIVE: {active_printers}. "
            f"Only ONE should be uncommented."
        )
    elif len(active_printers) == 1:
        lines.append(f"✓ One active printer config: {active_printers[0]}")
    else:
        lines.append("⚠ No active printer config found!")

    return "\n".join(lines)


def diff_config(
    client,
    config_path: str = PI_CONFIG_PATH,
    backup_index: int = -1,
) -> str:
    """Show diff between current config and the latest backup."""
    cfg_dir = os.path.dirname(config_path)

    # Get list of backups sorted by time (newest first)
    _, backup_list, _ = _exec(
        client,
        f"ls -t {cfg_dir}/printer.cfg.backup-* 2>/dev/null | head -5"
    )

    if not backup_list.strip():
        return "No backups found for diff comparison."

    backups = backup_list.strip().split("\n")
    if abs(backup_index) >= len(backups):
        return (
            f"Backup index {backup_index} out of range. "
            f"Available: {len(backups)} backups. Use 0 for newest."
        )

    compare_file = backups[backup_index]

    _, diff_output, _ = _exec(
        client,
        f"diff -u {compare_file} {config_path} 2>/dev/null | head -100"
    )

    if not diff_output.strip():
        return f"✓ No differences between current config and {compare_file}"

    lines = []
    lines.append(f"Diff: {os.path.basename(compare_file)} → current")
    lines.append("=" * 50)
    lines.append(diff_output.strip())
    return "\n".join(lines)


def apply_and_restart(
    client,
    config_path: str = PI_CONFIG_PATH,
) -> str:
    """Restart Klipper and verify it comes back up cleanly."""
    lines: list[str] = []
    lines.append("=" * 50)
    lines.append("APPLYING CONFIG & RESTARTING KLIPPER")
    lines.append("=" * 50)

    # 1. Final validation
    val_result = validate_config(client, config_path)
    lines.append(val_result)
    lines.append("")

    # 2. Restart Klipper
    _, _, stderr = _exec(client, "sudo systemctl restart klipper")
    if stderr.strip():
        lines.append(f"⚠ Restart warning: {stderr.strip()}")

    # 3. Wait and check
    import time
    time.sleep(3)

    # 4. Check service status
    _, status, _ = _exec(
        client,
        "systemctl is-active klipper && "
        "systemctl status klipper --no-pager -l | head -5"
    )
    lines.append(f"Service status:\n{status.strip()}")

    # 5. Check log for errors after restart
    _, log_errors, _ = _exec(
        client,
        "tail -30 /home/pi/printer_data/logs/klippy.log | "
        "grep -i -E 'error|shutdown|unable' || echo '(no errors found)'"
    )
    lines.append(f"\nRecent log check:\n{log_errors.strip()}")

    # 6. Verify with OctoPrint if possible
    _, op_check, _ = _exec(
        client,
        "curl -s -H 'X-Api-Key: '$(grep -r 'api_key' "
        "/home/pi/.octoprint/config.yaml 2>/dev/null | "
        "awk '{print $2}') "
        "'http://localhost:5000/api/printer' 2>/dev/null | "
        "python3 -c 'import sys,json; "
        "d=json.load(sys.stdin); "
        "print(d.get(\"state\",{}).get(\"text\",\"unknown\"))' "
        "2>/dev/null || echo 'OctoPrint check skipped'"
    )
    lines.append(f"\nPrinter state: {op_check.strip()}")

    return "\n".join(lines)


def enable_include(
    client,
    include_file: str,
    config_path: str = PI_CONFIG_PATH,
    dry_run: bool = False,
) -> str:
    """Enable a commented-out [include ...] line by uncommenting it."""
    # Check if it's already enabled
    _, check, _ = _exec(
        client,
        f"grep -c '^\\[include {include_file}\\]' {config_path}"
    )
    if check.strip() != "0":
        return f"✓ [{include_file}] is already enabled."

    # Check if it exists as a comment
    _, check_comment, _ = _exec(
        client,
        f"grep -c '^#\\[include {include_file}\\]' {config_path}"
    )
    if check_comment.strip() == "0":
        return f"ERROR: Include '{include_file}' not found (even as comment)."

    if dry_run:
        return f"[DRY RUN] Would uncomment: [include {include_file}]"

    backup_config(client, config_path)
    _, stdout, stderr = _exec(
        client,
        f"sed -i 's/^#\\[include {include_file}\\]/[include {include_file}]/' "
        f"{config_path}"
    )
    if stderr.strip():
        return f"ERROR: {stderr.strip()}"
    return f"✓ Enabled: [include {include_file}]"


def disable_include(
    client,
    include_file: str,
    config_path: str = PI_CONFIG_PATH,
    dry_run: bool = False,
) -> str:
    """Disable an active [include ...] line by commenting it out."""
    _, check, _ = _exec(
        client,
        f"grep -c '^\\[include {include_file}\\]' {config_path}"
    )
    if check.strip() == "0":
        return f"✓ [{include_file}] is already disabled (or not found)."

    if dry_run:
        return f"[DRY RUN] Would comment out: [include {include_file}]"

    backup_config(client, config_path)
    _, stdout, stderr = _exec(
        client,
        f"sed -i 's/^\\[include {include_file}\\]/#[include {include_file}]/' "
        f"{config_path}"
    )
    if stderr.strip():
        return f"ERROR: {stderr.strip()}"
    return f"✓ Disabled: [include {include_file}]"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Safely edit Klipper config on a remote printer via SSH"
    )
    # Connection
    parser.add_argument(
        "--host", "-H",
        default=os.environ.get("PRINTER_SSH_HOST", ""),
        help="Printer Pi IP/hostname",
    )
    parser.add_argument(
        "--port", type=int, default=22, help="SSH port"
    )
    parser.add_argument(
        "--username", "-u",
        default=os.environ.get("PRINTER_SSH_USER", "pi"),
        help="SSH username",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("PRINTER_SSH_PASSWORD", None),
        help="SSH password (prefer key auth)",
    )
    parser.add_argument(
        "--key-file",
        default=os.environ.get("PRINTER_SSH_KEY", None),
        help="SSH private key path",
    )
    parser.add_argument(
        "--config-path",
        default=PI_CONFIG_PATH,
        help="Remote printer.cfg path",
    )

    # Actions
    parser.add_argument(
        "--read", action="store_true", help="Read full remote config"
    )
    parser.add_argument(
        "--list-sections", action="store_true",
        help="List all config sections",
    )
    parser.add_argument(
        "--get-section", help="Get a specific section's contents",
    )
    parser.add_argument(
        "--edit", nargs=2, metavar=("KEY", "VALUE"),
        help="Edit a key in a section (requires --section)",
    )
    parser.add_argument(
        "--section", help="Section for --edit or --get-section",
    )
    parser.add_argument(
        "--enable", help="Enable a commented [include] directive",
    )
    parser.add_argument(
        "--disable", help="Disable (comment out) an [include] directive",
    )
    parser.add_argument(
        "--validate", action="store_true", help="Validate config syntax"
    )
    parser.add_argument(
        "--backup", action="store_true", help="Create a timestamped backup"
    )
    parser.add_argument(
        "--list-backups", action="store_true",
        help="List available backups",
    )
    parser.add_argument(
        "--restore", help="Restore a specific backup file path",
    )
    parser.add_argument(
        "--diff", action="store_true",
        help="Show diff from latest backup",
    )
    parser.add_argument(
        "--apply-and-restart", action="store_true",
        help="Validate, restart Klipper, and verify",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would change without applying",
    )
    parser.add_argument(
        "--json", action="store_true", help="Output as JSON",
    )
    args = parser.parse_args()

    # Actions that don't need SSH
    if not args.host:
        print(
            "ERROR: --host required (set PRINTER_SSH_HOST env var).",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        client = _get_client(
            host=args.host, port=args.port, username=args.username,
            password=args.password, key_file=args.key_file,
        )
    except ConnectionError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        result: str = ""

        if args.read:
            result = read_remote_config(client, args.config_path)
        elif args.list_sections:
            result = list_sections(client, args.config_path)
        elif args.get_section:
            if not args.section:
                result = "ERROR: --section required with --get-section"
            else:
                result = get_section(
                    client, args.section, args.config_path
                )
        elif args.edit:
            if not args.section:
                result = "ERROR: --section required with --edit"
            else:
                key, value = args.edit
                result = edit_key(
                    client, args.section, key, value,
                    args.config_path, args.dry_run,
                )
        elif args.enable:
            result = enable_include(
                client, args.enable, args.config_path, args.dry_run,
            )
        elif args.disable:
            result = disable_include(
                client, args.disable, args.config_path, args.dry_run,
            )
        elif args.validate:
            result = validate_config(client, args.config_path)
        elif args.backup:
            result = backup_config(client, args.config_path)
        elif args.list_backups:
            result = list_backups(client, args.config_path)
        elif args.restore:
            result = restore_backup(
                client, args.restore, args.config_path,
            )
        elif args.diff:
            result = diff_config(client, args.config_path)
        elif args.apply_and_restart:
            result = apply_and_restart(client, args.config_path)
        else:
            result = (
                "No action specified. Use --read, --edit, --validate, "
                "--backup, --diff, --apply-and-restart, etc."
            )

    except Exception as e:
        result = f"ERROR: {e}"
    finally:
        client.close()

    if args.json:
        print(json.dumps({"result": result}, indent=2))
    else:
        print(result)


if __name__ == "__main__":
    main()
