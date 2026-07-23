#!/usr/bin/env python3
"""
Mainsail Diagnostics — Debugs the Mainsail web UI stack: nginx static hosting,
Moonraker API reachability, WebSocket upgrade, CORS/trusted-client config,
update manager state, and the classic "stuck on connecting" failure modes.

Mainsail is a static web app served by nginx (port 80 by default) that talks
to Moonraker (port 7125) over REST + JSON-RPC WebSocket. Almost every Mainsail
problem is actually an nginx, Moonraker, or network problem — this script
checks each layer in order.

Usage:
    python mainsail_diagnostics.py --host 192.168.1.100                # full check
    python mainsail_diagnostics.py --host 192.168.1.100 --check http
    python mainsail_diagnostics.py --host 192.168.1.100 --check moonraker
    python mainsail_diagnostics.py --host 192.168.1.100 --check websocket
    python mainsail_diagnostics.py --host 192.168.1.100 --check ssh    # nginx/moonraker services + conf via SSH
    python mainsail_diagnostics.py --failures                          # known failure-mode reference
"""

import argparse
import json
import os
import sys

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package required. pip install requests", file=sys.stderr)
    sys.exit(1)


DEFAULT_HOST = os.environ.get("MOONRAKER_HOST", os.environ.get("PRINTER_SSH_HOST",
               os.environ.get("OCTOPRINT_IP", "localhost")))
DEFAULT_HTTP_PORT = os.environ.get("MAINSAIL_PORT", "80")
DEFAULT_MOONRAKER_PORT = os.environ.get("MOONRAKER_PORT", "7125")


# ── Known failure modes (knowledge base) ──────────────────────────────────────

FAILURE_MODES = {
    "blank_page": {
        "symptom": "Browser shows a blank/white page at the printer's IP",
        "causes": [
            "nginx not running or not installed",
            "Mainsail files missing from web root (~/mainsail)",
            "nginx site config points at wrong root directory",
            "Browser cached a broken build — hard refresh (Ctrl+Shift+R)",
        ],
        "checks": [
            "curl -I http://<ip>/ — expect 200 with text/html",
            "ssh: systemctl status nginx",
            "ssh: ls ~/mainsail — index.html must exist",
            "ssh: sudo nginx -t — validate config syntax",
        ],
    },
    "cannot_connect_moonraker": {
        "symptom": "Mainsail loads but shows 'Cannot connect to Moonraker' or spins on connecting",
        "causes": [
            "moonraker.service not running or crashed on start",
            "WebSocket upgrade blocked — nginx missing proxy_set_header Upgrade/Connection",
            "CORS rejection — client origin not in moonraker.conf [authorization] cors_domains",
            "Browsing via a hostname/port not covered by trusted_clients or cors_domains",
        ],
        "checks": [
            "curl http://<ip>:7125/server/info — Moonraker up?",
            "moonraker_api.py --action websocket-test — WebSocket handshake OK?",
            "ssh: systemctl status moonraker; tail ~/printer_data/logs/moonraker.log",
            "moonraker.conf: [authorization] must include cors_domains entry like *://<ip> or *.local",
        ],
    },
    "502_bad_gateway": {
        "symptom": "nginx returns 502 Bad Gateway on API routes",
        "causes": [
            "Moonraker down (nginx can't reach 127.0.0.1:7125)",
            "Moonraker crashed on a bad moonraker.conf — check its log",
            "Wrong upstream port in nginx config",
        ],
        "checks": [
            "ssh: systemctl status moonraker",
            "ssh: journalctl -u moonraker -n 50",
            "ssh: grep -r 'proxy_pass' /etc/nginx/sites-enabled/",
        ],
    },
    "klippy_disconnected": {
        "symptom": "Mainsail connects but shows 'Klippy: Disconnected' or 'Startup'/'Error' state",
        "causes": [
            "Klipper service not running, or klippy.log shows a config error",
            "Wrong klippy_uds_address in moonraker.conf (default ~/printer_data/comms/klippy.sock)",
            "printer.cfg syntax error preventing Klipper startup",
        ],
        "checks": [
            "moonraker_api.py --action klippy-state",
            "klipper_log_parser.py --days 1 — read the actual error",
            "ssh: systemctl status klipper",
        ],
    },
    "update_manager_errors": {
        "symptom": "Update manager shows 'dirty' / 'invalid' repos or fails to update",
        "causes": [
            "Local git changes in klipper/moonraker/mainsail directories",
            "Detached HEAD or unofficial remote (common on forks like klipper_IDEX)",
            "Network/DNS failure on the Pi",
        ],
        "checks": [
            "moonraker_api.py --action update-status",
            "ssh: cd ~/klipper && git status",
            "For Fracktal forks: update_manager entries must point at the FracktalWorks remote",
        ],
    },
    "webcam_not_showing": {
        "symptom": "Webcam feed missing or frozen in Mainsail",
        "causes": [
            "crowsnest/webcamd not running",
            "Wrong stream URL in Mainsail webcam settings (/webcam/?action=stream)",
            "Camera not detected (check `libcamera-hello --list-cameras` / ls /dev/video*)",
        ],
        "checks": [
            "ssh: systemctl status crowsnest (or webcamd)",
            "curl -I http://<ip>/webcam/?action=snapshot",
            "ssh: ls /dev/video*",
        ],
    },
    "slow_ui": {
        "symptom": "Mainsail is sluggish, temperature graph stutters, gcode viewer hangs",
        "causes": [
            "Pi under memory pressure or throttled (undervoltage)",
            "Very large gcode files with viewer enabled",
            "SD card failing — I/O stalls",
        ],
        "checks": [
            "moonraker_api.py --action proc-stats — check throttled_state",
            "pi_system_diagnostics.py --check all",
        ],
    },
}


