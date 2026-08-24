# Slicing for MANDEL

**PrusaSlicer.** `MANDEL_clay.ini` is a config bundle with four nozzles
(3/4/5/6 mm) and three working ratios. Import with **File → Import → Import
Config Bundle**, then pick a printer, a print profile and a filament.

Regenerate it with `python gen_prusaslicer_bundle.py` — edit the generator, not
the `.ini`.

---

## Why PrusaSlicer and not Cura

The decision is made by one unusual property of this machine: **E is volumetric.
One mm of commanded E is one mm³ of clay out of the nozzle, at any ratio.**
Everything else follows.

| | PrusaSlicer / OrcaSlicer | Cura |
|---|---|---|
| **A flow ceiling in mm³/s** | `filament_max_volumetric_speed` — a first-class setting. The auger's measured ceiling goes straight in, and the slicer slows every move to respect it | no equivalent; you would hand-compute a speed per nozzle and per ratio, and the time estimate would still be wrong |
| **Arithmetic in custom G-code** | `{extrusion_width * layer_height - ...}` — so `CLAY_PRINT_LIMITS BEAD=` computes itself | plain `{variable}` substitution only; the bead would have to be hard-coded in every profile and would silently go stale |
| **Per-layer hooks** | `layer_gcode` with `{if layer_num == 0}` — arms the speed cap *after* the descent from Z max | possible via post-processing script only |
| **Profiles as text** | plain `.ini`, diffable, generatable, version-controlled | profiles are managed in-app; less reproducible |

**OrcaSlicer is an equally good choice** — it inherits the same expression engine
and volumetric-speed setting from PrusaSlicer, and it speaks to Moonraker
natively rather than through the OctoPrint-compatible API. If you prefer its UI,
the same settings transfer; only the bundle format differs.

Cura is not *wrong* for clay — plenty of ceramic printers ship Cura profiles —
but on a machine whose bottleneck is a volumetric flow ceiling, it makes you do
by hand the one calculation the other two do for you.

---

## The two settings that are not preferences

### `filament_diameter = 1.128379`

This is not a real filament. It is the diameter whose cross-section is exactly
1 mm²:

```
area = pi/4 * d^2 = 1   ->   d = sqrt(4/pi) = 1.128379 mm
```

so **1 mm of "filament" is 1 mm³**, and every E value PrusaSlicer writes is
already in the machine's units. The slicer's own statistics stay correct too,
because it computes volume as length × area.

> Do **not** instead set Klipper's `filament_diameter` to 1.128379. Klipper
> rejects it (minimum 4.0), and it is unnecessary — nothing here uses Klipper's
> volumetric mode. The machine's `rotation_distance` already carries the mm³.

### `filament_max_volumetric_speed`

The auger's measured ceiling — **50 mm³/s at a 1:20 ratio, which is 307 RPM** —
expressed in the slicer's own units. PrusaSlicer slows the toolhead until the
flow fits, which is the same guarantee `CLAY_PRINT_LIMITS` gives on the machine,
applied early enough that the time estimate is honest.

Both are belt and braces: the slicer respects the ceiling, and the machine
enforces it again at print time from whatever ratio you actually set.

---

## The 3 mm profile is the cylinder test, parameter for parameter

`Clay 3mm nozzle` is the default preset and is not invented — it reproduces the
hand-written `gen_cylinder.py` test that this machine has actually run:

| | cylinder test | slicer profile |
|---|---|---|
| bead width | 3.0 mm | 3.0 mm |
| layer height | **2.0 mm** | **2.0 mm** |
| first layer height | **1.0 mm** | **1.0 mm** |
| bead cross-section | 5.142 mm² | 5.142 mm² |
| design flow | 100 mm³/s | 100 mm³/s |
| design XY speed | 19.45 mm/s | 19.45 mm/s |
| first layer speed | 15 mm/s | 15 mm/s |
| perimeters / bottom / top | 1 / 1 / 0 | 1 / 1 / 0 |
| infill | none | 0% |
| skirt | 1 ring | 1 loop |
| **effective XY at 1:20** | 9.73 mm/s | **9.72 mm/s** |

Two ceilings act, in order: the **design flow** (100 mm³/s, what the process
wants) and then the **auger ceiling** (what the screw can pass at the chosen
ratio). Whichever is lower wins. At 1:20 the screw binds; at 1:5 the design flow
binds, so the print does not run away just because the ratio is low.

