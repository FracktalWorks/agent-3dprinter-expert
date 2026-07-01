---
name: 3d-printer-expert
description: >
  Diagnose and fix 3D printer firmware/software issues — Klipper logs,
  OctoPrint API, printer.cfg analysis, MCU errors, thermistor problems,
  and ControlCenter codebase reference for application-level debugging.
when_to_use: >
  User asks about 3D printer troubleshooting, Klipper errors, OctoPrint
  issues, firmware configuration, print failures, hardware-software bugs,
  or ControlCenter application debugging.
authority: write
cost_tier: 1
version: 0.1.0
---

# 3D Printer Expert Skill

Diagnoses and fixes firmware and software issues across the full 3D printing
stack: Klipper firmware, OctoPrint, printer.cfg configuration, MCU
communication, sensors, and the ControlCenter PyQt5 application.

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/klipper_log_parser.py` | Parse klippy.log — extract errors, warnings, shutdown reasons, timing issues |
| `scripts/octoprint_api.py` | Query OctoPrint REST API — status, connection, files, job, settings |
| `scripts/firmware_analyzer.py` | Validate printer.cfg — MCU, thermistors, steppers, endstops, probes, macros, Fracktal conventions |
| `scripts/controlcenter_reference.py` | Search ControlCenter codebase for debugging patterns |
| `scripts/ssh_manager.py` | SSH into printer Pi — tail logs, restart services, execute commands, edit config keys |
| `scripts/visualize_data.py` | Visualize data — temperature graphs, MCU stats, print timelines, input shaper spectra |
| `scripts/remote_config_editor.py` | Safely edit printer.cfg remotely — backup, diff, validate, enable/disable includes, apply+restart |
| `scripts/klipper_docs.py` | Klipper documentation reference — commands, topics, troubleshooting, source links, Pi tools |

## Usage

```bash
# Parse Klipper logs for recent errors
python .github/skills/3d-printer-expert/scripts/klipper_log_parser.py --days 1

# Klipper documentation & diagnostics reference
python .github/skills/3d-printer-expert/scripts/klipper_docs.py --links
python .github/skills/3d-printer-expert/scripts/klipper_docs.py --topic bed_mesh
python .github/skills/3d-printer-expert/scripts/klipper_docs.py --command QUERY_ENDSTOPS
python .github/skills/3d-printer-expert/scripts/klipper_docs.py --search "pressure advance"
python .github/skills/3d-printer-expert/scripts/klipper_docs.py --diagnose heater_error
python .github/skills/3d-printer-expert/scripts/klipper_docs.py --list-commands

# Query OctoPrint API
python .github/skills/3d-printer-expert/scripts/octoprint_api.py --action status --ip 192.168.1.100 --api-key YOURKEY

# Validate printer.cfg
python .github/skills/3d-printer-expert/scripts/firmware_analyzer.py --check all --config-path /path/to/printer.cfg

# Search ControlCenter for relevant code
python .github/skills/3d-printer-expert/scripts/controlcenter_reference.py --query "websocket reconnect"

# SSH into printer Pi — tail logs, check services, get system info
python .github/skills/3d-printer-expert/scripts/ssh_manager.py --host 192.168.1.100 --action logs --tail 200
python .github/skills/3d-printer-expert/scripts/ssh_manager.py --host 192.168.1.100 --action check-services
python .github/skills/3d-printer-expert/scripts/ssh_manager.py --host 192.168.1.100 --action system-info

# Visualize temperature trends, MCU stats, print timelines
python .github/skills/3d-printer-expert/scripts/visualize_data.py --source log --type temperature --log-path klippy.log
python .github/skills/3d-printer-expert/scripts/visualize_data.py --source log --type stats --log-path klippy.log
python .github/skills/3d-printer-expert/scripts/visualize_data.py --source log --type input-shaper --log-path klippy.log

# Safely edit remote printer.cfg with auto-backup, diff, validate, apply+restart
python .github/skills/3d-printer-expert/scripts/remote_config_editor.py --host 192.168.1.100 --read
python .github/skills/3d-printer-expert/scripts/remote_config_editor.py --host 192.168.1.100 --edit sensor_type "EPCOS 100K B57560G104F" --section extruder
python .github/skills/3d-printer-expert/scripts/remote_config_editor.py --host 192.168.1.100 --enable MAG_DOOR.cfg
python .github/skills/3d-printer-expert/scripts/remote_config_editor.py --host 192.168.1.100 --validate
python .github/skills/3d-printer-expert/scripts/remote_config_editor.py --host 192.168.1.100 --apply-and-restart
```

## Required Environment Variables

- `OCTOPRINT_IP` — OctoPrint server IP address (optional, can be passed via --ip)
- `OCTOPRINT_API_KEY` — OctoPrint API key (optional, can be passed via --api-key)
- `PRINTER_SSH_HOST` — Printer Raspberry Pi IP/hostname for SSH scripts
- `PRINTER_SSH_USER` — SSH username (default: pi)
- `PRINTER_SSH_KEY` — Path to SSH private key (preferred over password)
- `PRINTER_SSH_PASSWORD` — SSH password (key-based auth preferred)
- `KLIPPER_LOG_PATH` — Default path to klippy.log (optional)
- `CONTROLCENTER_PATH` — Path to ControlCenter repo for code reference

## Outputs

Produces diagnostic reports, validated configurations, and actionable fix
recommendations. Writes detailed findings to `outputs/` for user review.
