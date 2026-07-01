#!/usr/bin/env python3
"""
Klipper Documentation & Diagnostics Reference — Built-in catalog of Klipper
G-code commands, diagnostic tools, config reference topics, and official
documentation source links. Can also fetch the latest Klipper docs from GitHub.

Usage:
    python klipper_docs.py --topic bed_mesh
    python klipper_docs.py --topic input_shaper
    python klipper_docs.py --command QUERY_ENDSTOPS
    python klipper_docs.py --list-commands
    python klipper_docs.py --list-topics
    python klipper_docs.py --fetch Config_Reference.md
    python klipper_docs.py --search "pressure advance"
    python klipper_docs.py --diagnose "heater error"
    python klipper_docs.py --links
"""

import argparse
import json
import os
import re
import sys
from typing import Optional

# ── Official Klipper Documentation Sources ────────────────────────────────────

KLIPPER_DOCS_BASE = "https://github.com/Klipper3d/klipper/blob/master/docs"
KLIPPER_RAW_BASE = (
    "https://raw.githubusercontent.com/Klipper3d/klipper/master/docs"
)

OFFICIAL_LINKS = {
    "home": "https://www.klipper3d.org/",
    "github": "https://github.com/Klipper3d/klipper",
    "config_reference": f"{KLIPPER_DOCS_BASE}/Config_Reference.md",
    "gcode": f"{KLIPPER_DOCS_BASE}/G-Codes.md",
    "installation": f"{KLIPPER_DOCS_BASE}/Installation.md",
    "kinematics": f"{KLIPPER_DOCS_BASE}/Kinematics.md",
    "bed_mesh": f"{KLIPPER_DOCS_BASE}/Bed_Mesh.md",
    "resonance_compensation": f"{KLIPPER_DOCS_BASE}/Resonance_Compensation.md",
    "pressure_advance": f"{KLIPPER_DOCS_BASE}/Pressure_Advance.md",
    "skew_correction": f"{KLIPPER_DOCS_BASE}/Skew_Correction.md",
    "manual_level": f"{KLIPPER_DOCS_BASE}/Manual_Level.md",
    "probe_calibrate": f"{KLIPPER_DOCS_BASE}/Probe_Calibrate.md",
    "rotation_distance": f"{KLIPPER_DOCS_BASE}/Rotation_Distance.md",
    "mcu": f"{KLIPPER_DOCS_BASE}/MCU_Commands.md",
    "rpi_microcontroller": f"{KLIPPER_DOCS_BASE}/RPi_microcontroller.md",
    "canbus": f"{KLIPPER_DOCS_BASE}/CANBUS.md",
    "tmc_drivers": f"{KLIPPER_DOCS_BASE}/TMC_Drivers.md",
    "endstop_phase": f"{KLIPPER_DOCS_BASE}/Endstop_Phase.md",
    "debugging": f"{KLIPPER_DOCS_BASE}/Debugging.md",
    "faq": f"{KLIPPER_DOCS_BASE}/FAQ.md",
    "api_server": f"{KLIPPER_DOCS_BASE}/API_Server.md",
    "code_overview": f"{KLIPPER_DOCS_BASE}/Code_Overview.md",
    "status_reference": f"{KLIPPER_DOCS_BASE}/Status_Reference.md",
    "sdcard_loop": f"{KLIPPER_DOCS_BASE}/SDCard_Loops.md",
    "temperature_sensors": f"{KLIPPER_DOCS_BASE}/Config_checks.md",
}

RAW_DOC_URLS = {
    "Config_Reference.md": f"{KLIPPER_RAW_BASE}/Config_Reference.md",
    "G-Codes.md": f"{KLIPPER_RAW_BASE}/G-Codes.md",
    "Status_Reference.md": f"{KLIPPER_RAW_BASE}/Status_Reference.md",
    "Config_checks.md": f"{KLIPPER_RAW_BASE}/Config_checks.md",
    "Debugging.md": f"{KLIPPER_RAW_BASE}/Debugging.md",
    "FAQ.md": f"{KLIPPER_RAW_BASE}/FAQ.md",
}

# ── Klipper Diagnostic G-code Commands Catalog ────────────────────────────────

