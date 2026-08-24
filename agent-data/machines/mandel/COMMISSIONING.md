# MANDEL — field commissioning procedure

A site visit with two jobs: **measure what the machine physically is**, because
its configuration contradicts itself, and **set up PrusaSlicer** so the customer
can slice their own parts.

Work the phases in order. Phase 3 depends on numbers only Phase 1 can produce.

> Shareable version, with tick-off boxes and a printable data sheet:
> <https://claude.ai/code/artifact/876a97e4-8c03-490d-a48a-bd6e06fced48>

| | |
|---|---|
| Machine | MANDEL (IISc clay printer), `192.168.0.34` |
| Extruder | plunger → auger, no heaters |
| Nozzle for setup | 3 mm |
| Slicer | PrusaSlicer 2.9.6 |
| Estimated time on site | 3–4 h |

---

## ⚠ Read before touching the controls

**Do not command Y above 200 mm, or X above 200 mm.** The configuration claims
both axes travel 585 mm. That number is almost certainly Z's travel, pasted onto
X and Y. Y homes to its *maximum* endstop and Klipper is told that end is Y=200 —
so a move to Y=585 would be accepted and would drive the gantry 385 mm into a
hard stop.

Every print so far has been a small object near the middle of the bed, which is
the only reason nothing has crashed. Correcting this is Phase 2, and it is the
main reason for the visit.

Two more habits of this machine:

- **The extruder motors release after 60 s idle** (by design — it keeps X/Y/Z
  homed). A released plunger can back-drive under barrel pressure, so prime last,
  immediately before resuming.
- **There are no heaters.** All temperatures read nonsense and that is expected.

---

## Phase 0 — before leaving the office

Assume no internet at the customer; the printer has been off the network before.

1. **Tools on the laptop** — PrusaSlicer 2.9.6 installed and launched once; the
   repo cloned, or `MANDEL_clay.ini`, `gen_prusaslicer_bundle.py` and
   `validate.py` from `slicer/` on a USB stick; Python 3 with `paramiko`. Read
   [`../mandel_clay_printer.md`](../mandel_clay_printer.md) §10 and §11 — §11 is
   the list of fixes already tried and failed.
2. **Measuring kit** — steel tape ≥1 m, 300 mm rule, 150 mm calipers, torch,
   printed data sheet, camera.
3. **Access confirmed in advance** — SSH to the Pi, Mainsail at
   `http://192.168.0.34`, admin rights if PrusaSlicer goes on their workstation,
   and **clay loaded** plus a spare batch (~20 mL for the acceptance print, more
   for priming).

## Phase 1 — measure what the machine actually is

The blocking unknown. Software cannot answer it: Klipper only knows what it was
told, and what it was told is self-contradictory. Take readings with the machine
**homed and stationary**.

4. **Bring it up and record state** — `FIRMWARE_RESTART`, then `CLAY_STATUS`.
   Capture the axis config verbatim:
   `grep -A11 '^\[stepper_[xyz]\]' ~/printer_data/config/printer.cfg`

   | Axis | `position_endstop` | `position_max` | homes toward |
   |---|---|---|---|
   | X | 0 | 585 | minimum |
   | Y | **200** | 585 | **maximum** |
   | Z | 585 | 585 | maximum |

5. **`G28`, then read back the position.** Expect ≈ `X0 Y200 Z585`. If Z does not
   report ~585, **stop and call** — every print so far has descended from 585 to
   Z≈1, so that figure has been load-bearing.
6. **Measure the three travels by hand.** No motion required.
   - **X travel** — nozzle centre to the far mechanical limit of X.
   - **Y travel** — nozzle is at the Y endstop end; measure to the opposite
     limit. *This is the critical figure.*
   - **Z travel** — nozzle tip to bed surface, homed.
   - **Usable bed surface**, X × Y. Record travel and usable area separately;
     where they differ, the slicer gets the smaller.
7. **Verify the scale with a 100 mm move.** Mark the home position, then
   `G28` / `G90` / `G1 X100 F3000` / `M400`, and measure the displacement. It must
   be **100.0 mm ± 0.5**. Repeat for Y (Y homes at maximum, so `G1 Y100` moves
   *away* from the endstop). **If it is not 100 mm, stop** — `rotation_distance`
   is wrong and every dimension this machine has printed is scaled.