# ── HTTP-layer checks ─────────────────────────────────────────────────────────

def check_http(host: str, port: str) -> dict:
    """Is nginx serving the Mainsail frontend?"""
    url = f"http://{host}:{port}/"
    result: dict = {"url": url}
    try:
        resp = requests.get(url, timeout=10)
        result["status_code"] = resp.status_code
        result["server"] = resp.headers.get("Server", "")
        body = resp.text[:4000].lower()
        result["looks_like_mainsail"] = "mainsail" in body
        result["looks_like_fluidd"] = "fluidd" in body
        if resp.status_code == 200 and result["looks_like_mainsail"]:
            result["verdict"] = "OK — Mainsail frontend served"
        elif resp.status_code == 200:
            result["verdict"] = ("HTTP 200 but page doesn't look like Mainsail — "
                                 "check nginx root directory")
        elif resp.status_code == 502:
            result["verdict"] = "502 Bad Gateway — see failure mode '502_bad_gateway'"
        else:
            result["verdict"] = f"Unexpected HTTP {resp.status_code}"
    except requests.exceptions.ConnectionError:
        result["verdict"] = ("UNREACHABLE — nginx down, wrong port, or network issue. "
                             "ssh: systemctl status nginx")
    except requests.exceptions.Timeout:
        result["verdict"] = "TIMEOUT — host up but web server not responding"
    return result


def check_moonraker(host: str, port: str) -> dict:
    """Is Moonraker answering REST on 7125?"""
    url = f"http://{host}:{port}/server/info"
    result: dict = {"url": url}
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        info = resp.json().get("result", {})
        result["moonraker_version"] = info.get("moonraker_version")
        result["klippy_state"] = info.get("klippy_state")
        result["klippy_connected"] = info.get("klippy_connected")
        result["warnings"] = info.get("warnings", [])
        result["failed_components"] = info.get("failed_components", [])
        if info.get("klippy_state") == "ready":
            result["verdict"] = "OK — Moonraker up, Klipper ready"
        else:
            result["verdict"] = (f"Moonraker up but klippy_state="
                                 f"{info.get('klippy_state')} — parse klippy.log next")
    except requests.exceptions.ConnectionError:
        result["verdict"] = ("UNREACHABLE — moonraker.service down or port blocked. "
                             "ssh: systemctl status moonraker && "
                             "tail ~/printer_data/logs/moonraker.log")
    except Exception as e:
        result["verdict"] = f"ERROR — {e}"
    return result


def check_websocket(host: str, port: str) -> dict:
    """Can we complete the JSON-RPC WebSocket handshake Mainsail depends on?"""
    try:
        import websocket  # websocket-client
    except ImportError:
        return {"verdict": "SKIPPED — pip install websocket-client to enable"}
    url = f"ws://{host}:{port}/websocket"
    result: dict = {"url": url}
    try:
        ws = websocket.create_connection(url, timeout=10)
        ws.send(json.dumps({"jsonrpc": "2.0", "method": "server.info", "id": 1}))
        resp = json.loads(ws.recv())
        ws.close()
        result["klippy_state"] = resp.get("result", {}).get("klippy_state")
        result["verdict"] = "OK — WebSocket handshake + JSON-RPC round-trip succeeded"
    except Exception as e:
        result["verdict"] = (f"FAILED — {e}. If REST works but this fails, the "
                             "cause is usually nginx missing WebSocket upgrade "
                             "headers or Moonraker CORS rejecting the origin.")
    return result


