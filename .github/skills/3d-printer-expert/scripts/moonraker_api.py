#!/usr/bin/env python3
"""
Moonraker API Client — Queries Moonraker's REST API (the API server used by
Mainsail, Fluidd, and KlipperScreen) for Klipper state, printer objects,
temperatures, job status, update manager state, and machine control.

Usage:
    python moonraker_api.py --action info --host 192.168.1.100
    python moonraker_api.py --action server
    python moonraker_api.py --action klippy-state
    python moonraker_api.py --action temps
    python moonraker_api.py --action query --objects "toolhead,extruder,heater_bed"
    python moonraker_api.py --action gcode --script "M115"
    python moonraker_api.py --action gcode-history --count 50
    python moonraker_api.py --action print-status
    python moonraker_api.py --action history --limit 10
    python moonraker_api.py --action sysinfo
    python moonraker_api.py --action proc-stats
    python moonraker_api.py --action update-status
    python moonraker_api.py --action power
    python moonraker_api.py --action files
    python moonraker_api.py --action restart-klipper
    python moonraker_api.py --action firmware-restart
    python moonraker_api.py --action restart-service --service moonraker
    python moonraker_api.py --action websocket-test
    python moonraker_api.py --action diagnose
"""

import argparse
import json
import os
import sys
from typing import Optional
from urllib.parse import quote

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package required. pip install requests", file=sys.stderr)
    sys.exit(1)


# ── Defaults from environment ─────────────────────────────────────────────────
DEFAULT_HOST = os.environ.get("MOONRAKER_HOST", os.environ.get("OCTOPRINT_IP", "localhost"))
DEFAULT_PORT = os.environ.get("MOONRAKER_PORT", "7125")
DEFAULT_API_KEY = os.environ.get("MOONRAKER_API_KEY", "")

# Default printer objects for a quick health query
DEFAULT_QUERY_OBJECTS = [
    "toolhead", "extruder", "heater_bed", "print_stats", "idle_timeout",
    "virtual_sdcard", "display_status", "fan", "system_stats",
]


