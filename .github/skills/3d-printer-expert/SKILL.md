---
name: 3d-printer-expert
description: >
  Diagnose and fix 3D printer issues across the full stack — Klipper logs and
  errors (MCU, TMC drivers, thermal, homing, CAN — with exact causes),
  OctoPrint/Moonraker/Mainsail APIs and web stack, printer.cfg analysis,
  Raspberry Pi health, SPI/HDMI display boards, KlipperScreen, electronics,
  and ControlCenter codebase reference for application-level debugging.
when_to_use: >
  User asks about 3D printer troubleshooting, Klipper errors, OctoPrint,
  Moonraker, or Mainsail issues, firmware configuration, print failures,
  Raspberry Pi or display/touchscreen problems, hardware-software bugs,
  or ControlCenter application debugging.
authority: write
cost_tier: 1
version: 0.2.0
---

# 3D Printer Expert Skill (Anil)

Diagnoses and fixes firmware, software, and hardware issues across the full
3D printing stack: Klipper firmware, OctoPrint, Moonraker, Mainsail,
printer.cfg configuration, MCU communication, TMC drivers, sensors,
Raspberry Pi platform, display boards, and the ControlCenter PyQt5
application.

> Related skill: `.github/skills/klipper-knowledge-graph/` — Graphify-powered
> knowledge graph of Klipper GitHub issues, forums, and source code.
> **Graphify must be installed to properly use the agent's knowledge-graph
> features** (`uv tool install graphifyy` && `graphify install`).

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
| `scripts/live_printer_diagnostics.py` | **Interactive diagnostic wizard** — connects via OctoPrint REST API, runs comprehensive checks (thermistor, heater, extrusion, homing, motion, probe), supports human-in-the-loop for physical verification, generates structured reports |
| `scripts/octoprint_websocket_client.py` | Real-time WebSocket connection to OctoPrint — streams temperature, printer state, job progress, events; detects anomalies (rapid temp drops, oscillations, connection issues) |
| `scripts/print_quality_analyzer.py` | **Print quality diagnostic tool** — matches user-described print symptoms to 24+ known issues in a comprehensive database; provides targeted fixes, Klipper commands, slicer settings, and material-specific guidance |
| `scripts/klipper_error_lookup.py` | **Comprehensive Klipper error database** — explains exactly why every common MCU, TMC driver, thermal, homing, extrusion, CAN, and config error occurs (source-level mechanism), with diagnostics and fixes |
| `scripts/moonraker_api.py` | **Moonraker REST API client** — klippy state, printer objects, temperatures, G-code, job history, update manager, power devices, service restarts, WebSocket test, full health sweep |
| `scripts/mainsail_diagnostics.py` | **Mainsail web stack diagnostics** — nginx frontend, Moonraker REST + WebSocket, CORS config, versions, SSH-layer service checks, and known failure-mode reference (blank page, 502, "cannot connect") |
| `scripts/pi_system_diagnostics.py` | **Raspberry Pi health** — undervoltage/throttling decode, thermals, SD card health, network, USB serial, CAN bus, systemd services, boot config, journal errors, failure-mode reference |
| `scripts/display_diagnostics.py` | **Display board diagnostics** — SPI TFT panels (fbtft overlays), HDMI/DSI screens, framebuffers, KMS/DRM, touch devices + calibration, KlipperScreen service/logs, backlight, failure-mode reference |

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

# LIVE DIAGNOSTICS — Interactive printer health check wizard
python .github/skills/3d-printer-expert/scripts/live_printer_diagnostics.py --ip 192.168.1.100 --api-key YOURKEY
python .github/skills/3d-printer-expert/scripts/live_printer_diagnostics.py --check heater,thermistor --interactive
python .github/skills/3d-printer-expert/scripts/live_printer_diagnostics.py --check all --output report.json
python .github/skills/3d-printer-expert/scripts/live_printer_diagnostics.py --check homing,motion --no-interactive

# WEBSOCKET — Real-time monitoring via OctoPrint's SockJS WebSocket (same as ControlCenter)
python .github/skills/3d-printer-expert/scripts/octoprint_websocket_client.py --ip 192.168.1.100 --api-key YOURKEY
python .github/skills/3d-printer-expert/scripts/octoprint_websocket_client.py --monitor temps --duration 120 --detect-anomalies
python .github/skills/3d-printer-expert/scripts/octoprint_websocket_client.py --trend tool0 --duration 60