GCODE_COMMANDS = {
    "RESTART": {
        "description": "Restart the Klipper host software (reloads config)",
        "usage": "RESTART",
        "category": "system",
        "note": "Does NOT reload MCU firmware. Use FIRMWARE_RESTART for that.",
    },
    "FIRMWARE_RESTART": {
        "description": "Restart the MCU firmware (full reset including stepper drivers)",
        "usage": "FIRMWARE_RESTART",
        "category": "system",
        "note": "Use after flashing new MCU firmware or when MCU is in bad state.",
    },
    "STATUS": {
        "description": "Report the current printer status and last stats",
        "usage": "STATUS",
        "category": "system",
    },
    "M112": {
        "description": "Emergency stop — immediately halts all motion and heaters",
        "usage": "M112",
        "category": "safety",
        "note": "Irrecoverable without RESTART.",
    },
    "QUERY_ENDSTOPS": {
        "description": "Report the current state of all endstops (open/triggered)",
        "usage": "QUERY_ENDSTOPS",
        "category": "diagnostic",
        "note": "Use when homing fails — check which endstop is falsely triggered.",
    },
    "QUERY_ADC": {
        "description": "Report the last ADC reading from thermistors and sensors",
        "usage": "QUERY_ADC",
        "category": "diagnostic",
        "note": "Shows raw ADC values — helps identify wiring issues vs config issues.",
    },
    "STEPPER_BUZZ": {
        "description": "Vibrate a stepper motor to identify it (moves 1mm fwd/back + buzz)",
        "usage": "STEPPER_BUZZ STEPPER=stepper_x",
        "category": "diagnostic",
        "note": "Use when verifying which physical motor maps to which config section.",
    },
    "PID_CALIBRATE": {
        "description": "Run PID auto-tuning for a heater (extruder or bed)",
        "usage": "PID_CALIBRATE HEATER=extruder TARGET=200",
        "category": "calibration",
        "note": "Run after changing heater, thermistor, or power supply. Save with SAVE_CONFIG.",
    },
    "PID_TUNE": {
        "description": "Alternative PID tuning with different algorithm",
        "usage": "PID_TUNE HEATER=extruder TARGET=200",
        "category": "calibration",
    },
    "PROBE_CALIBRATE": {
        "description": "Calibrate probe Z offset using paper test",
        "usage": "PROBE_CALIBRATE",
        "category": "calibration",
        "note": "Moves nozzle to bed center, then use TESTZ Z= to adjust. ACCEPT + SAVE_CONFIG when done.",
    },
    "PROBE_ACCURACY": {
        "description": "Test probe repeatability by probing the same spot N times",
        "usage": "PROBE_ACCURACY SAMPLES=10",
        "category": "diagnostic",
        "note": "Standard deviation should be < 0.003mm for good probes. > 0.01mm indicates problem.",
    },
    "BED_MESH_CALIBRATE": {
        "description": "Probe the bed to generate a mesh for automatic leveling",
        "usage": "BED_MESH_CALIBRATE",
        "category": "calibration",
        "note": "Requires [bed_mesh] section in config. Save with SAVE_CONFIG.",
    },
    "BED_MESH_OUTPUT": {
        "description": "Export the current bed mesh as CSV for external visualization",
        "usage": "BED_MESH_OUTPUT",
        "category": "diagnostic",
    },
    "BED_MESH_PROFILE": {
        "description": "Manage bed mesh profiles (save/load/remove)",
        "usage": "BED_MESH_PROFILE LOAD=default",
        "category": "calibration",
    },
    "BED_SCREWS_ADJUST": {
        "description": "Interactive bed screw adjustment using the probe",
        "usage": "BED_SCREWS_ADJUST",
        "category": "calibration",
        "note": "Probes above each screw and reports turns needed. ACCEPT when done.",
    },
    "DELTA_CALIBRATE": {
        "description": "Delta printer auto-calibration (not applicable to CoreXY)",
        "usage": "DELTA_CALIBRATE METHOD=manual",
        "category": "calibration",
    },
    "TEST_RESONANCES": {
        "description": "Measure mechanical resonances for input shaper — requires ADXL345",
        "usage": "TEST_RESONANCES AXIS=X",
        "category": "calibration",
        "note": "Generates /tmp/resonances_x_*.csv. Process with calibrate_shaper.py on Pi.",
    },
    "SHAPER_CALIBRATE": {
        "description": "Automated resonance testing + input shaper recommendation — requires ADXL345",
        "usage": "SHAPER_CALIBRATE",
        "category": "calibration",
        "note": "Runs TEST_RESONANCES X+Y then computes best shaper. Results in console output.",
    },
    "MEASURE_AXES_NOISE": {
        "description": "Measure idle noise on all axes — helps diagnose stepper/ADC noise",
        "usage": "MEASURE_AXES_NOISE",
        "category": "diagnostic",
        "note": "Printer must be idle. Run for 30+ seconds for useful data.",
    },
    "TUNING_TOWER": {
        "description": "Automated test tower for parameter tuning (PA, temp, retraction, etc.)",
        "usage": "TUNING_TOWER COMMAND=SET_PRESSURE_ADVANCE PARAMETER=ADVANCE START=0 FACTOR=.005",
        "category": "calibration",
        "note": "Must be used within a print — not from idle console.",
    },
    "SET_PRESSURE_ADVANCE": {
        "description": "Set pressure advance at runtime (for TUNING_TOWER or manual tuning)",
        "usage": "SET_PRESSURE_ADVANCE ADVANCE=0.05",
        "category": "tuning",
        "note": "For Fracktal TD-01 direct drive, typical range is 0.02–0.08.",
    },
    "CALCULATE_SWITCHING_DISTANCE": {
        "description": "Compute switching offset for dual extruder IDEX printers",
        "usage": "CALCULATE_SWITCHING_DISTANCE EXTRUDER=extruder",
        "category": "calibration",
        "note": "Relevant for Fracktal TwinDragon IDEX models.",
    },
    "SAVE_CONFIG": {
        "description": "Write auto-calibrated values to printer.cfg SAVE_CONFIG block",
        "usage": "SAVE_CONFIG",
        "category": "system",
        "note": "Must run after PID_CALIBRATE, PROBE_CALIBRATE, BED_MESH_CALIBRATE.",
    },
    "GET_POSITION": {
        "description": "Report current toolhead position (including offset compensation)",
        "usage": "GET_POSITION",
        "category": "diagnostic",
    },
    "SYNC_EXTRUDER_MOTION": {
        "description": "Sync/unsync an extruder stepper with toolhead motion (dual extrusion)",
        "usage": "SYNC_EXTRUDER_MOTION EXTRUDER=extruder1 MOTION_QUEUE=extruder",
        "category": "tuning",
        "note": "Used by Fracktal TwinDragon for IDEX control and Dragon V2 dual material bay.",
    },
    "SET_KINEMATIC_POSITION": {
        "description": "Force-set the kinematic position (for recovery after layer shift or MCU error)",
        "usage": "SET_KINEMATIC_POSITION X=100 Y=100 Z=10",
        "category": "recovery",
        "note": "Dangerous — only use after layer shift to recover position for rest of print.",
    },
    "FORCE_MOVE": {
        "description": "Move steppers without homing — requires [force_move] and enable_force_move: True",
        "usage": "FORCE_MOVE STEPPER=stepper_x DISTANCE=10 VELOCITY=5",
        "category": "diagnostic",
        "note": "Bypasses all limits. Use with extreme caution. Good for testing stepper direction.",
    },
    "MOTION_REPORT": {
        "description": "Report the current toolhead motion queue status",
        "usage": "MOTION_REPORT",
        "category": "diagnostic",
    },
}

# ── Documentation Topics Catalog ──────────────────────────────────────────────