class MoonrakerClient:
    """Minimal Moonraker REST API client for diagnostics."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: str = DEFAULT_PORT,
        api_key: str = DEFAULT_API_KEY,
        timeout: int = 10,
    ):
        self.base_url = f"http://{host}:{port}"
        self.timeout = timeout
        self.session = requests.Session()
        if api_key:
            self.session.headers.update({"X-Api-Key": api_key})

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
            resp.raise_for_status()
            data = resp.json()
            # Moonraker wraps responses in {"result": ...}
            return data.get("result", data)
        except requests.exceptions.ConnectionError:
            return {"error": f"Cannot connect to Moonraker at {url}. "
                             "Is moonraker.service running? (port 7125 by default)"}
        except requests.exceptions.Timeout:
            return {"error": f"Timeout connecting to {url}"}
        except requests.exceptions.HTTPError as e:
            body = ""
            try:
                body = e.response.json().get("error", {}).get("message", "")
            except Exception:
                body = e.response.text[:200] if e.response is not None else ""
            return {"error": f"HTTP {e.response.status_code if e.response is not None else '?'}: {body}"}
        except ValueError:
            return {"error": f"Non-JSON response from {url} — is this really Moonraker?"}

    def _get(self, path: str) -> dict:
        return self._request("GET", path)

    def _post(self, path: str) -> dict:
        return self._request("POST", path)

    # ── Endpoints ─────────────────────────────────────────────────────────────

    def printer_info(self) -> dict:
        """Klipper host info — state, software version, hostname."""
        return self._get("/printer/info")

    def server_info(self) -> dict:
        """Moonraker server info — klippy state, loaded components, warnings."""
        return self._get("/server/info")

    def server_config(self) -> dict:
        return self._get("/server/config")

    def objects_list(self) -> dict:
        return self._get("/printer/objects/list")

    def objects_query(self, objects: list) -> dict:
        query = "&".join(quote(o) for o in objects)
        return self._get(f"/printer/objects/query?{query}")

    def temperature_store(self) -> dict:
        return self._get("/server/temperature_store")

    def gcode_script(self, script: str) -> dict:
        return self._post(f"/printer/gcode/script?script={quote(script)}")

    def gcode_store(self, count: int = 100) -> dict:
        return self._get(f"/server/gcode_store?count={count}")

    def job_history(self, limit: int = 10) -> dict:
        return self._get(f"/server/history/list?limit={limit}")

    def system_info(self) -> dict:
        return self._get("/machine/system_info")

    def proc_stats(self) -> dict:
        return self._get("/machine/proc_stats")

    def update_status(self) -> dict:
        return self._get("/machine/update/status")

    def power_devices(self) -> dict:
        return self._get("/machine/device_power/devices")

    def files_list(self, root: str = "gcodes") -> dict:
        return self._get(f"/server/files/list?root={quote(root)}")

    def restart_klipper(self) -> dict:
        return self._post("/printer/restart")

    def firmware_restart(self) -> dict:
        return self._post("/printer/firmware_restart")

    def restart_service(self, service: str) -> dict:
        return self._post(f"/machine/services/restart?service={quote(service)}")


# ── Output formatting ─────────────────────────────────────────────────────────

def _print(data: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, indent=2, default=str))
        return
    print(json.dumps(data, indent=2, default=str))


def _fmt_temps(query_result: dict) -> str:
    """Human-readable temperature summary from an objects query."""
    status = query_result.get("status", {})
    lines = ["── Temperatures ──"]
    for name, obj in status.items():
        if not isinstance(obj, dict):
            continue
        if "temperature" in obj:
            actual = obj.get("temperature")
            target = obj.get("target", "—")
            power = obj.get("power", None)
            line = f"  {name:<24} {actual}°C / target {target}°C"
            if power is not None:
                line += f"  (power {round(power * 100)}%)"
            lines.append(line)
    if len(lines) == 1:
        lines.append("  (no temperature-capable objects reported)")
    return "\n".join(lines)


def action_klippy_state(client: MoonrakerClient) -> dict:
    """Summarize klippy state + warnings — the first thing to check."""
    server = client.server_info()
    if "error" in server:
        return server
    info = client.printer_info()
    result = {
        "klippy_state": server.get("klippy_state"),
        "klippy_connected": server.get("klippy_connected"),
        "moonraker_version": server.get("moonraker_version"),
        "warnings": server.get("warnings", []),
        "failed_components": server.get("failed_components", []),
        "klipper_version": info.get("software_version") if "error" not in info else None,
        "state_message": info.get("state_message") if "error" not in info else info.get("error"),
    }
    return result


def action_diagnose(client: MoonrakerClient) -> dict:
    """Full health sweep: server info, klippy state, temps, print status, updates."""
    report: dict = {}
    server = client.server_info()
    if "error" in server:
        return {"error": server["error"],
                "hint": "Moonraker unreachable — check `systemctl status moonraker`, "
                        "port 7125 open, and trusted_clients/cors in moonraker.conf"}
    report["klippy"] = action_klippy_state(client)
    query = client.objects_query(["extruder", "heater_bed", "print_stats",
                                  "toolhead", "system_stats", "virtual_sdcard"])
    if "error" not in query:
        status = query.get("status", {})
        ps = status.get("print_stats", {})
        report["print"] = {
            "state": ps.get("state"),
            "filename": ps.get("filename"),
            "print_duration_s": ps.get("print_duration"),
            "progress": status.get("virtual_sdcard", {}).get("progress"),
        }
        report["temperatures"] = {
            name: {"actual": obj.get("temperature"), "target": obj.get("target")}
            for name, obj in status.items()
            if isinstance(obj, dict) and "temperature" in obj
        }
        sysload = status.get("system_stats", {})
        report["host_load"] = {
            "cputime": sysload.get("cputime"),
            "memavail_kb": sysload.get("memavail"),
        }
    proc = client.proc_stats()
    if "error" not in proc:
        throttled = proc.get("throttled_state", {})
        report["pi_throttled_state"] = throttled
        if throttled.get("bits", 0):
            report["pi_throttled_warning"] = (
                "Non-zero throttled state — Pi has seen undervoltage or thermal "
                "throttling. Run pi_system_diagnostics.py for a full decode."
            )
    updates = client.update_status()
    if "error" not in updates:
        version_info = updates.get("version_info", {})
        report["components"] = {
            name: {"version": v.get("version"), "remote": v.get("remote_version")}
            for name, v in version_info.items() if isinstance(v, dict)
        }
    return report


def action_websocket_test(host: str, port: str, api_key: str) -> dict:
    """Test Moonraker's JSON-RPC WebSocket (what Mainsail/Fluidd actually use)."""
    try:
        import websocket  # websocket-client
    except ImportError:
        return {"error": "'websocket-client' package required. pip install websocket-client"}
    url = f"ws://{host}:{port}/websocket"
    try:
        ws = websocket.create_connection(url, timeout=10)
        ws.send(json.dumps({"jsonrpc": "2.0", "method": "server.info", "id": 1}))
        raw = ws.recv()
        ws.close()
        resp = json.loads(raw)
        result = resp.get("result", {})
        return {
            "websocket": "OK",
            "url": url,
            "klippy_state": result.get("klippy_state"),
            "moonraker_version": result.get("moonraker_version"),
        }
    except Exception as e:
        return {"websocket": "FAILED", "url": url, "error": str(e),
                "hint": "If REST works but WebSocket fails, check reverse-proxy "
                        "(nginx) upgrade headers and moonraker CORS settings — "
                        "this is the classic 'Mainsail stuck on connecting' cause."}