8. **Photograph** the X endstop, the Y endstop (confirming it is at the maximum
   end), and the bed with a rule across it.

### Decision gate — what the Y measurement means

| Y travel measures | Meaning | Action |
|---|---|---|
| ≈ 200 mm | the endstop value is right; only `position_max` is wrong | Phase 2, coordinates unchanged |
| ≈ 250 mm | the endstop value is *also* wrong; the Y frame is shifted 50 mm | Phase 2, then **regenerate all existing g-code** |
| anything else | neither config figure is trustworthy | record it, apply it, flag it |

## Phase 2 — correct the axis limits

Only with the measurements in hand. This changes where the machine believes it
is, so a wrong number drives the gantry into a stop.

9. **Back up first** — `cp printer.cfg printer.cfg.bak-$(date +%F)-previsit`.
   Add yours; do not overwrite the existing July/August backups.
10. **Apply the measured travels** (values below assume both measured 250 mm):

    ```ini
    [stepper_x]
    position_max: 250        ; was 585

    [stepper_y]
    position_endstop: 250    ; was 200 — the endstop IS the max end
    position_max: 250        ; was 585
    ```

    **The file uses CRLF. Preserve it** — edit in place with `nano` on the Pi, or
    use [`sync.py`](sync.py), which handles it. For Y, `position_endstop` and
    `position_max` must be the same number: the axis homes positive, so the
    endstop *is* the top of travel, and any gap between them is the crash margin.
11. **Restart and confirm** — `FIRMWARE_RESTART`, `G28`. The reported position
    must now match the measured travel. Then approach the far corner in steps,
    **hand on the emergency stop**: `G1 X50 Y50 F3000`, `G1 X200 Y200 F3000`,
    `G1 X245 Y245 F1500`, `G28`.
12. **Tell the customer what moved.** If Y's endstop value changed, the
    coordinate frame shifted and every existing file in `~/printer_data/gcodes/`
    lands elsewhere. Say so before they run one unattended.

## Phase 3 — set up PrusaSlicer

Everything is prepared; the only value depending on Phase 1 is the bed size.

13. **Put the measured bed into the bundle** — edit `BED_X`, `BED_Y`, `MAX_Z` at
    the top of `slicer/gen_prusaslicer_bundle.py` and re-run it. The park position
    follows automatically (always the bed centre). Regenerating beats editing the
    bed shape in the UI, because the file is what gets version-controlled.
14. **Import and select** — File → Import → Import Config Bundle →
    `MANDEL_clay.ini`, then:

    | Slot | Choose | Why |
    |---|---|---|
    | Printer | `MANDEL Clay 3mm` | nozzle size lives on the printer profile |
    | Print | `Clay 3mm nozzle` | 2.0 mm layers, 1.0 mm first — the proven test |
    | Filament | `Clay @ 1-20 ratio` | carries the auger's 50 mm³/s ceiling |

    **The filament profile is the ratio.** Whatever Plunger:Auger ratio is set on
    the touchscreen in Phase 4 must match the profile sliced with — a *higher*
    ratio on the machine stalls the auger, which is what killed the previous test
    print at layer 2.
15. **Point the upload at Moonraker** — the bundle already contains a physical
    printer `MANDEL`, host type OctoPrint, at `http://192.168.0.34`. Add a
    Moonraker API key, or add the workstation to `trusted_clients` in
    `moonraker.conf` and leave the key blank. Test with *Send to printer*.
16. **Run the validator — do not skip.** `python validate.py --nozzle 3 --ratio 20`
    must end with `ALL CHECKS PASSED`. It has already caught four defects that
    inspection missed. Repeat for whichever of `--nozzle 4 5 6` the customer owns.

## Phase 4 — acceptance print

No print on this machine has yet succeeded past layer 1. The speed cap exists to
fix exactly that, and this is its first real test.