DOC_TOPICS = {
    "bed_mesh": {
        "title": "Bed Mesh / Automatic Bed Leveling",
        "description": (
            "Klipper's bed mesh system compensates for uneven build surfaces "
            "by probing a grid and applying Z offsets during printing."
        ),
        "link": OFFICIAL_LINKS["bed_mesh"],
        "key_sections": [
            "[bed_mesh]",
            "mesh_min / mesh_max — define probe area",
            "probe_count — grid density (3,3 or 5,5 typical)",
            "mesh_pps — points per segment for interpolation",
            "fade_start / fade_end — gradual disengagement of mesh",
            "BED_MESH_CALIBRATE — generate the mesh",
            "BED_MESH_PROFILE LOAD=<name> — switch profiles",
        ],
        "fracktal_notes": (
            "Dragon printers define custom bed_calibration positions in "
            "PRINTER_VARIABLES gcode_macro. Check variable_bed_calibration_x1/y1/x2/y2 "
            "in the active PRINTER_*.cfg."
        ),
    },
    "input_shaper": {
        "title": "Input Shaper / Resonance Compensation",
        "description": (
            "Input shaping cancels mechanical ringing/ghosting by preprocessing "
            "stepper motion through a digital filter tuned to the printer's "
            "resonant frequencies."
        ),
        "link": OFFICIAL_LINKS["resonance_compensation"],
        "key_sections": [
            "[input_shaper]",
            "shaper_type_x / shaper_type_y — ei, mzv, zv, 2hump_ei, 3hump_ei",
            "shaper_freq_x / shaper_freq_y — Hz from calibration",
            "[adxl345] — ADXL chip config per toolhead",
            "TEST_RESONANCES AXIS=X — generates raw data",
            "SHAPER_CALIBRATE — automated end-to-end calibration",
            "calibrate_shaper.py on Pi processes CSV → recommendation",
        ],
        "fracktal_notes": (
            "Fracktal printers have ADXL345 on each toolhead MCU. Toolhead 0 ADXL "
            "is on cs_pin: toolhead0: gpio13. Run SHAPER_CALIBRATE from OctoPrint "
            "terminal. Check TOOLHEADS_TD-01_TOOLHEAD0.cfg for exact pin assignments."
        ),
    },
    "pressure_advance": {
        "title": "Pressure Advance",
        "description": (
            "Pressure advance compensates for filament compression in the extruder "
            "by advancing/retracting filament slightly at corner starts/ends."
        ),
        "link": OFFICIAL_LINKS["pressure_advance"],
        "key_sections": [
            "[extruder]",
            "pressure_advance: <value> — typical 0.02–0.08 for direct drive",
            "pressure_advance_smooth_time: 0.040 — smoothing window",
            "TUNING_TOWER for automated calibration during test print",
            "SET_PRESSURE_ADVANCE ADVANCE=<value> — runtime override",
        ],
        "fracktal_notes": (
            "TD-01 direct drive extruder typically needs 0.02–0.08 PA. "
            "Uncomment pressure_advance in TOOLHEADS_TD-01_TOOLHEAD0.cfg "
            "and set the calibrated value. Default Dragon 400 config has it "
            "commented out (#pressure_advance: 0.2825 — this is NOT correct "
            "for TD-01, it's a placeholder from older toolhead config)."
        ),
    },
    "rotation_distance": {
        "title": "Rotation Distance / Extruder Calibration",
        "description": (
            "rotation_distance is the distance the axis moves per full stepper "
            "revolution. For extruders, calibrate by marking 120mm filament, "
            "extruding 100mm, and measuring remaining."
        ),
        "link": OFFICIAL_LINKS["rotation_distance"],
        "key_sections": [
            "[stepper_x/y/z] — rotation_distance for belt-driven axes (32 for GT2 20T)",
            "[extruder] — rotation_distance calibrated per extruder (~4.72 for TD-01)",
            "Formula: new_rd = old_rd × (expected / actual)",
            "DO NOT use steps_per_mm — Klipper uses rotation_distance",
        ],
        "fracktal_notes": (
            "Dragon/TwinDragon X/Y: rotation_distance: 32 (GT2 belt, 20T pulley). "
            "TD-01 extruder: rotation_distance calibrated per unit (typically ~4.72). "
            "This value is tuned at the factory but may drift with gear wear."
        ),
    },
    "pid_calibration": {
        "title": "PID Temperature Calibration",
        "description": (
            "PID (Proportional-Integral-Derivative) tuning optimizes heater "
            "temperature control. Run after changing heater cartridge, thermistor, "
            "hotend, nozzle, or power supply."
        ),
        "link": OFFICIAL_LINKS["config_reference"],
        "key_sections": [
            "[extruder] / [heater_bed]",
            "control: pid",
            "pid_Kp / pid_Ki / pid_Kd — auto-calculated by PID_CALIBRATE",
            "PID_CALIBRATE HEATER=extruder TARGET=200",
            "SAVE_CONFIG after calibration",
        ],
        "fracktal_notes": (
            "Dragon uses PID for both extruder and bed. Standard values in "
            "TOOLHEADS_TD-01_TOOLHEAD0.cfg: pid_Kp: 17.062, pid_Ki: 0.455, "
            "pid_Kd: 159.960. These were factory-tuned for the specific "
            "heater/thermistor combination. Re-run PID_CALIBRATE if you "
            "change the heater cartridge or thermistor."
        ),
    },
    "mcu_diagnostics": {
        "title": "MCU Communication Diagnostics",
        "description": (
            "Diagnosing USB/CANbus communication issues between the Raspberry Pi "
            "and printer MCU(s). Symptoms: Lost communication, timer too close, "
            "bytes_retransmit > 0 in stats."
        ),
        "link": OFFICIAL_LINKS["debugging"],
        "key_sections": [
            "Check klippy.log for ' Lost communication with MCU'",
            "Stats lines: bytes_retransmit should be 0",
            "buffer_time should stay above 2.0s",
            "Dmesg: 'dmesg | grep -i usb' for disconnect events",
            "USB: Use /dev/serial/by-id/ path, not /dev/ttyUSB0",
            "CANbus: Verify UUID, 120Ω termination, bitrate",
            "Reduce microsteps from 16→8 if Timer too close",
        ],
        "fracktal_notes": (
            "Multi-MCU Fracktal printers (toolhead MCU via CANbus) are especially "
            "sensitive to CANbus issues. Check canbus_uuid is NOT 'XXXXXXXXXXX' — "
            "this placeholder must be replaced. Run canbus_query.py on the Pi."
        ),
    },
    "endstop_diagnostics": {
        "title": "Endstop & Homing Diagnostics",
        "description": (
            "Diagnosing endstop and homing failures. Use QUERY_ENDSTOPS to check "
            "state, check wiring with endstop_pin pull-up (^) and invert (!)."
        ),
        "link": OFFICIAL_LINKS["config_reference"],
        "key_sections": [
            "[stepper_x/y/z]",
            "endstop_pin: ^!PA3 — ^ = pull-up, ! = invert (NC switches)",
            "QUERY_ENDSTOPS — shows open/triggered for each",
            "position_endstop / position_max must be correct",
            "homing_speed / homing_retract_dist",
            "homing_positive_dir: true/false",
        ],
        "fracktal_notes": (
            "Dragon endstops use normally-closed (NC) switches with ^! pull-up "
            "inversion on most pins. Check BASE_DRAGON.cfg: endstop_pin: ^PF2 "
            "for Y, endstop_pin: ^!PC2 for Z (varies by model). TwinDragon "
            "uses different pins for dual_carriage endstop."
        ),
    },
    "thermistor_diagnostics": {
        "title": "Thermistor & Temperature Sensor Diagnostics",
        "description": (
            "Diagnosing thermistor faults: ADC out of range, temperature spikes, "
            "sensor errors. Verify sensor_type, wiring, and pull-up resistor."
        ),
        "link": OFFICIAL_LINKS["config_reference"],
        "key_sections": [
            "[extruder] / [heater_bed]",
            "sensor_type — must match physical thermistor exactly",
            "sensor_pin — verify correct ADC pin",
            "pullup_resistor — 4700 for most NTC 100K thermistors",
            "min_temp / max_temp — safety limits",
            "QUERY_ADC — shows raw ADC reading for each sensor",
            "[verify_heater extruder] — automatic heater verification",
        ],
        "fracktal_notes": (
            "Standard Fracktal thermistor: EPCOS 100K B57560G104F. This is a "
            "common NTC 100K thermistor. Do NOT use 'Generic 3950' which is "
            "a different thermistor curve. The [verify_heater extruder] section "
            "in TOOLHEADS_TD-01_TOOLHEAD0.cfg has custom parameters: "
            "max_error: 120, check_gain_time: 20, hysteresis: 40, heating_gain: 6. "
            "If verify_heater triggers falsely, adjust these values."
        ),
    },
    "stepper_diagnostics": {
        "title": "Stepper Driver Diagnostics",
        "description": (
            "Diagnosing stepper motor issues: layer shifts, skipped steps, "
            "overheating, noise. Check TMC driver settings, currents, microsteps."
        ),
        "link": OFFICIAL_LINKS["tmc_drivers"],
        "key_sections": [
            "[tmc5160 stepper_x] — SPI-controlled TMC5160 driver",
            "[tmc2209 extruder] — UART-controlled TMC2209 driver",
            "run_current — operating current in Amps (1.20 for X/Y, 0.85 for extruder)",
            "hold_current — idle current (0.60 for X/Y)",
            "stealthchop_threshold — speed above which to disable StealthChop",
            "interpolate: False — disable for more torque at low speeds",
            "sense_resistor — 0.075 for BTT Octopus (Fracktal standard)",
        ],
        "fracktal_notes": (
            "Fracktal uses TMC5160 on X/Y (SPI, higher current, better for "
            "high-speed CoreXY) and TMC2209 on extruder (UART, quieter, lower "
            "current). TMC5160 sense_resistor: 0.075 (BTT Octopus). If steppers "
            "overheat, reduce run_current by 10–15% and recheck print quality. "
            "TwinDragon dual_carriage uses identical TMC5160 settings."
        ),
    },
    "canbus": {
        "title": "CANbus Setup & Diagnostics",
        "description": (
            "CANbus communication between Raspberry Pi and toolhead MCUs. "
            "Enables cleaner wiring and higher reliability for multi-MCU setups."
        ),
        "link": OFFICIAL_LINKS["canbus"],
        "key_sections": [
            "[mcu toolhead0]",
            "canbus_uuid: <unique-id> — from canbus_query.py",
            "canbus_interface: can0",
            "CANbus speed: 500000 or 1000000",
            "120Ω termination required at both ends",
            "Check 'ip -s link show can0' for errors",
        ],
        "fracktal_notes": (
            "Fracktal uses CANbus for toolhead MCUs on all models. The canbus_uuid "
            "in printer.cfg is a PLACEHOLDER (XXXXXXXXXXX) that must be replaced "
            "with the actual UUID from each toolhead MCU. Run on the Pi: "
            "'~/klippy-env/bin/python ~/klipper/scripts/canbus_query.py can0'. "
            "Each toolhead MCU will report its UUID — copy into the appropriate "
            "[mcu toolheadX] section."
        ),
    },
}

