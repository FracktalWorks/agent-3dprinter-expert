# 3D Printer Expertging — SOP

Debug firmware and software issues on Klipper-based 3D printers controlled via
OctoPrint. Covers log analysis, API diagnostics, config validation, and
ControlCenter application debugging.

## When to Use

- Printer reports an error or shuts down unexpectedly
- Print quality issues (layer shifts, extrusion problems, artifacts)
- OctoPrint cannot connect or disconnects frequently
- Klipper reports MCU communication errors
- Temperature/heater faults
- Configuration changes need validation
- ControlCenter application behaves unexpectedly

## Required Information

Before starting, gather:
1. **Printer model** and firmware version
2. **klippy.log** — the single most important diagnostic file
3. **printer.cfg** — current configuration
4. **OctoPrint URL and API key** (if debugging OctoPrint issues)
5. **Symptom description** — what happened, when, and what changed recently

## Workflow

### Phase 1: Triage (5 min)

1. Ask the user what specifically is failing
2. Determine which component is likely involved:
   - **Firmware/Klipper** → start with `klipper_log_parser.py`
   - **OctoPrint/Connection** → start with `octoprint_api.py --action status`
   - **Configuration** → start with `firmware_analyzer.py --check all`
   - **ControlCenter UI** → start with `controlcenter_reference.py --query "<symptom>"`
3. **Look up relevant Klipper docs** → `klipper_docs.py --search "<symptom keywords>"`
4. **Check troubleshooting guide** → `klipper_docs.py --diagnose <symptom_key>`
5. Set expectations: most issues are config or wiring, not firmware bugs

### Phase 2: Evidence Collection (10-15 min)

Run the appropriate diagnostic scripts:

```bash
# ALWAYS start with log analysis — klippy.log is ground truth
python .github/skills/3d-printer-expert/scripts/klipper_log_parser.py --days 1

# If you have SSH access — get logs directly from the Pi
python .github/skills/3d-printer-expert/scripts/ssh_manager.py --host <IP> --action logs --tail 200
python .github/skills/3d-printer-expert/scripts/ssh_manager.py --host <IP> --action klipper-errors
python .github/skills/3d-printer-expert/scripts/ssh_manager.py --host <IP> --action system-info

# If OctoPrint is involved
python .github/skills/3d-printer-expert/scripts/octoprint_api.py --action status --ip <IP> --api-key <KEY>

# If configuration might be the issue
python .github/skills/3d-printer-expert/scripts/firmware_analyzer.py --check all --config-path <path>

# Visualize trends to find intermittent issues
python .github/skills/3d-printer-expert/scripts/visualize_data.py --source log --type temperature --log-path <path>
python .github/skills/3d-printer-expert/scripts/visualize_data.py --source log --type stats --log-path <path>
python .github/skills/3d-printer-expert/scripts/visualize_data.py --source log --type timeline --log-path <path>

# If ControlCenter code is relevant
python .github/skills/3d-printer-expert/scripts/controlcenter_reference.py --query "<keywords>"
```

### Phase 3: Diagnosis

Correlate findings across all evidence sources. Use `visualize_data.py` to spot
patterns invisible in raw logs — temperature oscillations, periodic MCU
retransmits, buffer starvation during specific geometry.

| Symptom | Log Pattern | Config Issue | Hardware Check |
|---------|------------|--------------|----------------|
| Heater not heating | `Heater extruder not heating at expected rate` | `max_power` too low | Heater cartridge resistance (~3-5Ω) |
| Temperature spike | `ADC out of range` | Wrong `sensor_type` (should be `EPCOS 100K B57560G104F`) | Thermistor wiring, pull-up resistor |
| MCU disconnect | `Lost communication with MCU` | Baudrate mismatch, CANbus UUID placeholder | USB cable, power supply, CAN termination |
| Layer shift | `Timer too close` | Microsteps too high (16→8) | Belt tension, stepper current |
| Print stops mid-job | `Move exceeds maximum extrusion` | `max_extrude_cross_section` too low | Check for nozzle clog |
| Probe fails | `Probe triggered prior to movement` | `z_offset` wrong, `speed` too high | Probe mounting, wiring |
| **Fracktal: wrong printer** | Multiple `[include PRINTER_` active | Two printer configs uncommented | Check printer.cfg |