# ERROR LOOKUP — Explain exactly why a Klipper error occurs (MCU/TMC/thermal/homing/CAN)
python .github/skills/3d-printer-expert/scripts/klipper_error_lookup.py --error "MCU 'mcu' shutdown: Timer too close"
python .github/skills/3d-printer-expert/scripts/klipper_error_lookup.py --error "TMC 'stepper_x' reports error: ... uv_cp=1"
python .github/skills/3d-printer-expert/scripts/klipper_error_lookup.py --category tmc_drivers
python .github/skills/3d-printer-expert/scripts/klipper_error_lookup.py --search thermistor
python .github/skills/3d-printer-expert/scripts/klipper_error_lookup.py --list

# MOONRAKER — Query Moonraker API (Mainsail/Fluidd/KlipperScreen backend)
python .github/skills/3d-printer-expert/scripts/moonraker_api.py --action diagnose --host 192.168.1.100
python .github/skills/3d-printer-expert/scripts/moonraker_api.py --action klippy-state
python .github/skills/3d-printer-expert/scripts/moonraker_api.py --action temps
python .github/skills/3d-printer-expert/scripts/moonraker_api.py --action gcode --script "QUERY_ENDSTOPS"
python .github/skills/3d-printer-expert/scripts/moonraker_api.py --action update-status
python .github/skills/3d-printer-expert/scripts/moonraker_api.py --action websocket-test

# MAINSAIL — Debug the web UI stack layer by layer
python .github/skills/3d-printer-expert/scripts/mainsail_diagnostics.py --host 192.168.1.100 --check all
python .github/skills/3d-printer-expert/scripts/mainsail_diagnostics.py --host 192.168.1.100 --check ssh
python .github/skills/3d-printer-expert/scripts/mainsail_diagnostics.py --failures

# RASPBERRY PI — Health checks (undervoltage FIRST when chasing random disconnects)
python .github/skills/3d-printer-expert/scripts/pi_system_diagnostics.py --host 192.168.1.100 --check all
python .github/skills/3d-printer-expert/scripts/pi_system_diagnostics.py --host 192.168.1.100 --check power
python .github/skills/3d-printer-expert/scripts/pi_system_diagnostics.py --host 192.168.1.100 --check can
python .github/skills/3d-printer-expert/scripts/pi_system_diagnostics.py --failures

# DISPLAYS — SPI TFT / HDMI / DSI / KlipperScreen / touch debugging
python .github/skills/3d-printer-expert/scripts/display_diagnostics.py --host 192.168.1.100 --check all
python .github/skills/3d-printer-expert/scripts/display_diagnostics.py --host 192.168.1.100 --check klipperscreen
python .github/skills/3d-printer-expert/scripts/display_diagnostics.py --failures spi_white_screen
python .github/skills/3d-printer-expert/scripts/display_diagnostics.py --failures hdmi_no_signal

# PRINT QUALITY — Diagnose print issues from symptom descriptions
python .github/skills/3d-printer-expert/scripts/print_quality_analyzer.py --symptom "stringing between towers"
python .github/skills/3d-printer-expert/scripts/print_quality_analyzer.py --symptom "first layer not sticking" --material PETG
python .github/skills/3d-printer-expert/scripts/print_quality_analyzer.py --category extrusion
python .github/skills/3d-printer-expert/scripts/print_quality_analyzer.py --list-categories
python .github/skills/3d-printer-expert/scripts/print_quality_analyzer.py --material-guide ABS
python .github/skills/3d-printer-expert/scripts/print_quality_analyzer.py --tuning-guide
python .github/skills/3d-printer-expert/scripts/print_quality_analyzer.py --post-processing
```

## Required Environment Variables

- `OCTOPRINT_IP` — OctoPrint server IP address (optional, can be passed via --ip)
- `OCTOPRINT_API_KEY` — OctoPrint API key (optional, can be passed via --api-key)
- `MOONRAKER_HOST` — Moonraker host/IP (falls back to OCTOPRINT_IP)
- `MOONRAKER_PORT` — Moonraker port (default: 7125)
- `MOONRAKER_API_KEY` — Moonraker API key (only if authentication enabled)
- `MAINSAIL_PORT` — Mainsail/nginx HTTP port (default: 80)
- `PRINTER_SSH_HOST` — Printer Raspberry Pi IP/hostname for SSH scripts
- `PRINTER_SSH_USER` — SSH username (default: pi)
- `PRINTER_SSH_KEY` — Path to SSH private key (preferred over password)
- `PRINTER_SSH_PASSWORD` — SSH password (key-based auth preferred)
- `KLIPPER_LOG_PATH` — Default path to klippy.log (optional)
- `CONTROLCENTER_PATH` — Path to ControlCenter repo for code reference

## Outputs

Produces diagnostic reports, validated configurations, and actionable fix
recommendations. Writes detailed findings to `outputs/` for user review.
