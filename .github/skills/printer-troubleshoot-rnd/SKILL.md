---
name: printer-troubleshoot
description: >
  Diagnose and fix 3D printer issues by connecting to printers over serial
  (USB/UART) or wireless (OctoPrint REST, Moonraker WebSocket). Run diagnostic
  G-codes, interpret output, and save fix records for future reference.
when_to_use: "User asks to troubleshoot/fix/diagnose a 3D printer issue"
authority: write
cost_tier: 1
version: 0.1.0
---

# Printer Troubleshoot Skill

Connect to 3D printers via serial or wireless, run diagnostic commands, interpret results (M122, M119, M105, M503), identify root cause of failures, and save fix records.

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/serial_connect.py` | Connect to printer over serial port, send G-code, read response |
| `scripts/troubleshoot_diagnostics.py` | Run full diagnostic suite and save fix report |

## Usage

```bash
# Connect and get printer state
python .github/skills/printer-troubleshoot/scripts/serial_connect.py --port COM3 --baud 115200 --cmd "M105"

# Run full diagnostics
python .github/skills/printer-troubleshoot/scripts/troubleshoot_diagnostics.py --port COM3 --baud 115200 --printer "CR-10"
```

## Fix Record Storage

Every diagnostic run saves a JSON file to `outputs/_memory/fixes/<timestamp>_<printer>.json`:
- Printer model & firmware version
- Symptom description
- Diagnostic commands run & responses
- Root cause diagnosis
- Fix applied
- Verification result

These files are **read-only** — never modified after creation.

## Outputs

- Fix records in `outputs/_memory/fixes/`
- Diagnostic summaries in `outputs/reports/`