# ── Troubleshooting Guides ────────────────────────────────────────────────────

TROUBLESHOOTING = {
    "heater_error": {
        "title": "Heater Not Heating / Thermal Runaway",
        "symptoms": [
            "Klipper reports 'Heater extruder not heating at expected rate'",
            "Temperature drops during print",
            "Thermal runaway protection triggers",
        ],
        "checks": [
            "1. Run `PID_CALIBRATE HEATER=extruder TARGET=200` — re-tune PID",
            "2. Check heater cartridge resistance with multimeter (~3–5Ω for 40W)",
            "3. Verify thermistor is fully seated in heat block",
            "4. Check sensor_type matches: `EPCOS 100K B57560G104F` for Fracktal",
            "5. Run `QUERY_ADC` — compare raw values to expected range",
            "6. Check [verify_heater extruder] thresholds are not too aggressive",
            "7. Inspect wiring for loose connections or frayed wires",
        ],
        "related_commands": [
            "PID_CALIBRATE", "QUERY_ADC", "SAVE_CONFIG",
        ],
    },
    "mcu_disconnect": {
        "title": "MCU Communication Lost / Disconnects",
        "symptoms": [
            "'Lost communication with MCU' in klippy.log",
            "Printer stops mid-print, heaters shut off",
            "Frequent 'Timer too close' errors",
        ],
        "checks": [
            "1. Check USB cable quality — use shielded cable, < 2m length",
            "2. Verify CANbus termination (120Ω at both ends) if using CAN",
            "3. Run `visualize_data.py --type stats` to check retransmit rate",
            "4. Check Pi power supply — undervoltage causes USB resets",
            "5. For USB: use /dev/serial/by-id/ path, never /dev/ttyUSB0",
            "6. For CAN: verify UUID with canbus_query.py",
            "7. Reduce microsteps from 16→8 in stepper config if Timer too close",
            "8. Check grounding — poor ground causes communication noise",
        ],
        "related_commands": [
            "FIRMWARE_RESTART", "dmesg | grep -i usb",
            "ip -s link show can0", "MEASURE_AXES_NOISE",
        ],
    },
    "layer_shift": {
        "title": "Layer Shifts / Skipped Steps",
        "symptoms": [
            "Print layers are offset in X or Y direction",
            "Audible clicking or grinding from steppers",
            "TMC driver over-temperature warning",
        ],
        "checks": [
            "1. Check belt tension — should 'twang' at ~50–60Hz (guitar tuner app)",
            "2. Verify stepper run_current — too low causes skips, too high causes overheat",
            "3. Check for mechanical binding — move axis by hand with power off",
            "4. Reduce acceleration/velocity in [printer] section",
            "5. Enable input shaper to reduce mechanical stress",
            "6. Check TMC driver cooling — TMC5160 needs airflow above 1.0A",
            "7. Run `MEASURE_AXES_NOISE` — high noise suggests wiring/grounding issue",
            "8. Verify rotation_distance is correct for the pulley tooth count",
        ],
        "related_commands": [
            "TEST_RESONANCES", "SHAPER_CALIBRATE", "MEASURE_AXES_NOISE",
        ],
    },
    "first_layer": {
        "title": "First Layer / Bed Adhesion Issues",
        "symptoms": [
            "First layer not sticking to bed",
            "Nozzle too close/far from bed in different areas",
            "Elephant's foot (first layer squished too much)",
        ],
        "checks": [
            "1. Run `PROBE_CALIBRATE` — verify paper test at bed center",
            "2. Run `PROBE_ACCURACY SAMPLES=10` — std dev should be < 0.005mm",
            "3. Run `BED_SCREWS_ADJUST` if you have manual bed screws",
            "4. Run `BED_MESH_CALIBRATE` to generate new mesh",
            "5. Verify mesh is loaded: `BED_MESH_PROFILE LOAD=default`",
            "6. Check START_PRINT macro includes `BED_MESH_PROFILE LOAD=default`",
            "7. Clean bed surface with IPA — oils prevent adhesion",
            "8. Verify Z offset in [probe] or [bltouch] section",
        ],
        "related_commands": [
            "PROBE_CALIBRATE", "PROBE_ACCURACY",
            "BED_MESH_CALIBRATE", "BED_SCREWS_ADJUST",
            "BED_MESH_OUTPUT", "SAVE_CONFIG",
        ],
    },
    "print_quality": {
        "title": "General Print Quality Issues",
        "symptoms": [
            "Ringing/ghosting around corners",
            "Stringing between parts",
            "Inconsistent extrusion / under-extrusion",
            "Blobs or zits on surface",
        ],
        "checks": [
            "1. Run `SHAPER_CALIBRATE` to tune input shaper (requires ADXL345)",
            "2. Tune pressure advance with TUNING_TOWER test print",
            "3. Calibrate extruder rotation_distance (mark 120mm, extrude 100mm, measure)",
            "4. Check filament diameter in slicer matches actual (1.75mm nominal)",
            "5. Verify nozzle_diameter in config (0.400 for standard TD-01)",
            "6. Check extruder tension — too loose = under-extrusion, too tight = grinding",
            "7. Dry filament — moisture causes stringing and blobs",
        ],
        "related_commands": [
            "SHAPER_CALIBRATE", "TUNING_TOWER",
            "SET_PRESSURE_ADVANCE", "SAVE_CONFIG",
        ],
    },
}

