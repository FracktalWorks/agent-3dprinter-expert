# JULIA250 (192.168.0.184)

New machine, commissioned 2026-10-29 on the Pi CM4 that was the TwinDragon 600 V2
reference unit (`docs/STATUS.md`). The CM4/OS/OctoPrint stack is unchanged; the
electronics are new.

| | |
|---|---|
| Kinematics | CoreXY, single nozzle, 250 x 250 x 300 (Z endstop at Z max, `position_endstop` 300) |
| Main board | BTT Manta M5P V1.0, STM32G0B1, USB-to-CAN bridge, `canbus_uuid 28fd68d251e1` |
| Toolhead | TD-01 RP2040, CAN 1 Mbit/s, `canbus_uuid 0b9c82a2706e` (`TOOLHEADS_TD-01_TOOLHEAD0.cfg`) |
| Drivers | M1 = A (`stepper_x`), M2 = B (`stepper_y`), M3 = Z: TMC5160 on software SPI (SCK PB13, MISO PB14, MOSI PB15), CS PD9/PD8/PB10. Extruder TMC2209 on the toolhead |
| Endstops | X min on the toolhead (gpio7), Y max on MIN2 (PD2), Z max on MIN3 (PC3) |
| Bed | HB PA5, TB PA0, EPCOS 100K |
| Probe | PC15 (Probe / IND-DET header) |

Files in `config/` are what is deployed to `~/printer_data/config` (symlinked in
`/home/pi`). `BASE_JULIA.cfg` and `PRINTER_JULIA250.cfg` are also copied into the
installed ControlCenter `firmware/` folder, and its template `printer.cfg` has a
`#[include PRINTER_JULIA250.cfg]` line so the touchscreen can select it. A
ControlCenter upgrade overwrites that folder: the files belong in
`klipper_IDEX/fracktal_config/templates` / ControlCenter `firmware/` upstream.

Do not include the M8P add-ons (`T0_FILAMENT_*`, `MAG_DOOR.cfg`,
`ELECTRONICS_CHAMBER_COOLING.cfg`): their pins are M8P pins, and `MAG_DOOR.cfg`
drives PA5, which is the bed heater on the M5P.

Backup of the TwinDragon config set: `~/config-backup-pre-julia250-20261029-115212.tar.gz`.

## Verified 2026-10-29 (no motion)

Klipper `ready`; both MCUs on CAN, 0 rx/tx errors; TMC5160 X/Y/Z answer on SPI
(`IOIN version=0x30`), TMC2209 extruder (`0x21`); bed 28 C; endstops and probe read
`open` at rest.

## Not verified: values carried from the Dragon, check before printing

1. **Hotend thermistor reads -99.6 C (open circuit).** TD-01 has `min_temp: -130`,
   so Klipper does not shut down on it: do not heat the hotend until it reads room
   temperature.
2. Motor directions (`dir_pin`), CoreXY A/B wiring: home each axis with a hand on
   the power switch.
3. Endstop polarity: `QUERY_ENDSTOPS` with each switch pressed must read `TRIGGERED`.
4. `rotation_distance` X/Y 40 (GT2 20T pulley, set 2026-10-29) and Z 4 @ 8 microsteps: measure 100 mm moves.
5. Travel and endstop positions (X 0, Y 250, Z 300: real Z travel not yet measured) and `position_min` Z -6.
6. Z current 1.0 A, `sense_resistor` 0.075 (BTT TMC5160 module): check the module.
7. Probe pin polarity (`QUERY_PROBE` triggered vs open); `z_offset` reset to 0.
8. Bed PID is the Dragon's: `PID_CALIBRATE HEATER=heater_bed TARGET=60`.
9. Speeds are conservative (300 mm/s, 3000 mm/s², SCV 5): raise after input shaping.
10. `ptfe_tube_length` 900 and bed calibration points are placeholders.
11. Webcam: the OV5647 does not answer on I2C (`i2c read error`), check the ribbon.

## Accelerometer axes_map (measured 2026-10-29)

At rest the TD-01 ADXL345 read gravity on chip +x (9919, 222, -766); a +X move
peaked on chip -y, a +Y move on chip -z. `PRINTER_JULIA250.cfg` overrides
`[adxl345 toolhead0] axes_map: -y, -z, x`; after it, gravity reads on z
(-74, 536, 9549). The shared `TOOLHEADS_TD-01_TOOLHEAD0.cfg` still says `x,y,z`,
and the board is mounted the same way on Dragon/TwinDragon, so their shaper
results are suspect: measure one (`ACCELEROMETER_QUERY` at rest + a short +X/+Y
move per toolhead) before fixing the shared file upstream.

## Lessons from commissioning (2026-10-29)

- **First Manta M5P never stepped.** The TMC5160s answered on SPI, but MSCNT never
  changed and IOIN `refl_step`/`drv_enn` stayed constant on all three sockets, with
  every pin matching BTT's `generic-bigtreetech-manta-m5p.cfg`. Swapping the board
  fixed it: the old board is faulty. MSCNT before/after a move is the quickest proof
  that STEP reaches a driver; pick a move that is not a whole number of electrical
  cycles (Z 50 mm at rotation_distance 4 is exactly 625, so MSCNT reads the same).
- **A new board needs its jumpers copied.** On the replacement, Y/Z failed
  `Unable to write tmc spi ... GLOBALSCALER` until the SPI-mode and VM/HV jumpers
  under M2/M3 matched M1. A TMC5160 without motor power does not answer SPI.
