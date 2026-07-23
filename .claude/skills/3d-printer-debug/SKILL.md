---
name: 3d-printer-debug
description: >
  Debug 3D printers end-to-end — Klipper errors (MCU, TMC drivers, thermal,
  homing, CAN), OctoPrint/Moonraker/Mainsail stacks, Raspberry Pi health,
  SPI/HDMI display boards, KlipperScreen, electronics, and print quality.
  Use when the user reports any printer error, failed print, disconnect,
  heater/thermistor issue, display problem, or wants live printer diagnostics.
---

# 3D Printer Debugging

Canonical skill: `.github/skills/3d-printer-expert/SKILL.md` — read it for the
full SOP. All scripts run from the repo root with `python <script> --help`.

## Routing table

| Symptom | Command |
|---------|---------|
| Any Klipper error/shutdown | `python .github/skills/3d-printer-expert/scripts/klipper_log_parser.py --days 1` |
| Explain an error message exactly | `python .github/skills/3d-printer-expert/scripts/klipper_error_lookup.py --error "<msg>"` |
| Peripheral compatibility / combination rules | `python .github/skills/3d-printer-expert/scripts/peripheral_lookup.py --name "<part>"` or `--combos <term>` |
| Klipper/Moonraker state, temps, gcode | `python .github/skills/3d-printer-expert/scripts/moonraker_api.py --action diagnose` |
| OctoPrint status/job/files | `python .github/skills/3d-printer-expert/scripts/octoprint_api.py --action status` |
| Mainsail blank/can't connect/502 | `python .github/skills/3d-printer-expert/scripts/mainsail_diagnostics.py --check all` |
| Random disconnects, reboots | `python .github/skills/3d-printer-expert/scripts/pi_system_diagnostics.py --check power` |
| Pi health sweep (SD, CAN, services) | `python .github/skills/3d-printer-expert/scripts/pi_system_diagnostics.py --check all` |
| SPI/HDMI display, touch, KlipperScreen | `python .github/skills/3d-printer-expert/scripts/display_diagnostics.py --check all` |
| Validate printer.cfg | `python .github/skills/3d-printer-expert/scripts/firmware_analyzer.py --check all` |
| Edit remote printer.cfg safely | `python .github/skills/3d-printer-expert/scripts/remote_config_editor.py --host <ip> --edit KEY VALUE --section SECT` |
| Live interactive health check | `python .github/skills/3d-printer-expert/scripts/live_printer_diagnostics.py --check all` |
| Print quality symptom | `python .github/skills/3d-printer-expert/scripts/print_quality_analyzer.py --symptom "..."` |
| Temperature/MCU stats plots | `python .github/skills/3d-printer-expert/scripts/visualize_data.py --type temperature` |
| SSH: logs/services/commands | `python .github/skills/3d-printer-expert/scripts/ssh_manager.py --host <ip> --action logs --tail 200` |
| Klipper docs/commands | `python .github/skills/3d-printer-expert/scripts/klipper_docs.py --search "..."` |
| ControlCenter app code | `python .github/skills/3d-printer-expert/scripts/controlcenter_reference.py --query "..."` |

Known-failure references (offline): `mainsail_diagnostics.py --failures`,
`pi_system_diagnostics.py --failures`, `display_diagnostics.py --failures`,
`klipper_error_lookup.py --list`.

## SOP

1. klippy.log first — it is ground truth.
2. Identify the exact error with `klipper_error_lookup.py`; unknown errors →
   use the `klipper-knowledge-graph` skill.
3. Rule out Pi undervoltage before chasing software ghosts.
4. One change at a time; `remote_config_editor.py` auto-backups and validates.
5. Verify after every fix; store lessons via `.tmp/scripts/memory_bank.py --add-insight`.

Connection settings come from `.env` (`OCTOPRINT_IP`, `MOONRAKER_HOST`,
`PRINTER_SSH_HOST`, ...) or CLI flags. SSH scripts need `paramiko`;
WebSocket checks need `websocket-client` (`pip install -r requirements.txt`).
