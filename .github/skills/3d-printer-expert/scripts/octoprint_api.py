#!/usr/bin/env python3
"""
OctoPrint API Client — Queries OctoPrint's REST API for printer status,
connection info, file management, job control, and settings.

Usage:
    python octoprint_api.py --action status --ip 192.168.1.100 --api-key ABC123
    python octoprint_api.py --action connection --port /tmp/printer --baudrate 115200
    python octoprint_api.py --action files --location local
    python octoprint_api.py --action job
    python octoprint_api.py --action printer --command jog --x 10 --y 0 --z 0
    python octoprint_api.py --action system
    python octoprint_api.py --action version
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
DEFAULT_IP = os.environ.get("OCTOPRINT_IP", "localhost")
DEFAULT_PORT = os.environ.get("OCTOPRINT_PORT", "5000")
DEFAULT_API_KEY = os.environ.get("OCTOPRINT_API_KEY", "")


class OctoPrintClient:
    """Minimal OctoPrint REST API client for diagnostics."""

    def __init__(
        self,
        ip: str = DEFAULT_IP,
        port: str = DEFAULT_PORT,
        api_key: str = DEFAULT_API_KEY,
        timeout: int = 10,
    ):
        self.base_url = f"http://{ip}:{port}"
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "X-Api-Key": api_key,
            "Content-Type": "application/json",
        })

    def _get(self, path: str) -> dict:
        """GET request to OctoPrint API."""
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.ConnectionError:
            return {"error": f"Could not connect to OctoPrint at {self.base_url}"}
        except requests.exceptions.Timeout:
            return {"error": f"Connection timed out ({self.timeout}s)"}
        except requests.exceptions.HTTPError as e:
            return {
                "error": f"HTTP {resp.status_code}: {resp.reason}",
                "body": resp.text[:500] if resp.text else "",
            }
        except Exception as e:
            return {"error": str(e)}

    def _post(self, path: str, data: Optional[dict] = None) -> dict:
        """POST request to OctoPrint API."""
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.post(
                url, json=data or {}, timeout=self.timeout
            )
            resp.raise_for_status()
            if resp.status_code == 204:
                return {"success": True}
            return resp.json() if resp.text else {"success": True}
        except requests.exceptions.ConnectionError:
            return {"error": f"Could not connect to OctoPrint at {self.base_url}"}
        except requests.exceptions.Timeout:
            return {"error": f"Connection timed out ({self.timeout}s)"}
        except requests.exceptions.HTTPError as e:
            return {
                "error": f"HTTP {resp.status_code}: {resp.reason}",
                "body": resp.text[:500] if resp.text else "",
            }
        except Exception as e:
            return {"error": str(e)}

    # ── API Methods ───────────────────────────────────────────────────────

    def version(self) -> dict:
        """Get OctoPrint version and API info."""
        return self._get("/api/version")

    def server_info(self) -> dict:
        """Get server information."""
        return self._get("/api/server")

    def connection(self) -> dict:
        """Get current connection settings."""
        return self._get("/api/connection")

    def connect_printer(
        self, port: str = "/tmp/printer", baudrate: int = 115200,
        printer_profile: str = "_default", save: bool = False,
        autoconnect: bool = False,
    ) -> dict:
        """Issue a connect command to OctoPrint."""
        data = {
            "command": "connect",
            "port": port,
            "baudrate": baudrate,
            "printerProfile": printer_profile,
            "save": save,
            "autoconnect": autoconnect,
        }
        return self._post("/api/connection", data)

    def disconnect_printer(self) -> dict:
        """Issue a disconnect command."""
        return self._post("/api/connection", {"command": "disconnect"})

    def printer_state(self, history: bool = False, limit: int = 10) -> dict:
        """Get current printer state. Optionally include temperature history."""
        path = "/api/printer"
        params = []
        if history:
            params.append(f"history=true&limit={limit}")
        if params:
            path += "?" + "&".join(params)
        return self._get(path)

    def job(self) -> dict:
        """Get current job information."""
        return self._get("/api/job")

    def job_command(self, command: str) -> dict:
        """Send a command to the current job (start, cancel, pause, restart)."""
        valid = ("start", "cancel", "pause", "restart")
        if command not in valid:
            return {"error": f"Invalid job command: {command}. Use one of {valid}"}
        return self._post("/api/job", {"command": command})

    def files(
        self, location: str = "local", recursive: bool = False,
    ) -> dict:
        """List files on the printer."""
        path = f"/api/files/{quote(location, safe='')}"
        params = []
        if recursive:
            params.append("recursive=true")
        if params:
            path += "?" + "&".join(params)
        return self._get(path)

    def settings(self) -> dict:
        """Get current OctoPrint settings."""
        return self._get("/api/settings")

    def system_commands(self) -> dict:
        """List available system commands."""
        return self._get("/api/system/commands")

    def printer_profiles(self) -> dict:
        """List printer profiles."""
        return self._get("/api/printerprofiles")

    def logs(self) -> dict:
        """List available log files."""
        return self._get("/api/logs")


def format_output(data: dict, action: str) -> str:
    """Format API response into readable text."""
    if "error" in data:
        return f"ERROR: {data['error']}"

    lines = []
    lines.append("=" * 60)
    lines.append(f"OCTOPRINT API: {action.upper()}")
    lines.append("=" * 60)

    if action == "version":
        lines.append(f"Server: {data.get('server', 'N/A')}")
        lines.append(f"API: {data.get('api', 'N/A')}")
        lines.append(f"Text: {data.get('text', 'N/A')}")
    elif action == "connection":
        current = data.get("current", {})
        lines.append(f"State: {current.get('state', 'N/A')}")
        lines.append(f"Port: {current.get('port', 'N/A')}")
        lines.append(f"Baudrate: {current.get('baudrate', 'N/A')}")
        lines.append(f"Printer Profile: {current.get('printerProfile', 'N/A')}")
        options = data.get("options", {})
        if options:
            lines.append(f"Available ports: {', '.join(options.get('ports', []))}")
            lines.append(
                f"Available baudrates: {', '.join(map(str, options.get('baudrates', [])))}"
            )
    elif action == "printer":
        state = data.get("state", {})
        temps = data.get("temperature", {})
        lines.append(f"State: {state.get('text', 'N/A')}")
        flags = state.get("flags", {})
        if flags:
            lines.append("Flags:")
            for flag, val in flags.items():
                if val:
                    lines.append(f"  • {flag}")
        if temps:
            lines.append("Temperatures:")
            for heater, info in temps.items():
                actual = info.get("actual", "N/A")
                target = info.get("target", "N/A")
                lines.append(f"  {heater}: {actual}°C / {target}°C")
    elif action == "job":
        job_info = data.get("job", {})
        progress = data.get("progress", {})
        lines.append(f"File: {job_info.get('file', {}).get('name', 'N/A')}")
        lines.append(
            f"Estimated print time: {job_info.get('estimatedPrintTime', 'N/A')}s"
        )
        lines.append(f"Completion: {progress.get('completion', 'N/A')}%")
        lines.append(f"Print time: {progress.get('printTime', 'N/A')}s")
        lines.append(
            f"Print time left: {progress.get('printTimeLeft', 'N/A')}s"
        )
    elif action == "files":
        files_list = data.get("files", [])
        lines.append(f"File count: {len(files_list)}")
        for f in files_list[:20]:
            name = f.get("name", "N/A")
            size = f.get("size", 0)
            date = f.get("date", "N/A")
            lines.append(f"  {name} ({size} bytes, {date})")
        if len(files_list) > 20:
            lines.append(f"  ... and {len(files_list) - 20} more files")
    elif action == "settings":
        # Settings are massive; just show keys at top level
        lines.append("Settings sections:")
        for key in sorted(data.keys()):
            lines.append(f"  • {key}")
    elif action == "system":
        commands = data.get("system", {}).get("actions", [])
        lines.append("System commands:")
        for cmd in commands:
            lines.append(
                f"  • {cmd.get('name', 'N/A')} — {cmd.get('action', 'N/A')}"
            )
    else:
        lines.append(json.dumps(data, indent=2, default=str))

    lines.append("=" * 60)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Query OctoPrint REST API for diagnostics"
    )
    parser.add_argument(
        "--action",
        required=True,
        choices=[
            "status", "connection", "files", "job", "printer",
            "settings", "system", "version", "profiles", "logs",
            "connect", "disconnect",
        ],
        help="API action to perform",
    )
    parser.add_argument(
        "--ip", default=DEFAULT_IP, help=f"OctoPrint IP (default: {DEFAULT_IP})"
    )
    parser.add_argument(
        "--port", default=DEFAULT_PORT, help=f"OctoPrint port (default: {DEFAULT_PORT})"
    )
    parser.add_argument(
        "--api-key", default=DEFAULT_API_KEY, help="OctoPrint API key"
    )
    parser.add_argument(
        "--timeout", type=int, default=10, help="Request timeout in seconds"
    )
    # Connection args
    parser.add_argument(
        "--printer-port", default="/tmp/printer", help="Printer serial port"
    )
    parser.add_argument(
        "--baudrate", type=int, default=115200, help="Printer baudrate"
    )
    # File args
    parser.add_argument(
        "--location", default="local", help="File location (local/sdcard)"
    )
    parser.add_argument(
        "--recursive", action="store_true", help="List files recursively"
    )
    # Job args
    parser.add_argument(
        "--command",
        choices=["start", "cancel", "pause", "restart"],
        help="Job command to send",
    )
    # Output
    parser.add_argument(
        "--json", action="store_true", help="Output as raw JSON"
    )
    args = parser.parse_args()

    if not args.api_key:
        print(
            "WARNING: No API key provided. Set OCTOPRINT_API_KEY env var "
            "or use --api-key. Most endpoints require authentication.",
            file=sys.stderr,
        )

    client = OctoPrintClient(
        ip=args.ip,
        port=args.port,
        api_key=args.api_key,
        timeout=args.timeout,
    )

    action_map = {
        "version": client.version,
        "status": lambda: client.printer_state(history=True),
        "connection": client.connection,
        "files": lambda: client.files(
            location=args.location, recursive=args.recursive
        ),
        "job": client.job,
        "printer": client.printer_state,
        "settings": client.settings,
        "system": client.system_commands,
        "profiles": client.printer_profiles,
        "logs": client.logs,
    }

    if args.action == "connect":
        data = client.connect_printer(
            port=args.printer_port, baudrate=args.baudrate
        )
    elif args.action == "disconnect":
        data = client.disconnect_printer()
    elif args.action == "job" and args.command:
        data = client.job_command(args.command)
    elif args.action == "status":
        # Combined: connection info + printer state + job status
        print(format_output(client.connection(), "connection"))
        print()
        print(format_output(client.printer_state(history=True), "printer"))
        print()
        print(format_output(client.job(), "job"))
        return
    elif args.action in action_map:
        data = action_map[args.action]()
    else:
        print(f"Unknown action: {args.action}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(data, indent=2, default=str))
    else:
        print(format_output(data, args.action))

    if "error" in data:
        sys.exit(1)


if __name__ == "__main__":
    main()