def check_versions(host: str, port: str) -> dict:
    """Mainsail/Klipper/Moonraker versions via update manager."""
    url = f"http://{host}:{port}/machine/update/status"
    result: dict = {}
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        vi = resp.json().get("result", {}).get("version_info", {})
        for name, v in vi.items():
            if isinstance(v, dict):
                result[name] = {
                    "version": v.get("version"),
                    "remote_version": v.get("remote_version"),
                    "dirty": v.get("is_dirty"),
                    "valid": v.get("is_valid", True),
                }
        result["verdict"] = "OK"
    except Exception as e:
        result["verdict"] = f"Could not read update status — {e}"
    return result


# ── SSH-layer checks (optional) ───────────────────────────────────────────────

def check_ssh_layer(host: str, user: str, password: str, key_file: str) -> dict:
    """Check nginx + moonraker services and configs directly on the Pi."""
    try:
        import paramiko
    except ImportError:
        return {"verdict": "SKIPPED — pip install paramiko to enable SSH checks"}

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
        return {"verdict": f"SSH FAILED — {e}"}

    def run(cmd: str) -> str:
        _, stdout, stderr = client.exec_command(cmd, timeout=20)
        out = stdout.read().decode(errors="replace").strip()
        err = stderr.read().decode(errors="replace").strip()
        return out or err

    result = {
        "nginx_service": run("systemctl is-active nginx 2>/dev/null || echo not-found"),
        "moonraker_service": run("systemctl is-active moonraker 2>/dev/null || echo not-found"),
        "klipper_service": run("systemctl is-active klipper 2>/dev/null || echo not-found"),
        "nginx_config_test": run("sudo -n nginx -t 2>&1 || nginx -t 2>&1 | tail -2"),
        "mainsail_root": run("ls ~/mainsail/index.html 2>/dev/null || "
                             "ls /home/pi/mainsail/index.html 2>/dev/null || echo missing"),
        "moonraker_conf_auth": run("grep -A6 '\\[authorization\\]' "
                                   "~/printer_data/config/moonraker.conf 2>/dev/null | head -12"),
        "moonraker_log_tail": run("tail -15 ~/printer_data/logs/moonraker.log 2>/dev/null"),
    }
    client.close()
    return result


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


def main():
    parser = argparse.ArgumentParser(description="Mainsail web stack diagnostics")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Printer host/IP")
    parser.add_argument("--http-port", default=DEFAULT_HTTP_PORT, help="Mainsail/nginx port (default 80)")
    parser.add_argument("--moonraker-port", default=DEFAULT_MOONRAKER_PORT, help="Moonraker port (default 7125)")
    parser.add_argument("--check", default="all",
                        choices=["all", "http", "moonraker", "websocket", "versions", "ssh"])
    parser.add_argument("--ssh-user", default=os.environ.get("PRINTER_SSH_USER", "pi"))
    parser.add_argument("--ssh-password", default=os.environ.get("PRINTER_SSH_PASSWORD", ""))
    parser.add_argument("--ssh-key", default=os.environ.get("PRINTER_SSH_KEY", ""))
    parser.add_argument("--failures", nargs="?", const="", default=None,
                        help="Print known failure-mode reference (optionally one key)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.failures is not None:
        print_failures(args.failures)
        return

    report: dict = {"host": args.host}
    if args.check in ("all", "http"):
        report["http_frontend"] = check_http(args.host, args.http_port)
    if args.check in ("all", "moonraker"):
        report["moonraker_rest"] = check_moonraker(args.host, args.moonraker_port)
    if args.check in ("all", "websocket"):
        report["moonraker_websocket"] = check_websocket(args.host, args.moonraker_port)
    if args.check in ("all", "versions"):
        report["versions"] = check_versions(args.host, args.moonraker_port)
    if args.check == "ssh":
        report["ssh_layer"] = check_ssh_layer(args.host, args.ssh_user,
                                              args.ssh_password, args.ssh_key)

    print(json.dumps(report, indent=2, default=str))

    # Overall verdict for quick triage
    verdicts = [v.get("verdict", "") for v in report.values() if isinstance(v, dict)]
    failed = [v for v in verdicts if v and not v.startswith(("OK", "SKIPPED"))]
    if failed:
        print(f"\n⚠ {len(failed)} layer(s) failing — see verdicts above. "
              "Run with --failures for the failure-mode reference.", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