# ── Klipper Tools on the Pi ───────────────────────────────────────────────────

KLIPPER_SCRIPTS = {
    "calibrate_shaper.py": {
        "path": "~/klipper/scripts/calibrate_shaper.py",
        "description": "Process ADXL345 resonance data and recommend input shaper",
        "usage": "~/klippy-env/bin/python ~/klipper/scripts/calibrate_shaper.py /tmp/resonances_x_*.csv -o /tmp/shaper_calibrate.png",
    },
    "graph_extruder.py": {
        "path": "~/klipper/scripts/graph_extruder.py",
        "description": "Visualize extruder motion to verify rotation_distance",
        "usage": "~/klippy-env/bin/python ~/klipper/scripts/graph_extruder.py /tmp/extruder_test_*.csv",
    },
    "graph_accelerometer.py": {
        "path": "~/klipper/scripts/graph_accelerometer.py",
        "description": "Plot raw ADXL345 accelerometer data as frequency spectrum",
        "usage": "~/klippy-env/bin/python ~/klipper/scripts/graph_accelerometer.py -c /tmp/raw_data_*.csv -o /tmp/resonances.png",
    },
    "graph_motion.py": {
        "path": "~/klipper/scripts/graph_motion.py",
        "description": "Plot stepper motion profile (velocity, acceleration, position)",
        "usage": "~/klippy-env/bin/python ~/klipper/scripts/graph_motion.py /tmp/motion_test_*.csv",
    },
    "graph_temp_sensor.py": {
        "path": "~/klipper/scripts/graph_temp_sensor.py",
        "description": "Plot temperature sensor response over time (PID validation)",
        "usage": "~/klippy-env/bin/python ~/klipper/scripts/graph_temp_sensor.py /tmp/temp_data_*.csv",
    },
    "logextract.py": {
        "path": "~/klipper/scripts/logextract.py",
        "description": "Extract structured data from klippy.log for external analysis",
        "usage": "~/klippy-env/bin/python ~/klipper/scripts/logextract.py ~/printer_data/logs/klippy.log",
    },
    "canbus_query.py": {
        "path": "~/klipper/scripts/canbus_query.py",
        "description": "Query CANbus for connected MCU UUIDs",
        "usage": "~/klippy-env/bin/python ~/klipper/scripts/canbus_query.py can0",
    },
    "flash-sdcard.sh": {
        "path": "~/klipper/scripts/flash-sdcard.sh",
        "description": "Flash Klipper firmware to MCU via SD card",
        "usage": "~/klipper/scripts/flash-sdcard.sh -d /dev/serial/by-id/usb-... -b btt-octopus-f446",
    },
    "klipper-mcu.service": {
        "path": "/etc/systemd/system/klipper-mcu.service",
        "description": "Systemd service for Linux process MCU (RPi secondary MCU)",
        "usage": "sudo systemctl restart klipper-mcu",
    },
}