17. **Slice and send the test cylinder** — Ø50 × 40 mm, or generate the reference
    part with `gcode/gen_cylinder.py`. Sanity-check the preview: at 1:20 the print
    runs at **9.72 mm/s**, because the screw passes only 50 mm³/s through a
    5.14 mm² bead. If it looks fast, the volumetric ceiling did not apply.
18. **Use the pause properly.** The print homes, parks at the bed centre with the
    bed at Z max, switches the touchscreen to the clay panel and pauses on
    purpose. There: set the ratio to **1:20**; hold the extrude button and prime
    until clay flows steadily (it should flow continuously while held, not one
    burst per press); check the panel's auger RPM looks right (~212 RPM at
    33 mm³/s); prime **last**, then RESUME promptly.
19. **Watch the opening sequence** — travel to (15, 15) at full height then
    descend (not into the middle of the part), a 60 mm purge line ≈309 mm³, a 5 mm
    lift, then one skirt loop. **Measure the purge line with calipers**: it should
    be close to 3 mm. Wider means over-extrusion — trim with `M221 S90` and record
    the value that looks right.
20. **Watch layer 2 specifically.** The layer height doubles from 1.0 to 2.0 mm,
    so flow demand jumps. This is exactly where the last attempt failed — the
    auger was asked for 643 RPM against a measured ceiling of 307 and simply
    stopped turning, with no error. Expected now: the cap holds the screw at 307
    RPM and slows the toolhead instead. **If flow falters, do not cancel** — drop
    to `M220 S60`, then `S40`. The value that recovers it *is* the measurement of
    the auger's real ceiling.
21. **Hand over** the four things they will use daily: the three profiles and that
    the filament profile is the ratio; the pause-and-prime handover; `M220` and
    `M221` live mid-print; and that a larger nozzle prints *thicker, not faster* —
    a 6 mm nozzle at 1:20 is 2.4 mm/s, so large nozzles need a lower ratio.

---

## Data sheet to bring back

These values cannot be recovered remotely. Fill every row — a confirmed number is
as useful as a corrected one.

| Measurement | Config says | Measured | Notes |
|---|---|---|---|
| X travel from endstop | 585 | | |
| Y travel from endstop | 200 / 585 | | the critical one |
| Z travel, nozzle to bed at home | 585 | | |
| Usable bed surface, X × Y | — | | may be less than travel |
| 100 mm move, actual — X | 100.0 | | scale check |
| 100 mm move, actual — Y | 100.0 | | scale check |
| Purge line width (calipers) | 3.0 | | extrusion trim |
| `M221` value that looked right | 100 | | |
| `M220` needed at layer 2, if any | 100 | | implies the real auger ceiling |
| Ratio used for the acceptance print | 1:20 | | |
| Nozzles the customer owns | 3/4/5/6 | | |
| Acceptance print reached layer | 20 | | previous best: 1 |

Also bring back: the three photographs; `~/printer_data/logs/klippy.log` after
the acceptance print; the corrected `printer.cfg` (or run `sync.py --pull` while
still on their network); and the contents of `printer.cfg.bak*` dated July, which
may show where the 585 came from.

## If it goes wrong

All of these have happened on this machine. Full list with causes:
[`../mandel_clay_printer.md`](../mandel_clay_printer.md) §11.

| Symptom | Most likely cause | First move |
|---|---|---|
| Homing crawls, a minute per axis | speed cap left armed by a cancelled print | `CLAY_PRINT_END`, or just `G28` — it now releases the cap itself |
| Auger stops turning partway up the part | flow demand above the screw's ceiling; ratio higher than sliced for | `M220 S60`, then re-slice with a matching filament profile |
| Clay moves one burst per press instead of flowing | the panel's hold-to-jog loop stopping during the pause | restart KlipperScreen; report it — this was fixed and should not recur |
| Barely any extrusion; 500% flow does not help | the ratio applied to the wrong axis | `CLAY_STATUS` must say `1 E mm = 1 mm3 out`. If not, stop and report |
| "Internal error in stepcompress", MCU shutdown | an acceleration no motor could be asked for | `FIRMWARE_RESTART`; capture `klippy.log` first |
| Values changing on the panel with nobody touching it | someone *is* touching it, or a synthetic-input tool is running | ask the room before debugging — this has cost hours |