The other nozzles keep the same ~2/3-of-nozzle layer ratio and the same design
flow, which is why they are slower: 100 mm³/s through a 20.57 mm² bead is
4.86 mm/s. **First layer speed is bounded by the design flow too** — a flat
15 mm/s is 42 mm³/s on the 3 mm bead but 167 mm³/s on the 6 mm one, so it drops
to 8.98 mm/s there.

---

## The ratio, not the nozzle, sets throughput

The screw turns `balance` revolutions per unit of clay, so the flow it can pass
scales as `1/ratio`. **A bigger nozzle does not print faster — it prints
thicker, proportionally slower.**

Flow ceiling: **1:5 → 200 mm³/s, 1:10 → 100, 1:20 → 50.**

| nozzle | layer | bead mm² | XY at 1:5 | at 1:10 | at 1:20 |
|---|---|---|---|---|---|
| 3 mm | 2.0 | 5.14 | 38.9 mm/s | 19.5 | 9.7 |
| 4 mm | 2.5 | 8.66 | 23.1 | 11.6 | 5.8 |
| 5 mm | 3.0 | 13.07 | 15.3 | 7.7 | 3.8 |
| 6 mm | 4.0 | 20.57 | 9.7 | 4.9 | 2.4 |

A 6 mm nozzle at 1:20 is 2.4 mm/s — unusably slow. **Large nozzles need a low
ratio.** That is what the three filament profiles are for.

> **Slice and print at the SAME ratio.** The filament profile you choose fixes
> the flow the g-code asks for; the ratio you dial in during the print-start
> pause fixes what the screw can deliver. Setting a *higher* ratio on the machine
> than you sliced for stalls the auger — that is exactly the failure that killed
> the first test print at layer 2. Lower is always safe: the machine's own cap
> just slows the toolhead.

---

## How a print runs

1. **`CLAY_PRINT_START X=100 Y=100`** — homes, parks at the bed centre with the
   bed at Z max, switches the touchscreen to the clay panel and **pauses**.
2. **You prime by hand and set the ratio.** This is the primary purge.
3. **RESUME** — `CLAY_RESYNC` re-syncs at that ratio.
4. Travel to **(15, 15) at Z max**, then descend there. Never at the park point:
   that is the middle of the part, and the nozzle would drag out through its own
   ooze.
5. **`CLAY_PRINT_LIMITS BEAD=<mm²>`** arms the speed cap.
6. **A 60 mm purge line** — 309 mm³ on the 3 mm nozzle — at exactly the auger's
   rate, because the cap is already armed and the purge is a *moving* move. Then
   a 5 mm lift so the travel to the part cannot drag through it.
7. The skirt establishes flow at the part's own radius.
8. **`CLAY_PRINT_END`** releases the cap, then a 30 mm lift clear of the wet part.

The orderings in 4–6 are all load-bearing — see §10 of the machine doc for what
each one prevents. In particular the cap must be armed *before* the purge (a
moving purge then runs at the right flow) but *after* the descent (a toolhead
velocity limit would throttle the 585 mm drop to about a minute).

---

## ⚠ The build volume in printer.cfg is wrong, and Y is unsafe

The bundle is generated at **200 × 200 × 300** — *not* the 250 × 250 the operator
states the machine is. The reason is not doubt about the measurement:
**with the current config, any Y above 200 is a crash however long the axis
really is**, because Y homes to its MAX endstop and Klipper calls that Y=200.
Raise these once `printer.cfg` is corrected.

The axis limits were verified as **original, not introduced by any of this
work**: byte-identical to the 10 Aug 2026 backup, and no change ever touched a
`position_*` or `homing_*` key.

| axis | endstop | `position_max` | homes toward | should be, for 250 |
|---|---|---|---|---|
| X | 0 | **585** | MIN | `position_max: 250` |
| Y | **200** | **585** | **MAX** | `position_endstop: 250`, `position_max: 250` |
| Z | 585 | 585 | MAX | **unresolved — see below** |

**Y is the dangerous one.** It homes in the *positive* direction, so the endstop
is at the top of travel — but `position_endstop: 200` tells Klipper that top is
Y=200. Two consequences:

1. **Every Y coordinate is offset by 50 mm.** If the axis is really 250 long, the
   machine believes it is at Y=200 while physically at Y=250. Gcode Y=0 is
   physically 50 mm in, and the bed's true centre is commanded as Y=75, not 125.
2. **Y above 200 is unreachable but not refused.** `position_max: 585` lets
   Klipper accept a move to Y=585 — 335 mm past a hard stop. Nothing has hit it
   only because every print so far has been a small object near the middle.

**X** is the same class of error without the offset: it homes to 0, so the
coordinate frame is right, but `position_max: 585` permits 335 mm of travel that
does not exist.