def main():
    parser = argparse.ArgumentParser(description="Moonraker REST API diagnostics client")
    parser.add_argument("--action", required=True,
                        choices=["info", "server", "klippy-state", "temps", "query",
                                 "gcode", "gcode-history", "print-status", "history",
                                 "sysinfo", "proc-stats", "update-status", "power",
                                 "files", "restart-klipper", "firmware-restart",
                                 "restart-service", "websocket-test", "diagnose",
                                 "objects-list", "temp-store", "config"])
    parser.add_argument("--host", default=DEFAULT_HOST, help="Moonraker host/IP")
    parser.add_argument("--port", default=DEFAULT_PORT, help="Moonraker port (default 7125)")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="Moonraker API key (if auth enabled)")
    parser.add_argument("--objects", default="", help="Comma-separated printer objects for --action query")
    parser.add_argument("--script", default="", help="G-code for --action gcode")
    parser.add_argument("--service", default="", help="Service name for --action restart-service")
    parser.add_argument("--count", type=int, default=100, help="Entries for gcode-history")
    parser.add_argument("--limit", type=int, default=10, help="Entries for job history")
    parser.add_argument("--root", default="gcodes", help="File root for --action files")
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--json", action="store_true", help="Raw JSON output")
    args = parser.parse_args()

    client = MoonrakerClient(args.host, args.port, args.api_key, args.timeout)

    if args.action == "info":
        result = client.printer_info()
    elif args.action == "server":
        result = client.server_info()
    elif args.action == "config":
        result = client.server_config()
    elif args.action == "klippy-state":
        result = action_klippy_state(client)
    elif args.action == "objects-list":
        result = client.objects_list()
    elif args.action == "query":
        objects = ([o.strip() for o in args.objects.split(",") if o.strip()]
                   or DEFAULT_QUERY_OBJECTS)
        result = client.objects_query(objects)
    elif args.action == "temps":
        result = client.objects_query(["extruder", "extruder1", "heater_bed",
                                       "temperature_sensor chamber",
                                       "temperature_host"])
        if "error" not in result and not args.json:
            print(_fmt_temps(result))
            return
    elif args.action == "temp-store":
        result = client.temperature_store()
    elif args.action == "gcode":
        if not args.script:
            print("ERROR: --script required for --action gcode", file=sys.stderr)
            sys.exit(1)
        result = client.gcode_script(args.script)
    elif args.action == "gcode-history":
        result = client.gcode_store(args.count)
    elif args.action == "print-status":
        result = client.objects_query(["print_stats", "virtual_sdcard",
                                       "display_status", "idle_timeout"])
    elif args.action == "history":
        result = client.job_history(args.limit)
    elif args.action == "sysinfo":
        result = client.system_info()
    elif args.action == "proc-stats":
        result = client.proc_stats()
    elif args.action == "update-status":
        result = client.update_status()
    elif args.action == "power":
        result = client.power_devices()
    elif args.action == "files":
        result = client.files_list(args.root)
    elif args.action == "restart-klipper":
        result = client.restart_klipper()
    elif args.action == "firmware-restart":
        result = client.firmware_restart()
    elif args.action == "restart-service":
        if not args.service:
            print("ERROR: --service required (e.g. moonraker, klipper, nginx)", file=sys.stderr)
            sys.exit(1)
        result = client.restart_service(args.service)
    elif args.action == "websocket-test":
        result = action_websocket_test(args.host, args.port, args.api_key)
    elif args.action == "diagnose":
        result = action_diagnose(client)
    else:
        parser.error(f"Unknown action: {args.action}")
        return

    _print(result, args.json)
    if isinstance(result, dict) and "error" in result:
        sys.exit(2)


if __name__ == "__main__":
    main()