# ── Klipper Internal APIs ─────────────────────────────────────────────────────

KLIPPER_APIS = {
    "moonraker_api": {
        "description": (
            "Moonraker is Klipper's web API server (WebSocket + HTTP). "
            "Though Fracktal uses OctoPrint instead of Moonraker, "
            "Moonraker's API can coexist and provides additional diagnostics."
        ),
        "endpoint_examples": [
            "GET /printer/info — printer state + version",
            "GET /printer/objects/query?extruder — query specific objects",
            "GET /server/temperature_store — temperature history",
            "POST /printer/gcode/script?script=RESTART — send gcode",
            "WebSocket subscribe to 'notify_status_update' for live data",
        ],
        "note": "Fracktal uses OctoPrint, not Moonraker. This is reference only.",
    },
    "octoprint_api": {
        "description": (
            "OctoPrint REST API — the primary interface for Fracktal printers. "
            "Use the octoprint_api.py script for diagnostics."
        ),
        "endpoint_examples": [
            "GET /api/printer — printer state + temperatures",
            "GET /api/printer?history=true&limit=20 — temp history",
            "GET /api/connection — connection state (port, baudrate, status)",
            "POST /api/connection — connect/disconnect (command: connect)",
            "GET /api/job — current print job status + progress",
            "POST /api/job — start/cancel/pause/restart (command: pause)",
            "GET /api/files/local — list uploaded G-code files",
            "GET /api/settings — OctoPrint settings + plugins",
            "GET /api/logs — available log files for download",
        ],
    },
}


# ── Main functions ────────────────────────────────────────────────────────────

def list_commands(category: Optional[str] = None) -> str:
    """List all Klipper diagnostic G-code commands."""
    lines = []
    lines.append("=" * 60)
    lines.append("KLIPPER DIAGNOSTIC G-CODE COMMANDS")
    lines.append("=" * 60)

    categories: dict[str, list] = {}
    for name, info in GCODE_COMMANDS.items():
        cat = info["category"]
        if category and cat != category:
            continue
        categories.setdefault(cat, []).append((name, info))

    for cat in sorted(categories):
        lines.append(f"\n--- {cat.upper()} ---")
        for name, info in sorted(categories[cat]):
            lines.append(f"  {name}")
            lines.append(f"    {info['description']}")
            lines.append(f"    Usage: {info['usage']}")
            if info.get("note"):
                lines.append(f"    ⚠ {info['note']}")

    lines.append(f"\nTotal: {len(GCODE_COMMANDS)} commands")
    lines.append(f"\nFull reference: {OFFICIAL_LINKS['gcode']}")
    return "\n".join(lines)


def show_command(name: str) -> str:
    """Show detailed info for a specific G-code command."""
    cmd = GCODE_COMMANDS.get(name.upper())
    if not cmd:
        # Try partial match
        matches = [
            n for n in GCODE_COMMANDS
            if name.upper() in n.upper()
        ]
        if matches:
            return (
                f"Command '{name}' not found. Did you mean: {', '.join(matches)}?"
            )
        return f"Command '{name}' not found. Use --list-commands to see all."

    lines = []
    lines.append("=" * 50)
    lines.append(f"KLIPPER COMMAND: {name.upper()}")
    lines.append("=" * 50)
    lines.append(f"Category: {cmd['category']}")
    lines.append(f"Description: {cmd['description']}")
    lines.append(f"Usage: {cmd['usage']}")
    if cmd.get("note"):
        lines.append(f"\n⚠ Note: {cmd['note']}")
    return "\n".join(lines)


def list_topics() -> str:
    """List all documentation topics."""
    lines = []
    lines.append("=" * 60)
    lines.append("KLIPPER DOCUMENTATION TOPICS")
    lines.append("=" * 60)

    for key, topic in DOC_TOPICS.items():
        lines.append(f"\n--- {topic['title']} ---")
        lines.append(f"  Topic key: {key}")
        lines.append(f"  {topic['description'][:120]}...")
        lines.append(f"  Docs: {topic['link']}")

    lines.append(f"\nTotal: {len(DOC_TOPICS)} topics")
    return "\n".join(lines)