### Phase 4: Fix (Remote via SSH)

```bash
# Read the current config on the printer
python .github/skills/3d-printer-expert/scripts/remote_config_editor.py --host <IP> --read

# Edit a specific key (auto-backup, validates, shows diff)
python .github/skills/3d-printer-expert/scripts/remote_config_editor.py --host <IP> \
  --edit sensor_type "EPCOS 100K B57560G104F" --section extruder

# Enable a module (Fracktal convention: uncomment the include)
python .github/skills/3d-printer-expert/scripts/remote_config_editor.py --host <IP> \
  --enable MAG_DOOR.cfg

# Disable a module
python .github/skills/3d-printer-expert/scripts/remote_config_editor.py --host <IP> \
  --disable T1_FILAMENT_RUNOUT_SENSOR.cfg

# Validate config syntax before applying
python .github/skills/3d-printer-expert/scripts/remote_config_editor.py --host <IP> --validate

# See what changed from last backup
python .github/skills/3d-printer-expert/scripts/remote_config_editor.py --host <IP> --diff

# Apply changes: validate, restart Klipper, verify no errors in log
python .github/skills/3d-printer-expert/scripts/remote_config_editor.py --host <IP> --apply-and-restart

# If something went wrong, restore from backup
python .github/skills/3d-printer-expert/scripts/remote_config_editor.py --host <IP> --list-backups
python .github/skills/3d-printer-expert/scripts/remote_config_editor.py --host <IP> \
  --restore /home/pi/printer_data/config/printer.cfg.backup-20260701_143022
```

### Phase 5: Verify

1. `ssh_manager --action klipper-errors` — confirm no new errors after restart
2. `ssh_manager --action check-services` — verify klipper + octoprint running
3. `visualize_data --type temperature` — confirm temps stable for 5+ min
4. `octoprint_api --action status` — confirm printer operational
5. Re-run the original diagnostic to confirm the issue is resolved

## Common Fix Patterns

### MCU Communication Fixes

```ini
# If using USB serial — check the port
[mcu]
serial: /dev/serial/by-id/usb-Klipper_...  # Use by-id, not by-path

# If using CANbus — verify UUID
[mcu]
canbus_uuid: 0ab39df5e02c  # Get from: ~/klippy-env/bin/python ~/klipper/scripts/canbus_query.py can0

# For multi-MCU setups, ensure each has a unique name
[mcu rpi]
serial: /tmp/klipper_host_mcu

[mcu toolhead0]
canbus_uuid: XXXXXXXX
```

### Thermistor Fixes

```ini
[extruder]
sensor_type: ATC Semitec 104GT-2  # Most common for E3D thermistors
# OR
sensor_type: Generic 3950  # Common for bed thermistors

# If using PT100 amplifier
sensor_type: MAX31865
sensor_pin: spi0  # Check which SPI bus
```

### Stepper Current Tuning

```ini
[tmc2209 stepper_x]
run_current: 0.580  # Start at 0.5A, increase if skipping
hold_current: 0.350
stealthchop_threshold: 999999  # StealthChop for quiet operation
```

## ControlCenter-Specific Debugging

When debugging the ControlCenter PyQt5 application:

1. **WebSocket disconnects**: Check `websocket_client.py` — it has reconnect logic with exponential backoff. Look at the `_initialize_websocket` and `on_close` handlers.

2. **API timeouts**: The `octoprintAPI.py` uses `requests` without explicit timeouts on some methods. Check the `_get`/`_post` patterns.

3. **UI freezes**: The `main_controller.py` uses `QThread` for background tasks. Check that long operations aren't blocking the main thread.

4. **Config loading**: `printer_config_manager.py` handles dynamic config. Issues often stem from YAML parsing or missing config keys.

Use `controlcenter_reference.py` to find exact code locations for any of these patterns.

## Outputs

Write a diagnostic report to `outputs/<printer>-debug-<date>.md` containing:
- Summary of symptoms
- Evidence collected (log excerpts, API responses, config sections)
- Root cause analysis
- Fix applied (with config diff)
- Verification results
- Recommendations for prevention