### Z cannot simply be wrong

`position_endstop: 585` and every print descends from there to Z≈1 — **584 mm of
real travel, which has worked repeatedly.** A 300 mm Z axis could not do that. So
either the Z travel genuinely is ~585 mm and 300 is the *usable* print height, or
Z=0 is not the bed. `max_print_height = 300` in the bundle is a soft slicing
limit and is safe either way, but the machine's own number needs settling.

### Where 585 probably came from

`position_max = 585` appears on **all three axes**, while the two
deliberate-looking numbers are Y's endstop at 200 (matching the July 2026
documentation's 200 × 200 × 200) and Z's endstop at 585. Since every print
descends from Z=585 to Z≈1 and works — 584 mm of real travel — **585 is almost
certainly Z's true travel, pasted into X and Y's `position_max`.**

### Until printer.cfg is corrected

Keep parts within **Y ≤ 200** — the area the current configuration can actually
reach. The correction is two lines for X and Y; ask, and it can be applied and
verified. Changing Y's endstop to 250 also shifts the coordinate frame by 50 mm,
so **older g-code centred on (100, 100) will land somewhere different afterwards**
and should be regenerated.

---

## Other defaults worth knowing

- **No retraction anywhere.** There is nothing to retract — pulling the plunger
  back only decompresses the barrel, and the clay takes a long time to come
  back. `retract_before_travel` is set past any travel this bed can contain.
- **No heaters, no fan.** All temperatures are 0 and cooling is off. The
  `[extruder1]` heater is vestigial (see the machine doc).
- **Single wall, solid bottom, no infill** — `perimeters = 1`,
  `bottom_solid_layers = 1`, `fill_density = 0%`. The usual clay case. Turn on
  **Spiral vase** for seamless walls.
- **Extrusion width = nozzle bore** on every width setting. Clay leaves the
  nozzle at its own diameter; it is not squashed wider the way plastic is.
- **Speeds are deliberately generous (30 mm/s).** The volumetric ceiling is the
  real limit and PrusaSlicer will slow every move to respect it — the same
  philosophy as the machine: the file asks, the ceiling decides.
- **Acceleration control is disabled** — every `*_acceleration` is `0`, which in
  PrusaSlicer means *do not emit*. This is not tidiness: PrusaSlicer would
  otherwise write an acceleration before every feature and **overwrite the
  `ACCEL` that `CLAY_PRINT_LIMITS` set to keep the auger inside its envelope**.
  Klipper's configured acceleration, as capped by the clay macros, is the only
  authority on this machine.
- **`machine_limits_usage = time_estimate_only`** — so no `M201`/`M203`/`M204`
  machine limits are written into the file either. They exist for the time
  preview only.
- `gcode_flavor = marlin`. Both flavours are valid — the shipped Voron profiles
  use `klipper` — but **the klipper flavour makes PrusaSlicer emit
  `SET_VELOCITY_LIMIT`, which is the exact command the clay speed cap uses.**
  `marlin` is also accepted by every PrusaSlicer version, and Klipper's own
  documentation recommends it.
- **`seam_position = aligned`.** Never random on clay — a wet wall shows every
  seam, and aligned makes it one vertical line instead of a spiral of blemishes.
- **`perimeter_generator = classic`, never Arachne.** Arachne varies extrusion
  width to fit thin features, which is precisely what a fixed-bore clay nozzle
  cannot do — a varying width means a varying bead and therefore a flow the screw
  was never asked about.
- **`arc_fitting = disabled`** and **`gcode_label_objects = disabled`.** The
  machine has neither `[gcode_arcs]` nor `[exclude_object]`, so `G2`/`G3` or
  `EXCLUDE_OBJECT_*` would abort the print on an unknown command. Both are
  already the defaults; they are pinned so that turning one on later is a
  deliberate act with this note attached.
- **`Clay <n>mm nozzle - VASE` profiles** turn on spiral vase. For a single
  continuous wall — the usual clay part — it is strictly better: no seam, no
  layer-change stop, and no moment where the screw must stop and restart against
  barrel pressure. It cannot print a lid, a hole, or a second wall.
- **`[physical_printer:MANDEL]`** is included, so uploading works after import.
  Moonraker speaks the OctoPrint upload API, hence `host_type = octoprint` at
  `http://192.168.0.34`. **The API key is blank** — fill it in PrusaSlicer, or add
  this workstation to Moonraker's `trusted_clients` and leave it empty.

## Validated by actually slicing — `validate.py`

PrusaSlicer **2.9.6** is installed on the workstation, and the bundle is checked
by running it rather than by reading it:

```
python validate.py [--nozzle 3|4|5|6] [--ratio 5|10|20] [--vase]
```

It merges the chosen print + filament + printer sections into a flat config
(resolving `inherits`), generates a Ø50 × 40 mm cylinder STL, slices it with the
real `prusa-slicer-console.exe`, and audits the G-code:

- the four clay macros are present, with a **numeric** `BEAD=`
- **no** `M204`, `SET_VELOCITY_LIMIT`, `M201`, `M203`, `M200`, temperature, fan,
  or negative-E retraction — any of which would fight the machine
- E is in **mm³**: the measured mm³ per mm of travel must match the profile's
  computed bead
- **peak flow must not exceed the auger ceiling**, measured from the G-code's own
  E, distances and feedrates

All eight combinations (4 nozzles × flat/vase) pass, with peak flow at exactly
**100% of the 50 mm³/s ceiling** — PrusaSlicer clamps the profile's 30 mm/s
request down to `F583.477` = 9.72 mm/s = 50.00 mm³/s. That is the volumetric
limit doing its job.

### Two real bugs this caught

Both would have wasted an afternoon at the machine, and neither was visible by
inspection:

1. **PrusaSlicer refused to slice at all.** With `use_relative_e_distances = 1`
   it requires `G92 E0` in `layer_gcode`: *"Relative extruder addressing requires
   resetting the extruder position at each layer to prevent loss of floating
   point accuracy."* Genuinely needed here too — E is mm³, so it accumulates
   into the tens of thousands and float precision would start to bite.
2. **`layer_gcode` is not emitted for the first layer.** The first `G92 E0` lands
   at the *second* layer change, so a `{if layer_num == 0}` hook there **never
   fires** — `CLAY_PRINT_LIMITS` was silently absent from every sliced file.
   Anything that must happen once at the start belongs in `start_gcode`, which is
   where the cap is armed now, after an explicit fast `G1 Z{first_layer_height}`.

## Which PrusaSlicer fork

**Upstream PrusaSlicer.** The forks were compared specifically on extrusion:

| | verdict |
|---|---|
| **PrusaSlicer 2.9.6** | **chosen.** Has the Pressure Equalizer (2.5+), `filament_max_volumetric_speed`, arithmetic in custom G-code, and `.ini` profiles that live in this repo and are diffable |
| **SuperSlicer** | its extrusion edge was the flow-slope limiter — **that is now upstream** as the Pressure Equalizer. Update cadence has slowed and Orca has overtaken it. No remaining reason |
| **OrcaSlicer 2.4.2** | the real alternative: native Klipper/Moonraker, and calibration wizards for pressure advance, flow rate and max volumetric speed. Two costs — JSON profiles that cannot be hand-authored and version-controlled as cleanly, and **its Klipper flavour emits `SET_VELOCITY_LIMIT`, the exact command the clay cap uses** |
| **Bambu Studio / vendor forks** | vendor-locked, no benefit here |

### The Pressure Equalizer, and why it is left off

`max_volumetric_extrusion_rate_slope_positive` / `_negative` (Print Settings →
Speed, mm³/s²) limit how fast flow may *change* — which sounds ideal for a screw
pushing compressible clay through a long barrel.

It is deliberately **not enabled**, because the arithmetic says it would dominate
rather than help. Prusa recommends 2–10 for filament at ~10–20 mm³/s. This
machine's motion-side acceleration cap already limits flow acceleration to
`500 mm/s² × 5.14 mm² = 2571 mm³/s²`; a setting of 10 would be **250× more
restrictive** and would slow every transition to a crawl.

If bulging at the first-layer-to-main transition (a 2.79 → 5.14 mm² step) turns
out to be a real problem, start around **300–500 mm³/s²** and come down. Treat it
as one change, measured on a part.

## First slice — check these

1. E values are **mm³**, so they are large. A 3 mm nozzle at 2 mm layer is about
   **5.14 mm³ per mm of travel** — a 1.3 mm segment is `E6.7`, not `E0.05`.
2. The g-code contains `CLAY_PRINT_START`, one `CLAY_PRINT_LIMITS BEAD=5.142…`
   at the first layer, and `CLAY_PRINT_END` at the end.
3. PrusaSlicer's estimated time should be much longer than for plastic — if it
   is not, the volumetric ceiling is not being applied.
4. **No `M204` or `SET_VELOCITY_LIMIT` anywhere in the file.** If either appears,
   an acceleration got re-enabled and it will fight the clay speed cap.
5. **No `M201`/`M203`.** If they appear, `machine_limits_usage` did not take.