def show_topic(key: str) -> str:
    """Show detailed info for a specific documentation topic."""
    topic = DOC_TOPICS.get(key)
    if not topic:
        matches = [k for k in DOC_TOPICS if key.lower() in k.lower()]
        if matches:
            return (
                f"Topic '{key}' not found. Did you mean: {', '.join(matches)}?"
            )
        return (
            f"Topic '{key}' not found. Use --list-topics to see all. "
            f"Try --search '<keyword>' to find relevant topics."
        )

    lines = []
    lines.append("=" * 60)
    lines.append(f"KLIPPER TOPIC: {topic['title']}")
    lines.append("=" * 60)
    lines.append(f"\n{topic['description']}")
    lines.append(f"\n📖 Official docs: {topic['link']}")
    lines.append(f"\nKey sections to read:")
    for section in topic["key_sections"]:
        lines.append(f"  • {section}")

    if topic.get("fracktal_notes"):
        lines.append(f"\n🔧 Fracktal-specific notes:")
        lines.append(f"  {topic['fracktal_notes']}")

    lines.append(f"\n--- Related Commands ---")
    related = [
        (name, info) for name, info in GCODE_COMMANDS.items()
        if any(
            word in topic["title"].lower()
            or word in key.lower()
            for word in name.lower().split("_")
        )
    ][:5]
    if related:
        for name, info in related:
            lines.append(f"  {name}: {info['description'][:80]}")
    else:
        lines.append("  (see --list-commands for all diagnostic commands)")

    return "\n".join(lines)


def search_topics(query: str) -> str:
    """Search all documentation topics, commands, and troubleshooting for a query."""
    q = query.lower()
    results: list[tuple[str, str, str]] = []

    # Search topics
    for key, topic in DOC_TOPICS.items():
        if q in key.lower() or q in topic["title"].lower() or q in topic["description"].lower():
            results.append(("Topic", key, topic["title"]))

    # Search commands
    for name, info in GCODE_COMMANDS.items():
        if q in name.lower() or q in info["description"].lower() or q in info.get("note", "").lower():
            results.append(("Command", name, info["description"]))

    # Search troubleshooting
    for key, guide in TROUBLESHOOTING.items():
        if q in key.lower() or q in guide["title"].lower():
            results.append(("Guide", key, guide["title"]))
        for symptom in guide.get("symptoms", []):
            if q in symptom.lower():
                results.append(("Guide", key, guide["title"]))
                break

    if not results:
        return (
            f"No results found for '{query}'. Try:\n"
            f"  --list-topics    (see all documentation topics)\n"
            f"  --list-commands  (see all diagnostic commands)\n"
            f"  --diagnose '<symptom>' (troubleshooting guides)\n"
            f"  --links          (all official Klipper doc URLs)"
        )

    lines = []
    lines.append("=" * 60)
    lines.append(f"KLIPPER REFERENCE SEARCH: '{query}'")
    lines.append(f"Found {len(results)} result(s)")
    lines.append("=" * 60)

    for rtype, key, desc in results[:20]:
        if rtype == "Topic":
            lines.append(f"\n📖 [{rtype}] {key}")
            lines.append(f"   {desc}")
            lines.append(f"   Docs: {DOC_TOPICS.get(key, {}).get('link', OFFICIAL_LINKS['home'])}")
        elif rtype == "Command":
            lines.append(f"\n⚙ [{rtype}] {key}")
            lines.append(f"   {desc}")
            lines.append(f"   Usage: {GCODE_COMMANDS.get(key, {}).get('usage', 'N/A')}")
        elif rtype == "Guide":
            lines.append(f"\n🔧 [{rtype}] {key}")
            lines.append(f"   {desc}")
            guide = TROUBLESHOOTING.get(key, {})
            for check in guide.get("checks", [])[:3]:
                lines.append(f"   {check}")

    return "\n".join(lines)


def show_troubleshooting(key: str) -> str:
    """Show a specific troubleshooting guide."""
    guide = TROUBLESHOOTING.get(key)
    if not guide:
        matches = [k for k in TROUBLESHOOTING if key.lower() in k.lower()]
        if matches:
            return (
                f"Guide '{key}' not found. Did you mean: {', '.join(matches)}?"
            )
        return f"Guide '{key}' not found. Try: {', '.join(TROUBLESHOOTING.keys())}"

    lines = []
    lines.append("=" * 60)
    lines.append(f"TROUBLESHOOTING: {guide['title']}")
    lines.append("=" * 60)

    lines.append("\nSymptoms:")
    for s in guide["symptoms"]:
        lines.append(f"  • {s}")

    lines.append("\nDiagnostic Checks (in order):")
    for c in guide["checks"]:
        lines.append(f"  {c}")

    lines.append("\nRelated Commands:")
    for cmd in guide["related_commands"]:
        if cmd in GCODE_COMMANDS:
            lines.append(f"  {cmd}: {GCODE_COMMANDS[cmd]['description']}")
        else:
            lines.append(f"  {cmd}")

    return "\n".join(lines)