- **A new board is blank and has a new UUID.** It enumerates as ROM DFU
  (`0483:df11`); flash `~/klipper-config-m5p-usbcanbridge.config` from
  `~/klipper_IDEX` with `make flash FLASH_DEVICE=0483:df11`. dfu-util's
  `Error 255` on leave is harmless (the board came up as gs_usb). The toolhead only
  appeared on the bus after a power cycle.
- **CoreXY direction fix:** X reversed with Y correct means swap A/B and invert
  both dirs (one axis cannot be flipped alone on CoreXY).
- **Pulley:** GT2 20T = `rotation_distance: 40` (the Dragon value 32 is 16T).
- **`G28 X` homes all axes** with the CORE_GCODE_MACROS homing_override: bare
  `X` is an empty (false) parameter, so use `G28 X0`.
- **OctoPrint "won't move to 250":** a relative jog that would end past the limit
  is rejected whole by Klipper (`Move out of range`), not clamped. Use smaller
  steps or `G90` + `G1 X250`.
- **Bed thermistor unplugged** = `ADC out of range` shutdown at startup
  (min_temp 0). A temporary negative min_temp gets past it for motion tests; restore it.

## Input shaper (2026-10-29, SHAPER_CALIBRATE at 125,125,20, axes_map -y,-z,x)

Saved in `printer.cfg` (SAVE_CONFIG block).

| Axis | Recommended | Vibrations | Max accel before over-smoothing |
|---|---|---|---|
| X | `3hump_ei` @ 80.0 Hz | 0 % | 4700 mm/s² |
| Y | `mzv` @ 34.4 Hz | 1.0 % | 3500 mm/s² |

X fits disagree (zv 43, mzv 28, ei 37.8, 2hump_ei 40.2 Hz): two close peaks,
so `3hump_ei` was chosen to cover the 30-45 Hz band. Check that the CoreXY belt
pair is equally tensioned and re-run X. Other Y fits: zv 35.8 Hz (6.2 %, 4900),
ei 38.0 Hz (0 %, 2700), 2hump_ei 48.0 Hz (2500), 3hump_ei 58.6 Hz (2500).
Raw data: [`data/calibration_data_x_20261029_181324.csv`](data/calibration_data_x_20261029_181324.csv), [`data/calibration_data_y_20261029_181324.csv`](data/calibration_data_y_20261029_181324.csv) (PSD per axis + each shaper's response; plot with `klipper_IDEX/scripts/calibrate_shaper.py`).

## XY skipped-step speed test (2026-10-29)

Method: home X and Y, read the MCU step positions (`GET_POSITION`), run 5 loops of
corner-to-corner diagonals plus a perimeter lap in the 25-225 mm box at the test
speed and acceleration, re-home, compare. Lost steps show up as multiples of 16
microsteps (1 full step = 0.2 mm at rotation_distance 40, 16 microsteps) that grow
with speed; fail threshold was 2 full steps. Z at the top. TMC5160 1.2 A, 48 V HV IN.

| Accel (mm/s²) | Speed (mm/s) | A drift | B drift | Moves | Result |
|---|---|---|---|---|---|
| 3500 | 200 | -2 | -10 | 47.8 s | OK |
| 3500 | 300 | -6 | -10 | 33.9 s | OK |
| 3500 | 400 | -5 | -13 | 27.6 s | OK |
| 3500 | 500 | +2 | -2 | 24.2 s | OK |
| 3500 | 600 | -18 | -20 | 22.3 s | OK |
| 3500 | 700 | +2 / -7 | -8 / -11 | 21.4 s | OK (run twice) |
| 3500 | 800 | -1 | -1 | 20.9 s | OK |
| 3500 | 900 | -3 | -7 | 20.8 s | OK |
| 3500 | 1000 | +7 | -3 | 20.7 s | OK |
| 8000 | 700 | -4 | -4 | 16.8 s | OK |
| 8000 | 800 | -2 | -2 | 15.7 s | OK |
| 8000 | 900 | -2 | -4 | 14.9 s | OK |
| 8000 | 1000 | -1 | -5 | 14.5 s | OK |
| 10000 | 1000 | -5 | -5 | 13.4 s | OK |

Drift is in microsteps and does not grow with speed: it is endstop repeatability
(about +-0.25 mm worst case), not skipping. At 3500 mm/s² a 200 mm side tops out
near 835 mm/s, so speeds above that were not really reached; that is why the
times barely change from 800 to 1000. The motor limit was not found.

**About 2 s after the 10000 mm/s² run, the machine lost power** (klippy.log stops
mid-write at 18:34:42, with no MCU, CAN or TMC error before it). Whether it was
switched off or the 48 V supply dropped out under deceleration is still open:
do not go above 8000 mm/s² until that is answered.

Suggested `[printer]` limits (not applied yet): `max_velocity: 600`,
`max_accel: 3500` (Y shaper limit), raise acceleration per print in the slicer
when speed matters more than detail.

## Power loss right after G28 reverted printer.cfg (2026-10-29)

After that power loss, `printer.cfg` was an Oct-24 TwinDragon version (wrong CAN
UUIDs, Klipper stuck in `startup`) and the three newest `printer-*.cfg` backups
were 0 bytes. The Fracktal homing_override runs `SAVE_CONFIG NO_RESTART=1` on every
G28, and `/` is ext4 `commit=60`, so a power cut within about a minute of homing
can lose printer.cfg. Recovery: restore the newest non-empty `printer-*.cfg`
backup (here `printer-20261029_183440.cfg`), `sync`, restart Klipper. The wrong
file was kept as `printer.cfg.twindragon-after-powerloss`.
