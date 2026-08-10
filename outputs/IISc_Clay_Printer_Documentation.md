# IISc Clay Printer — Configuration & Test Documentation
## Date: 2026-07-30 | BTT Manta M5P + CM4 | Klipper v0.13.0

---

## 1. FINAL CONFIGURATION

### Printer
- **Board**: BTT Manta M5P (STM32G0B1, 64MHz)
- **Host**: Raspberry Pi CM4 (onboard BTB)
- **Kinematics**: CoreXY
- **Build Volume**: 200 × 200 × 200 mm
- **Home**: (0, 200) — top-left (X=min, Y=max)
- **Klipper**: v0.13.0-708-g7046bd00e
- **Firmware**: FLASH_START_0000 (no bootloader), USB serial PA11/PA12

### Speed/Accel Limits (verified with 48V TMC5160)
| Setting | Value |
|---------|-------|
| max_velocity | 800 mm/s |
| max_accel | 7,000 mm/s² |

### Motor Pin Map
| Axis | Step | Dir | Enable | Driver | CS | Current |
|------|------|-----|--------|--------|-----|---------|
| X | PA10 | !PA14 | !PA13 | TMC5160 | PD8 | 1.2A |
| Y | PC8 | PC9 | !PA15 | TMC5160 | PD9 | 1.2A |
| Z | PC6 | PC7 | !PA9 | TMC5160 | PB10 | 1.2A |
| E0 (Auger) | PB12 | !PB11 | !PA8 | TMC5160 | PB2 | 0.85A |
| E1 (Plunger) | PB0 | PB1 | !PC4 | TMC5160 | PA6 | 0.85A |

### Endstops & Homing
| Axis | Pin | Position | Homing Dir | 
|------|-----|----------|-------------|
| X | ^PD2 | 0 (min) | false (←) |
| Y | ^PD3 | 200 (max) | true (→) |
| Z | ^PC3 | 0 (min) | — |

> **Note**: X and Y motors are physically swapped. Config compensates with swapped pin assignments + X dir_pin inverted (!PA14).

### TMC5160 48V Settings (all steppers)
\\\ini
stealthchop_threshold: 0     # SpreadCycle only
driver_IHOLDDELAY: 8
driver_TPOWERDOWN: 128
driver_TBL: 2
driver_TOFF: 3
driver_HEND: 5
driver_HSTRT: 7
driver_PWM_AUTOSCALE: True
\\\

### Extruders (Clay)
| Extruder | Type | Heater | Sensor |
|----------|------|--------|--------|
| E0 | Auger | PC5 | temperature_mcu |
| E1 | Plunger | PA7 | EPCOS 100K (PA2) |

---

## 2. DISPLAY & TOUCH

### Hardware
- **Display**: waveshare35a (ILI9486 SPI, 480×320, fb1)
- **HDMI**: 800×480 (fb0) → fbcp copies to fb1
- **Touch**: ADS7846 on SPI0.1

### Configuration
- /boot/config.txt: \dtoverlay=waveshare35a,rotate=90,fps=12,speed=16000000\
- /etc/X11/xorg.conf.d/99-calibration.conf:
\\\
MinX=19811, MaxX=19920, MinY=52951, MaxY=53680
SwapXY=1, InvertX=0, InvertY=1
\\\
- touch-cal.service: DISABLED (no longer used)

---

## 3. CO2 SENSOR SETUP

- **Sensor**: PASCO PS-3208 (BLE/USB)
- **Bridge**: /home/pi/co2-bridge/co2_bridge.py
- **Dummy pusher**: /usr/local/bin/co2_dummy.py (reports 0 when sensor absent)
- **Service**: co2_dummy.service (active)
- **Macros**: /home/pi/printer_data/config/co2_macros.cfg (CO2 safety, M104/M109)
- **Mainsail graph**: Shows \co2_chamber\ in temperature panel

---

## 4. SPEED/ACCEL TEST HISTORY

| Test | Speed Range | Accel | Axis | Result |
|------|------------|-------|------|--------|
| 1 | 100-1000 | 2000-10000 | X | All passed |
| 2 | 1200-3000 | 15000-50000 | X | FAILED (too aggressive) |
| 3 | 100-2000 | 20000 | X | Skipped at 600 |
| 4 | 100-2000 | 5000 | X | ALL PASSED |
| 5 | 100-2000 | 10000 | X | ALL PASSED |
| 6 | 100-2000 | 20000 | X | FAILED |
| 7 | 100-2000 | 10000 | Y | Skipped at 600 |
| 8 | 100-800 | 5000 | X+Y+Diag | ALL PASSED |
| 9 | 100-800 | 10000 | X+Y+Diag | Y failed |
| 10 | 100-800 | 15000 | X+Y+Diag | FAILED |
| 11 | 100-1000 | 10000 | X+Y+Diag | Y failed |
| 12 | 200-800 | 1000 | X+Y+Diag | ALL PASSED |
| 13 | 200-1000 | 10000 | X+Y+Diag | With 48V TMC — tested |
| **FINAL** | **400-800** | **7000** | **X+Y+Diag** | **✓ CONFIRMED** |

### Performance Summary
| Metric | Max Tested | Stable Limit |
|--------|-----------|--------------|
| Speed | 3000 mm/s | **800 mm/s** |
| Accel | 50000 mm/s² | **7,000 mm/s²** |
| Voltage | — | 48V |

---

## 5. G-CODE TEST FILES (on Pi)

| File | Description |
|------|-------------|
| /home/pi/printer_data/gcodes/circular_test.gcode | Circle pattern (G2 arcs) |
| /home/pi/printer_data/gcodes/speed_test.gcode | Original speed test |
| /home/pi/printer_data/gcodes/speed_test2.gcode | Extended 1200-3000 test |
| /home/pi/printer_data/gcodes/speed_test3.gcode | 2000 cap, 20000 accel |
| /home/pi/printer_data/gcodes/speed_slow.gcode | Slow transition test |
| /home/pi/printer_data/gcodes/speed_5k.gcode | 5000 accel test |
| /home/pi/printer_data/gcodes/speed_10k.gcode | 10000 accel test |
| /home/pi/printer_data/gcodes/speed_20k.gcode | 20000 accel test |
| /home/pi/printer_data/gcodes/speed_y.gcode | Y-axis only test |
| /home/pi/printer_data/gcodes/full_test.gcode | X+Y+Diag combined |
| /home/pi/printer_data/gcodes/spd1k.gcode | 1000mm/s test |
| /home/pi/printer_data/gcodes/spd800_1k.gcode | Conservative test |
| /home/pi/printer_data/gcodes/final_test.gcode | Final 800/7000 test |

---

## 6. CONFIG BACKUPS (on Pi)

| File | Date | Description |
|------|------|-------------|
| printer.cfg.bak | Jul 23 13:55 | Original MKS Gen L config |
| printer.cfg.bak_stepper_fix | Jul 23 17:22 | Working Manta config |
| printer.cfg.bak_latest | Jul 23 | Pre-session backup |
| printer.cfg | Current | **Final working config** |

---

## 7. KNOWN ISSUES & NOTES

1. **CoreXY axis swap**: X/Y motors physically swapped on board. Fixed via config pin swap + X dir_pin inversion (!PA14)
2. **MCU log location**: klipper.service logs to /tmp/klippy.log (NOT printer_data/logs/)
3. **Touch calibration**: xinput_calibrator works but --output-type xinput unsupported on this version
4. **Klipper v0.13.0**: MCU firmware must match — reflash if updating Klipper
5. **CO2 graph**: Shows 0 until PASCO sensor connected; bridge needs fix for global variable issue