def show_links() -> str:
    """Show all official Klipper documentation links."""
    lines = []
    lines.append("=" * 60)
    lines.append("OFFICIAL KLIPPER DOCUMENTATION LINKS")
    lines.append("=" * 60)

    lines.append("\n--- Primary Sources ---")
    lines.append(f"  Klipper Home:        {OFFICIAL_LINKS['home']}")
    lines.append(f"  GitHub Repository:   {OFFICIAL_LINKS['github']}")
    lines.append(f"  Config Reference:    {OFFICIAL_LINKS['config_reference']}")
    lines.append(f"  G-Codes Reference:   {OFFICIAL_LINKS['gcode']}")
    lines.append(f"  Status Reference:    {OFFICIAL_LINKS['status_reference']}")
    lines.append(f"  Installation Guide:  {OFFICIAL_LINKS['installation']}")
    lines.append(f"  Debugging Guide:     {OFFICIAL_LINKS['debugging']}")
    lines.append(f"  FAQ:                 {OFFICIAL_LINKS['faq']}")

    lines.append("\n--- Calibration & Tuning ---")
    lines.append(f"  Bed Mesh:            {OFFICIAL_LINKS['bed_mesh']}")
    lines.append(f"  Resonance Comp:      {OFFICIAL_LINKS['resonance_compensation']}")
    lines.append(f"  Pressure Advance:    {OFFICIAL_LINKS['pressure_advance']}")
    lines.append(f"  Probe Calibrate:     {OFFICIAL_LINKS['probe_calibrate']}")
    lines.append(f"  Rotation Distance:   {OFFICIAL_LINKS['rotation_distance']}")
    lines.append(f"  Skew Correction:     {OFFICIAL_LINKS['skew_correction']}")
    lines.append(f"  Manual Level:        {OFFICIAL_LINKS['manual_level']}")

    lines.append("\n--- Hardware ---")
    lines.append(f"  Kinematics:          {OFFICIAL_LINKS['kinematics']}")
    lines.append(f"  MCU Commands:        {OFFICIAL_LINKS['mcu']}")
    lines.append(f"  RPi Microcontroller: {OFFICIAL_LINKS['rpi_microcontroller']}")
    lines.append(f"  CANbus:              {OFFICIAL_LINKS['canbus']}")
    lines.append(f"  TMC Drivers:         {OFFICIAL_LINKS['tmc_drivers']}")
    lines.append(f"  Endstop Phase:       {OFFICIAL_LINKS['endstop_phase']}")
    lines.append(f"  Temp Sensors:        {OFFICIAL_LINKS['temperature_sensors']}")

    lines.append("\n--- Developer ---")
    lines.append(f"  Code Overview:       {OFFICIAL_LINKS['code_overview']}")
    lines.append(f"  API Server:          {OFFICIAL_LINKS['api_server']}")
    lines.append(f"  SDCard Loops:        {OFFICIAL_LINKS['sdcard_loop']}")

    lines.append(f"\n--- Klipper Tools (on Pi) ---")
    for name, info in KLIPPER_SCRIPTS.items():
        lines.append(f"  {name}: {info['description'][:100]}")

    return "\n".join(lines)


def show_klipper_tools() -> str:
    """Show Klipper scripts and tools available on the Raspberry Pi."""
    lines = []
    lines.append("=" * 60)
    lines.append("KLIPPER TOOLS & SCRIPTS ON THE RASPBERRY PI")
    lines.append("=" * 60)

    for name, info in KLIPPER_SCRIPTS.items():
        lines.append(f"\n--- {name} ---")
        lines.append(f"  Path: {info['path']}")
        lines.append(f"  {info['description']}")
        lines.append(f"  Usage: {info['usage']}")

    lines.append("\n--- Klipper Python Environment ---")
    lines.append("  Python venv: ~/klippy-env/")
    lines.append("  Python binary: ~/klippy-env/bin/python")
    lines.append("  All klipper scripts require this venv, not system Python.")

    return "\n".join(lines)


def fetch_doc(doc_name: str) -> str:
    """Attempt to fetch a Klipper doc from GitHub raw. Returns URL for manual fetch."""
    if doc_name not in RAW_DOC_URLS:
        available = ", ".join(RAW_DOC_URLS.keys())
        return (
            f"Document '{doc_name}' not in the fetchable list.\n"
            f"Available: {available}\n"
            f"Browse all docs: {OFFICIAL_LINKS['home']}"
        )

    url = RAW_DOC_URLS[doc_name]
    try:
        import requests
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        content = resp.text
        # Truncate to reasonable size
        if len(content) > 8000:
            content = content[:8000] + "\n\n... (truncated — see full doc at link above)"
        return (
            f"--- {doc_name} (fetched from GitHub) ---\n"
            f"Full doc: {OFFICIAL_LINKS.get(doc_name.replace('.md', '').lower(), url)}\n\n"
            f"{content}"
        )
    except ImportError:
        return (
            f"Cannot auto-fetch (requests not installed). Open in browser:\n"
            f"  {OFFICIAL_LINKS.get(doc_name.replace('.md', '').lower(), url)}"
        )
    except Exception as e:
        return (
            f"Fetch failed: {e}\n"
            f"Open manually: {OFFICIAL_LINKS.get(doc_name.replace('.md', '').lower(), url)}"
        )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Klipper documentation, diagnostics, and command reference"
    )
    parser.add_argument(
        "--topic", "-t",
        help="Show a specific documentation topic (e.g., bed_mesh, input_shaper)",
    )
    parser.add_argument(
        "--command", "-c",
        help="Show a specific G-code command (e.g., QUERY_ENDSTOPS, PID_CALIBRATE)",
    )
    parser.add_argument(
        "--list-commands",
        action="store_true",
        help="List all Klipper diagnostic G-code commands",
    )
    parser.add_argument(
        "--list-topics",
        action="store_true",
        help="List all documentation topics",
    )
    parser.add_argument(
        "--search", "-s",
        help="Search all reference material for a keyword",
    )
    parser.add_argument(
        "--diagnose", "-d",
        help="Show troubleshooting guide for a symptom (e.g., heater_error, layer_shift)",
    )
    parser.add_argument(
        "--links",
        action="store_true",
        help="Show all official Klipper documentation links",
    )
    parser.add_argument(
        "--tools",
        action="store_true",
        help="Show Klipper scripts and tools available on the Pi",
    )
    parser.add_argument(
        "--fetch",
        help="Fetch a Klipper doc from GitHub (e.g., Config_Reference.md, G-Codes.md)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    result: str = ""

    if args.list_commands:
        result = list_commands()
    elif args.list_topics:
        result = list_topics()
    elif args.links:
        result = show_links()
    elif args.tools:
        result = show_klipper_tools()
    elif args.topic:
        result = show_topic(args.topic)
    elif args.command:
        result = show_command(args.command)
    elif args.search:
        result = search_topics(args.search)
    elif args.diagnose:
        result = show_troubleshooting(args.diagnose)
    elif args.fetch:
        result = fetch_doc(args.fetch)
    else:
        # Default: show overview
        result = "\n".join([
            show_links(),
            "",
            "Use --list-commands, --list-topics, --search <keyword>, --diagnose <symptom>,",
            "--topic <name>, --command <name>, --links, --tools, or --fetch <doc>.",
        ])

    if args.json:
        print(json.dumps({"result": result}, indent=2))
    else:
        print(result)


if __name__ == "__main__":
    main()
