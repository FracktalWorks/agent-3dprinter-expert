#!/usr/bin/env python3
"""
Display Diagnostics — Debugs display boards attached to the printer's Pi:
SPI TFT panels (fbtft/ili9486/st7789 class), HDMI touchscreens, and DSI
panels, plus the KlipperScreen / X / Wayland stack that draws on them.

Covers: /boot config.txt overlay review, framebuffer + KMS/DRM state, SPI
bus enablement, touch input devices and calibration, HDMI hotplug/EDID,
backlight control, KlipperScreen service and log analysis, and a knowledge
base of the classic failure modes (white screen, no signal, inverted touch).

Usage:
    python display_diagnostics.py --host 192.168.1.100 --check all
    python display_diagnostics.py --host 192.168.1.100 --check boot-config
    python display_diagnostics.py --host 192.168.1.100 --check framebuffer
    python display_diagnostics.py --host 192.168.1.100 --check spi
    python display_diagnostics.py --host 192.168.1.100 --check hdmi
    python display_diagnostics.py --host 192.168.1.100 --check touch
    python display_diagnostics.py --host 192.168.1.100 --check klipperscreen
    python display_diagnostics.py --host 192.168.1.100 --check backlight
    python display_diagnostics.py --host 192.168.1.100 --check dmesg
    python display_diagnostics.py --failures
    python display_diagnostics.py --failures spi_white_screen
"""

import argparse
import json
import os
import re
import sys

DEFAULT_HOST = os.environ.get("PRINTER_SSH_HOST", "")
DEFAULT_USER = os.environ.get("PRINTER_SSH_USER", "pi")
DEFAULT_PASSWORD = os.environ.get("PRINTER_SSH_PASSWORD", "")
DEFAULT_KEY = os.environ.get("PRINTER_SSH_KEY", "")

# config.txt lines that matter for displays
DISPLAY_CONFIG_PATTERNS = (
    r"dtoverlay=", r"dtparam=spi", r"dtparam=i2c", r"hdmi_", r"framebuffer_",
    r"display_rotate", r"lcd_rotate", r"gpu_mem", r"max_framebuffers",
    r"disable_overscan", r"config_hdmi_boost", r"enable_dpi_lcd", r"dpi_",
    r"ignore_lcd", r"disable_touchscreen",
)

