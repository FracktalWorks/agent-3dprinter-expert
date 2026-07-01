# agent-data — INDEX

Reference data for 3D Printer Expertging. All files in this directory are
read-only — the agent references them but never modifies them.

## Klipper Reference

| File | Description |
|------|-------------|
| *(add your klipper error code reference here)* | Common Klipper error codes and fixes |
| *(add thermistor tables here)* | Thermistor type vs. sensor_type mappings |

## OctoPrint Reference

| File | Description |
|------|-------------|
| *(add OctoPrint API docs here)* | OctoPrint REST API endpoint reference |

## Printer Configs

| File | Description |
|------|-------------|
| *(add printer config templates here)* | Reference printer.cfg templates |

## ControlCenter Reference

The ControlCenter codebase is referenced externally at:
`C:\Users\VijayRaghavVarada\Documents\Github\ControlCenter`

Key documentation:
- `Documentation/` — Debug session logs, testing guides
- `Documentation/ERROR_HANDLING_IMPROVEMENTS.md` — Error handling patterns
- `Documentation/KLIPPER_RESTART_WAIT_UTILITY.md` — Klipper restart handling
- `Documentation/OCTOPRINT_SERIAL_OPTIMIZATION.md` — Serial optimization
- `Documentation/WEBSOCKET_UI_UPDATE_FIXES.md` — WebSocket fixes

## How to Add Reference Data

1. Place files in this directory
2. Update this INDEX.md with the file name and description
3. The agent will reference these files during debugging sessions
