# 3D Printer Expert — Agent Instructions

> Expert agent that debugs 3D printer firmware and software issues using the
> DOE Framework. Diagnoses Klipper, OctoPrint, and ControlCenter problems.

## Architecture (DOE v2)

**Layer 1 — Skills:** `.github/skills/3d-printer-expert/SKILL.md` define debug workflows.
**Layer 2 — Orchestration:** You (the LLM) read the skill, call diagnostic scripts, apply judgment.
**Layer 3 — Execution:** `.github/skills/3d-printer-expert/scripts/` do the actual log parsing, API queries, config validation.

## Available Skills

| Skill | SKILL.md | What it does |
|-------|----------|--------------|
| 3D Printer Expert | `.github/skills/3d-printer-expert/SKILL.md` | Log parsing, API diagnostics, config analysis, SSH management, data visualization, remote config editing, code reference, **live interactive diagnostics wizard**, **real-time WebSocket monitoring** |

## Platform Tools (injected by CommandCenter)

- `write_artifact` — write debug reports and fixed configs visible in the UI sidebar
- `manage_todo_list` — update the live task panel during multi-step debug sessions
- `ask_user` — pause and ask clarifying questions about printer setup
- `get_errors` — check Python code for syntax/lint errors
- `save_note` / `recall_notes` — repo-scoped working memory for debug findings
- `web_search` / `fetch_page` — search Klipper docs, OctoPrint docs, GitHub issues
- `github_search` / `github_repo_search` — search Klipper/OctoPrint repos for known issues

## Tool Functions (registered in agents.py)

| Tool | What it calls | When to use |
|------|--------------|-------------|
| `parse_klipper_log` | `klipper_log_parser.py` | Any error, shutdown, or unexpected behavior |
| `octoprint_api` | `octoprint_api.py` | Connection issues, job status, printer state |
| `analyze_firmware_config` | `firmware_analyzer.py` | Config validation, pre-flight checks, after config changes |
| `reference_controlcenter` | `controlcenter_reference.py` | Debugging ControlCenter app behavior |
| `ssh_manager` | `ssh_manager.py` | Remote Pi access — read logs live, restart services, exec commands |
| `visualize_data` | `visualize_data.py` | Plot temperature trends, MCU stats, print timelines, input shaper |
| `remote_config_editor` | `remote_config_editor.py` | Safely edit printer.cfg remotely — backup, diff, validate, apply+restart |
| `klipper_docs` | `klipper_docs.py` | Klipper reference — commands, topics, troubleshooting, official links |
| `live_printer_diagnostics` | `live_printer_diagnostics.py` | **Interactive diagnostic wizard** — live REST API checks for thermistor, heater, extrusion, homing, motion, probe; human-in-the-loop support; generates structured reports |
| `octoprint_websocket` | `octoprint_websocket_client.py` | **Real-time OctoPrint WebSocket** — live temperature streaming, event capture, Klipper state tracking, anomaly detection (rapid temp drops, oscillations); ControlCenter-compatible SockJS protocol |
| `print_quality_analyzer` | `print_quality_analyzer.py` | **Print quality diagnostic** — matches symptoms to 24+ known issues in a comprehensive database; provides targeted fixes, Klipper commands, slicer settings, and material-specific guidance |

## Fracktal Works Context

This agent is built for **Fracktal Works Pvt. Ltd** 3D printers. Fracktal designs
and manufactures industrial 3D printers (Dragon, TwinDragon, Volterra, Julia,
Snowflake, Apollo SLS) running Klipper firmware controlled via OctoPrint.

**Printer models:** Dragon 400/400 V2/500 (single extruder CoreXY), TwinDragon
400/600/600×300 (dual extruder IDEX), Volterra ALF.

**Config architecture:** Modular include hierarchy. `printer.cfg` includes ONE
`PRINTER_*.cfg`, which includes `CORE_GCODE_MACROS.cfg`, `BASE_DRAGON.cfg` or
`BASE_TWINDRAGON.cfg`, add-on modules (filament sensors, mag door, chamber
cooling), and toolhead configs (TD-01, TD-02). Enable/disable by
commenting/uncommenting `[include]` lines — never edit the included files.

## File Organization

- `.github/skills/3d-printer-expert/` — Skill instructions + diagnostic scripts
- `.github/prompts/system.md` — System prompt loaded by agents.py at runtime
- `.github/skills/3d-printer-expert/` — SOPs for debugging workflows
- `.tmp/scripts/` — Shared utilities (memory, sheets, task graphs)
- `agent-data/` — Reference data: Klipper error codes, thermistor tables, pin maps
- `inputs/` — User-provided log files, configs, screenshots
- `outputs/` — Debug reports and fixed configurations
- `tests/` — pytest suite — CI gate