FAILURE_MODES = {
    "spi_white_screen": {
        "symptom": "SPI TFT shows solid white (backlight on, no image)",
        "causes": [
            "Wrong/missing dtoverlay for the panel controller (e.g. need waveshare35a, piscreen, ili9486 variant)",
            "SPI not enabled (dtparam=spi=on missing)",
            "speed= too high for wiring — try 16–24MHz instead of 32MHz+",
            "Wiring: DC/RS or RESET pin mismatch vs overlay defaults",
            "Panel revision differs from overlay (v3 vs v4 boards need different overlays)",
        ],
        "checks": [
            "--check boot-config — confirm the dtoverlay line matches the panel",
            "--check spi — /dev/spidev* present, fbtft module loaded",
            "--check dmesg — fbtft probe errors show the real reason",
        ],
    },
    "hdmi_no_signal": {
        "symptom": "HDMI display shows 'no signal' or stays black from boot",
        "causes": [
            "Display powered after Pi booted with hotplug undetected — set hdmi_force_hotplug=1",
            "EDID not readable (long/cheap cable, KVM) — set hdmi_group/hdmi_mode explicitly",
            "Wrong HDMI port on Pi4/CM4 (use HDMI0, nearest USB-C power)",
            "vc4-kms-v3d + a config still using legacy hdmi_ settings (KMS ignores most hdmi_* lines)",
            "Insufficient signal drive — config_hdmi_boost=4 (or higher)",
        ],
        "checks": [
            "--check hdmi — connector state, EDID, current mode via KMS",
            "--check boot-config — hdmi_force_hotplug / hdmi_group / hdmi_mode / KMS overlay",
            "kmsprint (KMS) or tvservice -s (legacy) on the Pi",
        ],
    },
    "touch_inverted_or_offset": {
        "symptom": "Touch works but is mirrored/rotated relative to the image, or offset",
        "causes": [
            "Display rotated (display_rotate/lcd_rotate) without matching touch transform",
            "ads7846 overlay missing swapxy/invx/invy params",
            "X11: missing libinput 'TransformationMatrix' / 'CalibrationMatrix' for the touch device",
        ],
        "checks": [
            "--check touch — input devices + current transform",
            "For ads7846: dtoverlay=ads7846,...,swapxy=1,invx=1 style params in config.txt",
            "For X11: xinput set-prop with a coordinate transformation matrix",
        ],
    },
    "klipperscreen_wont_start": {
        "symptom": "KlipperScreen service crash-loops; screen stays on console/blank",
        "causes": [
            "No X server / wrong display backend (KlipperScreen needs Xorg or a cage/Wayland session)",
            "Moonraker unreachable from localhost (check moonraker.conf trusted clients)",
            "Panel not detected → Xorg has no usable framebuffer (check fb0/fb1 mapping)",
            "Xorg FBDEV config points at wrong /dev/fbN for SPI panels",
        ],
        "checks": [
            "--check klipperscreen — service state + last log lines",
            "--check framebuffer — which fb device the panel actually is",
            "KlipperScreen.log usually names the exact failure (DISPLAY, Moonraker, or GTK)",
        ],
    },
    "console_on_wrong_display": {
        "symptom": "Boot console appears on HDMI but UI expected on SPI panel (or vice versa)",
        "causes": [
            "con2fbmap not applied (console maps to fb0 by default)",
            "fbcon=map:10 missing from cmdline.txt for SPI-console setups",
        ],
        "checks": [
            "--check framebuffer — fb0 vs fb1 controllers",
            "cmdline.txt: fbcon=map:10 puts console on fb1 (SPI) then fb0",
        ],
    },
    "dsi_panel_black": {
        "symptom": "Official 7\" DSI panel black; backlight maybe on",
        "causes": [
            "DSI cable seated wrong side / not fully inserted at either end",
            "vc4-kms-v3d without the panel's KMS support on older OS — try vc4-fkms-v3d",
            "ignore_lcd=1 set in config.txt",
        ],
        "checks": ["--check boot-config", "--check dmesg — look for 'ft5406' / 'rpi-dsi' probe"],
    },
    "backlight_dead": {
        "symptom": "Image visible under flashlight but no backlight",
        "causes": ["Backlight PWM pin not driven (overlay param)", "/sys/class/backlight value 0",
                   "Hardware: backlight fuse/driver on the display board failed"],
        "checks": ["--check backlight — sysfs brightness/actual values"],
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

def check_boot_config(client) -> dict:
    cfg_path = run(client, "ls /boot/firmware/config.txt 2>/dev/null || ls /boot/config.txt 2>/dev/null")
    if not cfg_path:
        return {"error": "config.txt not found"}
    raw = run(client, f"grep -v -E '^\\s*$' {cfg_path}")
    pattern = re.compile("|".join(DISPLAY_CONFIG_PATTERNS))
    display_lines = [ln for ln in raw.splitlines()
                     if pattern.search(ln) and not ln.strip().startswith("#")]
    commented = [ln for ln in raw.splitlines()
                 if pattern.search(ln) and ln.strip().startswith("#")]
    kms = next((ln for ln in display_lines if "vc4-kms" in ln or "vc4-fkms" in ln), None)
    result = {
        "config_txt": cfg_path,
        "display_relevant_lines": display_lines or ["(none — pure default config)"],
        "commented_out_display_lines": commented[:10],
        "graphics_driver": (
            "KMS (vc4-kms-v3d) — legacy hdmi_*/tvservice settings mostly ignored"
            if kms and "fkms" not in kms else
            "Fake-KMS (vc4-fkms-v3d) — legacy hdmi_* settings still honored"
            if kms else
            "Legacy framebuffer — no KMS overlay active"
        ),
    }
    cmdline = run(client, "cat /boot/firmware/cmdline.txt 2>/dev/null || cat /boot/cmdline.txt")
    if "fbcon=map" in cmdline:
        result["fbcon_mapping"] = re.search(r"fbcon=map:\S+", cmdline).group(0)
    return result


def check_framebuffer(client) -> dict:
    fbs = run(client, "for f in /sys/class/graphics/fb*; do "
                      "echo \"$f: $(cat $f/name 2>/dev/null) "
                      "$(cat $f/virtual_size 2>/dev/null)\"; done 2>/dev/null")
    con2fb = run(client, "con2fbmap 1 2>/dev/null || echo 'con2fbmap unavailable'")
    return {
        "framebuffers": fbs or "no framebuffers found",
        "console_mapping": con2fb,
        "hint": "SPI panels appear as fb_<controller> (e.g. fb_ili9486) usually on fb1; "
                "vc4drmfb/BCM2708 FB is the GPU (HDMI/DSI) framebuffer",
    }


def check_kms(client) -> dict:
    kmsprint = run(client, "kmsprint 2>/dev/null | head -40 || echo 'kmsprint unavailable'")
    modes = run(client, "for c in /sys/class/drm/card*-*; do "
                        "echo \"$c: $(cat $c/status 2>/dev/null) "
                        "$(cat $c/enabled 2>/dev/null)\"; done 2>/dev/null")
    return {"kmsprint": kmsprint, "drm_connectors": modes or "no DRM connectors"}


def check_spi(client) -> dict:
    spidev = run(client, "ls -la /dev/spidev* 2>/dev/null || echo 'no spidev devices'")
    modules = run(client, "lsmod | grep -E 'spi|fbtft|ili|st77|ssd1' || echo 'no SPI/fbtft modules loaded'")
    result = {"spidev_devices": spidev, "kernel_modules": modules}
    if "no spidev" in spidev:
        result["verdict"] = ("⚠ SPI bus not exposed — ensure dtparam=spi=on in config.txt "
                             "(or that the display overlay enables it) and reboot")
    else:
        result["verdict"] = "OK — SPI bus present"
    return result


def check_touch(client) -> dict:
    devices = run(client, "cat /proc/bus/input/devices 2>/dev/null | "
                          "grep -B1 -A4 -i -E 'touch|ads7846|goodix|ft5|gt9|stmpe' | head -40")
    event_nodes = run(client, "ls /dev/input/by-path/ 2>/dev/null | grep -i -E 'touch|event' || ls /dev/input/event* 2>/dev/null")
    xinput = run(client, "DISPLAY=:0 xinput list 2>/dev/null | grep -i -E 'touch|ads|goodix|ft5' || echo 'xinput unavailable/no X'")
    matrix = run(client, "DISPLAY=:0 xinput list-props "
                         "\"$(DISPLAY=:0 xinput list --name-only 2>/dev/null | grep -i -m1 touch)\" "
                         "2>/dev/null | grep -i 'transformation' || echo '(no transform set)'")
    return {
        "input_devices": devices or "no touch devices found in /proc/bus/input/devices",
        "event_nodes": event_nodes,
        "xinput": xinput,
        "x11_transformation_matrix": matrix,
    }


def check_hdmi(client) -> dict:
    connectors = run(client, "for c in /sys/class/drm/card*-HDMI*; do "
                             "echo \"$c: $(cat $c/status 2>/dev/null)\"; done 2>/dev/null")
    edid = run(client, "ls -la /sys/class/drm/card*-HDMI*/edid 2>/dev/null && "
                       "stat -c '%s bytes' /sys/class/drm/card*-HDMI*/edid 2>/dev/null | head -2")
    tvservice = run(client, "tvservice -s 2>/dev/null || echo 'tvservice unavailable (normal on KMS)'")
    display_power = run(client, "vcgencmd display_power 2>/dev/null || echo unavailable")
    result = {
        "hdmi_connectors": connectors or "no HDMI connectors via DRM (legacy driver?)",
        "edid": edid,
        "tvservice_legacy": tvservice,
        "display_power": display_power,
    }
    if connectors and "disconnected" in connectors and "connected" not in connectors.replace("disconnected", ""):
        result["verdict"] = ("⚠ All HDMI connectors report disconnected — cable/port issue "
                             "or display off at boot; consider hdmi_force_hotplug=1")
    return result


def check_klipperscreen(client) -> dict:
    state = run(client, "systemctl is-active KlipperScreen 2>/dev/null")
    unit = run(client, "systemctl status KlipperScreen --no-pager -n 8 2>/dev/null | tail -12")
    log = run(client, "tail -30 ~/printer_data/logs/KlipperScreen.log 2>/dev/null || "
                      "tail -30 /tmp/KlipperScreen.log 2>/dev/null || echo 'no KlipperScreen log found'")
    xorg_err = run(client, "grep -i -E '\\(EE\\)|fatal' /var/log/Xorg.0.log 2>/dev/null | tail -8")
    result = {
        "service_state": state or "not installed",
        "service_status_tail": unit,
        "log_tail": log,
        "xorg_errors": xorg_err or "(none)",
    }
    if state == "failed" or "error" in log.lower():
        result["verdict"] = ("⚠ KlipperScreen unhealthy — the log tail above names the "
                             "failure. Common: no DISPLAY (Xorg), Moonraker connection "
                             "refused, GTK/panel init errors.")
    elif state == "active":
        result["verdict"] = "OK — service active"
    return result


def check_backlight(client) -> dict:
    sysfs = run(client, "for b in /sys/class/backlight/*; do "
                        "echo \"$b: brightness=$(cat $b/brightness) "
                        "max=$(cat $b/max_brightness) actual=$(cat $b/actual_brightness 2>/dev/null)\"; "
                        "done 2>/dev/null")
    return {"backlight_devices": sysfs or "no /sys/class/backlight devices "
            "(SPI panels often control backlight via overlay GPIO instead)"}


def check_dmesg(client) -> dict:
    display = run(client, "dmesg | grep -i -E 'fbtft|ili9|st77|ssd1|vc4|drm|hdmi|edid|"
                          "ads7846|goodix|ft5406|panel|backlight' | tail -25")
    return {"display_related_dmesg": display or "(no display-related kernel messages)"}


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
    "boot-config": check_boot_config,
    "framebuffer": check_framebuffer,
    "kms": check_kms,
    "spi": check_spi,
    "touch": check_touch,
    "hdmi": check_hdmi,
    "klipperscreen": check_klipperscreen,
    "backlight": check_backlight,
    "dmesg": check_dmesg,
}


def main():
    parser = argparse.ArgumentParser(description="SPI/HDMI/DSI display + KlipperScreen diagnostics via SSH")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Pi host/IP (or PRINTER_SSH_HOST)")
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--key-file", default=DEFAULT_KEY)
    parser.add_argument("--check", default="all", choices=["all"] + list(CHECKS.keys()))
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
