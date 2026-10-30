# JULIA250 (192.168.0.184)

New machine, commissioned 2026-10-29 on the Pi CM4 that was the TwinDragon 600 V2
reference unit (`docs/STATUS.md`). The CM4/OS/OctoPrint stack is unchanged; the
electronics are new.

| | |
|---|---|
| Kinematics | CoreXY, single nozzle, 250 x 250 x 295 (Z endstop at Z max, `position_endstop` 295 since 2026-10-30, `variable_bed_z_max` 290 (set on the printer); the bed mesh says the real travel is about 299, see below) |
| Main board | BTT Manta M5P V1.0, STM32G0B1, USB-to-CAN bridge, `canbus_uuid 90b4e5c54d1f` (replacement board; the first, faulty one was `28fd68d251e1`) |
| Toolhead | TD-01 RP2040, CAN 1 Mbit/s, `canbus_uuid 0b9c82a2706e` (`TOOLHEADS_TD-01_TOOLHEAD0.cfg`) |
| Drivers | M2 = A (`stepper_x`, CS PD8), M1 = B (`stepper_y`, CS PD9), M3 = Z (CS PB10): TMC5160 on software SPI (SCK PB13, MISO PB14, MOSI PB15). Extruder TMC2209 on the toolhead, plus `extruder_stepper extruder_side0` on M4 (TMC5160, CS PB2, `rotation_distance` 7.710 from the Dragon, not verified), synced to it as on the Dragon |
| Endstops | X min on the toolhead (gpio7), Y max on MIN1 (PD3), Z max on MIN2 (PD2) (moved 2026-10-30) |
| Filament sensors | T0 runout switch on MIN3 (PC3), T0 jam/motion encoder on MIN4 (PC2), in BASE_JULIA.cfg (the shared T0_FILAMENT_* files use M8P pins) |
| Bed | Heater on HE0 (PC5), thermistor on TH0 (PA1), EPCOS 100K (moved from HB PA5 / TB PA0 on 2026-10-30) |
| Chamber heater | `[heater_generic Chamber]` on HE1 (PA7), thermistor ATC Semitec 104GT-2 on TH1 (PA2), `gcode_id: C`, macros `M141`/`M191`/`CHAMBER_OFF`; from ControlCenter `firmware/CHAMBER_HEATER.cfg`, PID not tuned |
| Always-on fan | FAN1 (PA3), `[output_pin fan1_always_on]` value 1, shutdown_value 1 |
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
5. Travel and endstop positions (X 0, Y 250, Z 295) and `position_min` Z -6. The
   2026-10-30 bed mesh triggered at Z -3.5 to -4.6, so Z 0 is above the bed: set
   `position_endstop` from a measured nozzle-to-bed distance before printing.
6. Z current 1.0 A, `sense_resistor` 0.075 (BTT TMC5160 module): check the module.
7. Probe pin polarity (`QUERY_PROBE` triggered vs open); `z_offset` reset to 0.
8. Bed PID is the Dragon's: `PID_CALIBRATE HEATER=heater_bed TARGET=60`. The bed
   output on HE0 has not been heated yet. Chamber PID is the template's:
   `PID_CALIBRATE HEATER=Chamber TARGET=50`.
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

## 2026-10-30: wiring changes, bed mesh, chamber heater, touchscreen

### Speed test

1000 mm/s at 8000 mm/s² (same method as above): passed, no skipped steps.

### Driver sockets: M4/M5 "dead" was missing jumpers

The extruder TMC5160 was silent on SPI (`IOIN ffffffff`, `version=0xff`, then
`Unable to write tmc spi ... GLOBALSCALER` at enable) in M4 and in M5, and a
known-good Z module was silent there too, while both modules answered in M3.
Cause: SPI-mode / VM jumpers not fitted under M4/M5. After fitting them, Z on M3 and
`extruder_side0` on M4 both answer (`IOIN 30000050`, `version=0x30`). Same lesson as
the replacement board: **when a module answers in one socket and not another,
compare the jumpers under the two sockets first.** GSTAT `00000005` (reset + uv_cp)
right after power-on is normal.

The motor had first been plugged into **M3B**, which is a second connector wired in
parallel to the M3 (Z) driver, not a separate driver.

### Z travel 295 and bed mesh

`position_endstop` / `position_max` / `variable_bed_z_max` set 300 -> 295. A 5x5
`BED_MESH_CALIBRATE` (25-225 mm) then stopped after 4 points:

| Point | Probe triggered at |
|---|---|
| 25, 25 | Z -4.615 |
| 75, 25 | Z -3.700 |
| 125, 25 | Z -3.473 |
| 175, 25 | Z -3.803 |
| 225, 25 | no trigger down to Z -6 (`position_min`): `No trigger on probe after full movement` |

So the bed is about 299 mm below the Z max endstop, not 295, and the front-right corner
is more than 2 mm lower than its neighbour (or the probe does not see the bed there).
Klipper leaves the nozzle at `position_min` after this error: raise Z before anything
else. Mesh is now `probe_count: 3,3` in `PRINTER_JULIA250.cfg`; Klipper logs
`Forcing lagrange interpolation` because bicubic needs 4+ points per axis (harmless).
The 3x3 mesh has not been run yet.

### Bed and chamber heaters

- Bed moved to HE0 (PC5) / TH0 (PA1). Reads room temperature; not heated yet.
- Chamber heater added to `BASE_JULIA.cfg` from ControlCenter's
  `firmware/CHAMBER_HEATER.cfg` (no Dragon config has one), pins HE1 (PA7) / TH1 (PA2).
  Reads 28 C. Use `M141 S<t>` (set), `M191 S<t>` (set and wait), `CHAMBER_OFF`;
  `M105` reports it as `C:`.

### OctoPrint and ControlCenter changes (on the printer only)

These are not in any repo. A ControlCenter upgrade/reinstall undoes the first two.

| Change | File on the printer | Backup |
|---|---|---|
| Julia shows the chamber (home screen reading, bed/chamber toggle on the temperature screen, `M141 S0` on Cool Down) | ControlCenter `utils/printer_ui_config.py`: `CHAMBER_HEATER_PRINTERS = {'TWINDRAGON_400_HT', 'JULIA250'}` | `printer_ui_config.py.pre-julia-chamber` |
| Selecting the printer on the touchscreen keeps the chamber on | ControlCenter `config/JULIA250.profile` (new; copy of the Julia profile with `heatedChamber: true`) | none (new file) |
| OctoPrint shows and controls the chamber | `~/.octoprint/printerProfiles/_default.profile`: `heatedChamber: true` (via `PATCH /api/printerprofiles/_default`) | `_default.profile.pre-chamber` |

Upstream fix (ControlCenter repo, reference-only here: team lead decision): add
JULIA250 to `CHAMBER_HEATER_PRINTERS`, ship `JULIA250.profile`. Note the shipped
`TWINDRAGON_400_HT.profile` also has `heatedChamber: false`, so OctoPrint does not
report the HT's chamber either. The OctoPrint profile height is still 300 (Z is 295).

The chamber control on the touchscreen is the existing bed/chamber toggle (the wide
bed-icon button above the bed set-point); it was checked with remote taps and
screenshots.

### FAN1 always on: not spinning yet

`[output_pin fan1_always_on]` on PA3 (FAN1 in BTT's M5P sample config) reads
`value: 1.0`, but the fan did not spin. Open: the M5P fan-voltage jumper next to
FAN0/FAN1 (no jumper = no supply), the fan's voltage against the jumper setting,
plug polarity.

### 3.5 inch display: `QT_SCALE_FACTOR` does not work

ControlCenter is laid out with fixed geometry for 800 x 480 (`config.py`
`SCREEN_WIDTH`/`SCREEN_HEIGHT`, absolute positions in the `.ui` files). Setting
`QT_SCALE_FACTOR=0.6` in `~/.xinitrc` shrank the window to 480 x 288 but every page
drew empty and cropped: reverted (`~/.xinitrc.pre-3.5inch`). For a 480 x 320 HDMI
panel, scale the 800 x 480 output in X instead (xrandr `--scale-from 800x480`); an
SPI TFT needs its overlay first. A 480 x 320 downscale of the screens is readable.

### Remote touchscreen checks

The touchscreen can be driven over SSH without extra packages: screenshot with
`DISPLAY=:0 XAUTHORITY=/home/pi/.Xauthority ffmpeg -f x11grab -video_size 800x480 -i :0 -frames:v 1 shot.png`,
tap with a few lines of Python calling `libXtst.so.6` `XTestFakeMotionEvent` /
`XTestFakeButtonEvent` through ctypes. Control screen = sliders button at (400, 393)
on the home screen.

### Unexplained reboot

Between about 16:45 and 17:57 the Pi dropped off Wi-Fi and came back freshly booted
(up 3 min at 18:00). Cause not checked: run `pi_system_diagnostics.py --check power`
and look at the previous boot's journal.