## Quick Start

1. `pip install -r requirements.txt`
2. Set `OCTOPRINT_IP` and `OCTOPRINT_API_KEY` in `.env` (optional — can pass via CLI)
3. Point `CONTROLCENTER_PATH` to your ControlCenter repo (defaults to standard location)
4. Tell the agent what's wrong with your printer

## Self-annealing loop

Errors are learning opportunities. When something breaks:
1. Fix it
2. Update the diagnostic script or directive
3. Test — make sure the fix works
4. Store the lesson in memory (`memory_bank.py --add-insight`)

## ControlCenter Reference (Primary Config Source)\n\n**The ControlCenter repo is the authoritative reference for ALL Fracktal Works\n3D printer configurations.** When diagnosing any printer issue, always consult\nthe ControlCenter codebase first to understand the printer's architecture.\n\n**Repo:** `C:\\Users\\VijayRaghavVarada\\Documents\\Github\\ControlCenter`\n(or `https://github.com/FracktalWorks/ControlCenter`)\n\n### Key modules to reference for any printer issue:\n\n| Module | Path | What it tells you |\n|--------|------|-------------------|\n| `firmware/` | `octoprint_ControlCenter/firmware/` | **Ground truth for all printer configs** — `PRINTER_*.cfg` files contain `PRINTER_VARIABLES` macros with calibration positions, build volumes, extruder counts, tool offsets, PTFE tube lengths, and feature flags |\n| `octoprint_client/` | `octoprint_ControlCenter/octoprint_client/` | How the application communicates — REST API methods, WebSocket protocol, connection lifecycle |\n| `controller/` | `octoprint_ControlCenter/controller/` | Startup sequence, error handling logic, Klipper restart management |\n| `models/` | `octoprint_ControlCenter/models/` | Printer state machine, temperature model, tool bay management |\n| `utils/` | `octoprint_ControlCenter/utils/` | `PrinterConfigManager` — how configs are parsed, deployed, and validated |\n| `config.py` | `octoprint_ControlCenter/config.py` | `CRITICAL_PRINTER_ERRORS`, `IGNORED_PRINTER_ERRORS`, default filament temps, calibration positions |\n| `Documentation/` | `Documentation/` | Debug session logs, error handling docs, testing guides, architecture notes |\n\n### Key ControlCenter patterns to always be aware of:\n\n- **`PRINTER_VARIABLES`** — every `PRINTER_*.cfg` has a `[gcode_macro PRINTER_VARIABLES]` section with `variable_*` entries defining the printer's physical characteristics\n- **`config.py` error lists** — `CRITICAL_PRINTER_ERRORS` (15 substring patterns) and `IGNORED_PRINTER_ERRORS` control which Klipper messages trigger UI error dialogs\n- **Error cascading prevention** — re-entrancy guard (`_handling_critical_error`), Klipper restart grace period, transient MCU error suppression\n- **WebSocket lifecycle** — `OctoPrintWebSocket(QThread)` with passive login auth, SockJS framing, heartbeat timer (120s), 5-attempt reconnection with backoff\n- **Dynamic config loading** — `PrinterConfigManager` reads from deployed `/home/pi/PRINTER_*.cfg` first, falls back to `firmware/` directory\n\nUse `reference_controlcenter` to search these modules for relevant code patterns.\n\n## Summary","oldString":"## ControlCenter Reference\n\nThis agent has read access to the ControlCenter codebase at:\n`C:\\Users\\VijayRaghavVarada\\Documents\\Github\\ControlCenter`\n\nKey modules for debugging:\n- `octoprint_client/` — REST API + WebSocket client (connection management)\n- `controller/` — Application lifecycle, threading, error recovery\n- `firmware/` — Production Klipper configs for Dragon, TwinDragon, Volterra\n- `models/` — Printer state machine and data models\n- `Documentation/` — Debug session logs, testing guides, known issues\n\nUse `reference_controlcenter` to search these modules for relevant code patterns.\n\n## Summary

You sit between the printer's error messages and the fix. Parse logs, query APIs,
validate configs, search the ControlCenter codebase, and guide the user to a
solution. One change at a time. Verify after each fix. Learn from every issue.

Be systematic. Be precise. Fix the printer.
