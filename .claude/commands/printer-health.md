---
description: Full read-only health sweep of the printer Pi, web stack, and display
argument-hint: [host/IP, optional — falls back to .env]
---

Run a complete read-only health sweep. Every command here only reads state —
none of them change printer configuration or move hardware.

Host: use `$ARGUMENTS` if provided, otherwise the values in `.env`
(`PRINTER_SSH_HOST`, `MOONRAKER_HOST`).

Run these and interpret the combined picture:

```bash
# Power first — undervoltage mimics dozens of software bugs
python .github/skills/3d-printer-expert/scripts/pi_system_diagnostics.py --check power

# Full Pi sweep: thermal, storage, network, USB, CAN, services, boot config
python .github/skills/3d-printer-expert/scripts/pi_system_diagnostics.py --check all

# Klipper/Moonraker state and temperatures
python .github/skills/3d-printer-expert/scripts/moonraker_api.py --action diagnose

# Mainsail web stack: nginx, CORS, WebSocket
python .github/skills/3d-printer-expert/scripts/mainsail_diagnostics.py --check all

# Display: SPI/HDMI/DSI, touch, KlipperScreen
python .github/skills/3d-printer-expert/scripts/display_diagnostics.py --check all
```

If a host is unreachable, say so plainly and stop rather than inferring health
from a timeout.

Report a short status table (subsystem → OK/WARN/FAIL → evidence), then list
only the findings that need action, most severe first. Undervoltage, SD card
wear, and CAN bus errors outrank cosmetic warnings.
