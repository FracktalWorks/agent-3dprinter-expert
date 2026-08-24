# MANDEL — IISc clay printer

CoreXY clay extruder at **192.168.0.34**. Not a Dragon and not a filament
printer: a **plunger feeding an auger**, no heaters, KlipperScreen on a 3.5"
SPI panel. Everything here was measured on the machine unless marked otherwise.

General Klipper behaviours found here are in
[`../klipper_motion_gotchas.md`](../klipper_motion_gotchas.md) — read that first
when debugging motion or extrusion.

## Picking this up cold

1. **`mandel/` beside this file holds the machine's live files** — 59 KB of clay
   macros and a 32 KB touchscreen panel that exist in no other git repo. Read
   them there rather than over SSH. `mandel/klipperscreen/` additionally holds
   the four upstream KlipperScreen files patched in place on this machine —
   **a KlipperScreen update destroys those**, so re-apply the patch after one.
2. **`python mandel/sync.py --check` before editing anything.** The printer is
   the source of truth; the snapshot goes stale the moment someone touches a
   knob. Pushing a stale file silently reverts their work.
3. **Read §11 (What has already gone wrong) before proposing a fix.** Most of
   the plausible-sounding changes on this machine have already been tried, and
   several of them were wrong in ways that took hours to find.
4. Then §2 (the volumetric model) and §5 (ceilings). Everything else hangs off
   those two.
5. **Slicing is §10.** PrusaSlicer, and `validate.py` must be run after any
   profile change — it slices a real object and asserts on the G-code.
6. **Going to the machine in person?** `mandel/COMMISSIONING.md` is the field
   procedure — measuring the true build volume, correcting the axis limits, and
   commissioning the slicer.

Current state, 2026-08-24: 16 microsteps both motors, auger ceiling **307 RPM**
(measured), print-speed cap armed by the g-code and tracking the live ratio,
ratio-scaling bug fixed in both the panel and `CLAY_AUGER_SPIN`, Z offset +0.5 mm.
`cylinder_d50_clay.gcode` is uploaded. PrusaSlicer is configured and validated
(§10). **No print has yet succeeded past layer 1** — the last attempt stalled the
auger at layer 2, which the speed cap now exists to prevent.

---

## 1. The machine

| | |
|---|---|
| Kinematics | corexy, 585 mm axes, `max_velocity: 100`, `max_accel: 500` |
| Host | Raspberry Pi, Klipper + Moonraker + KlipperScreen v0.4.7-149 |
| MCU | STM32G0B1 |
| Auger | `[extruder]` — NEMA 17 (LDO), direct coupled, TMC5160, **16 microsteps** |
| Plunger | `[extruder1]` — **10:1 gearbox** onto a 4 mm lead screw, TMC5160, **16 microsteps** |
| Barrel | **64 mm bore** = 3216.99 mm² = 3.217 mL per mm of plunger travel |
| Screw | OD 14, core 7, pitch 5.5, flight 3.2 mm axial |
| Display | 480×320 SPI panel, but X renders **800×480** and `fbcp` scales it |

`[extruder1]` still carries a vestigial `heater_pin: PA7` and a disconnected
`Generic 3950` sensor reading ≈ −109 °C. Harmless; `min_extrude_temp: -110`.

### Measured drivetrain figures

| Quantity | Value | How it was measured |
|---|---|---|
| `plunger_base_rd` | **0.400 mm/rev** | 250 commanded rev → 100 mm of travel |
| Plunger resolution | 8000 microsteps/mm | 200 × 16 ÷ 0.4 |
| Plunger motor ceiling | **800 RPM** | stalls near 1000, derated 80% |
| Auger steps/rev | **200** (full step) | 10 commanded rev = 10 physical rev, verified at 16µ |
| Auger geometric volume | **265.54 mm³/rev** | `π/4 (14²−7²) × (5.5−3.2)` |
| `auger_eff` | **0.7366** | back-calculated, see §3 |
| Auger delivery | **195.60 mm³/rev** | eff × geometric |
| `auger_motor_max_rpm` | 1500 | **UNMEASURED placeholder** |

The old `rotation_distance: 2.642` on the plunger was a fabrication, wrong by
6.6×; the old auger `8.0` was arbitrary — a screw has no filament, so that
number meant nothing at all.

---

## 2. The volumetric model — how E works here

**One mm of commanded E is one mm³ of clay out of the nozzle, at any ratio.**
Volume is the only unit a screw and a piston share, so it is the only unit in
which a rate or a ratio between them means anything.

```
[extruder1] (plunger) rd = barrel_area × plunger_base_rd = 1286.796   ← constant
[extruder]  (auger)   rd = auger_vol_rev / balance                    ← ratio lives here
```

**The plunger carries E; the balance lives on the auger.** This is the single
most important line in this document. The plunger's rotation distance never
moves, so E always means real delivered volume; the balance changes only how far
the *screw* turns to deliver it.

> **Getting this backwards costs exactly the balance factor.** It was originally
> implemented with the balance on the plunger, which starved it: at 1:16.5 a
> commanded 5.14 mm³ delivered **0.31 mm³**, so the first real print came out at
> 6% of its intended bead and no slicer flow percentage could reach it — 1650%
> would have been needed. Symptom to recognise: *"I need 500% flow and it still
> barely extrudes."*

Verified 1:1 through 1:50 — 1.0000 mm³ per E mm throughout, only auger RPM moving.

### Derived rates

```
auger_rpm   = flow × balance × 60 / auger_vol_rev
plunger_rpm = flow × 60 / (barrel_area × plunger_base_rd)
```

At flow 100 mm³/s: plunger 4.7 RPM (0.031 mm/s), auger 31 × balance RPM.

---

## 3. `auger_eff`, and why it cannot be weighed

`auger_eff` = delivered ÷ geometric = **0.7366**. It is back-calculated from the
ratio this machine printed with for months (0.0076 mm of plunger per mm of old
auger E), which under the corrected plunger calibration works out to 195.6 mm³
per auger revolution. 74% is squarely where a thick-flight clay screw belongs —
the flight is 3.2 mm of a 5.5 mm pitch, so 58% of the screw is metal.

**It cannot be measured by weighing what comes out.** Plunger → auger → nozzle is
a sealed positive-displacement chain, so in steady state the output equals the
plunger supply *regardless of what the auger does*. A scale only ever measures
the piston.

**The balance trim IS the measurement.** Tune `balance` until pressure holds
steady — no ooze at pauses (over-supplied), no thinning or stuttering (starved) —
then `CLAY_AUGER_ZERO` folds that trim into `auger_eff` and resets the ratio to
1:1. If a very high ratio turns out to be correct, that is evidence `auger_eff`
is badly wrong: needing 1:20 implies the screw delivers ~3.7% of geometric.

---

## 4. Modes

| | EXTRUDE | LOAD |
|---|---|---|
| Purpose | printing, flow-metered | filling the barrel, clearing a blocked nozzle |
| E unit | mm³ of clay | **mm of plunger travel** |
| Plunger | carries E, rd 1286.796 | `load_rpm`, ceiling **`load_max_rpm` 500** |
| Auger | `auger_vol_rev / balance` | **`auger_motor_max_rpm`, flat out** |
| Accel | `jog_accel` 20000 mm³/s² | `load_accel` 100 mm/s² |

**Both motors run 16 microsteps.** Auger 0.058 mm³ per step; plunger 0.402 mm³
per step = 0.08 mm of a 5.14 mm² bead.

> **Do not drop these for step-rate headroom.** Both were taken to
> `microsteps: 1` on 2026-08-11 and reverted the same day: the operator
> immediately noticed the machine could not move as fast as before. The
> "interpolation makes it free" argument is wrong about speed — see gotchas §12.
> The step rates that motivated it (80,000/s at 1500 auger RPM) were computed
> from a placeholder the screw has never reached; it stalls at 270–640 RPM,
> i.e. 14,000–34,000 steps/s, so there was no step-rate problem to solve.

**LOAD drives the plunger ALONE; the auger is parked.** Gearing the auger to the
plunger on one E axis was tried twice and abandoned both times — see the note in
`_CLAY_LOAD_APPLY`. If the auger is wanted for unblocking, drive it from EXTRUDE
mode or give it a macro of its own rather than tying it to the plunger's speed.

Both are synced states. Load mode's ratio is simply "both as fast as they are
allowed", which falls out of wanting both at once:

```
plunger rd = plunger_base_rd
auger   rd = load_rpm × plunger_base_rd / auger_motor_max_rpm
```

At 500 plunger RPM against a 1500 RPM auger that is 0.1333 — three auger turns
per plunger turn. **`_CLAY_LOAD_APPLY` must be re-run whenever `load_rpm`
changes**, or the auger drifts off its ceiling.

**Acceleration in load mode must be bounded by the AUGER, not the plunger.**
`load_accel` is a plunger figure, but the auger sees `load_accel / auger_rd`
rev/s², and `auger_rd` shrinks with `load_rpm` — so lowering the load speed
explodes the auger's angular acceleration and Klipper dies with `Internal error
in stepcompress`. `_CLAY_LOAD_APPLY` takes
`min(load_accel, auger_max_accel × auger_rd)` and publishes it as
`load_accel_eff`, which both jog brackets and the panel's queue model use.
`auger_max_accel` is **300 rev/s² = 960k steps/s²**, held constant at every load
speed. See gotchas §2b — this took the machine down once.

The plunger's 500 RPM cap is hard: the jog's ramp compensation deliberately
commands a peak above the setpoint, so `CLAY_JOG_BEGIN` pins `VELOCITY` to
`load_max_rpm` and the panel clamps its computed peak to the same figure.

LOAD is idle-or-paused only. Any resync — `CLAY_RESYNC`, `EXTRUDERS_SYNC` at the
top of a print file, the `RESUME` override, leaving the clay panel — returns to
EXTRUDE and restores the config velocity/accel/cruise-ratio, so the unsynced
state is never left lying around for a print to trip over.

---

## 5. Ceilings

One process ceiling, `max_flow`, measured at the plunger. `_CLAY_RECALC` folds it
with both motor limits into `flow_cap`, all three expressed as mm³/s out of the
nozzle so they can be compared at all:

```
max_flow                                              the process limit
plunger_max_rpm / 60 × barrel_area × plunger_base_rd  the plunger motor
auger_motor_max_rpm / 60 × auger_vol_rev / balance    the auger motor
```

The auger term carries the balance, so **raising the ratio lowers the flow
ceiling** and the panel's `max` readout drops accordingly. Real, not a fault.

Per-motor *process* caps do not exist on purpose — setting them independently
means guessing twice and letting the smaller guess bind for no physical reason.

### The auger's ceiling — MEASURED 2026-08-11

**50 mm³/s at a 1:20 ratio = 307 RPM.** Measured by the operator at 16
microsteps, after full stepping was reverted. `auger_motor_max_rpm` = **307**.

> No derate. One was applied unasked (245, by analogy with the plunger's
> 1000 → 800) and the operator rejected it: the measured figure is the limit
> they want honoured. **Do not quietly add safety margin to a number someone
> measured** — if margin is wanted, it is theirs to ask for. Margin invented on
> the agent's side is indistinguishable from a wrong measurement.

Store the ceiling in **RPM, not mm³/s**: RPM is the motor's property and is
ratio-independent, while the flow it permits scales as `1/balance`.

```
flow ceiling (mm3/s) = auger_motor_max_rpm / 60 x auger_vol_rev / balance
    at 1:10    -> 82 mm3/s        at 1:20.95 -> 38 mm3/s
    at 1:25    -> 32 mm3/s        at 1:30    -> 27 mm3/s
```

`CLAY_SET_AUGER_MAX_RPM RPM=<n>` sets it, persists it to `clay_vars.cfg` and
re-derives `flow_cap`. Its confirmation message reports a **stale** `flow_cap`,
because Klipper renders a macro's whole template before executing any of it, so
the `{% set c = ... %}` sees pre-`_CLAY_RECALC` state — run `CLAY_STATUS` for
the real figure.

#### The failure this explains

| Stage | bead | XY | flow | auger | result |
|---|---|---|---|---|---|
| skirt + layer 1 | 2.79 mm² | 15 mm/s | 42 mm³/s | 269 RPM | printed |
| layer 2 onward | 5.14 mm² | 19.4 mm/s | 100 mm³/s | 643 RPM | **never turned** |

The layer height doubles at layer 2, so the demand jumps 2.4× at a single
`G1 Z`. 643 RPM is more than twice the measured ceiling — it was never going to
turn. (That print also ran at `microsteps: 1`, which independently cost top
speed, so 269-printed/643-stalled was never a clean bracket. The 307 RPM figure
supersedes it.)

### The print-speed cap — the machine's guarantee, not the file's

**Nothing in Klipper bounds an extruder during a printing move** (gotchas §2c).
Since the ratio is chosen on the touchscreen *after* the file has started, no
feedrate baked into g-code can be correct. So the file declares its bead and the
machine derives its own ceiling from the live ratio:

```
CLAY_PRINT_LIMITS BEAD=<mm2>     arms it   (after G28 — it slows every move)
CLAY_PRINT_END                   releases it
_CLAY_TOOLHEAD_LIMITS            XY cap = auger_motor_max_rpm/60 × auger_rd / bead
                                 XY accel cap = auger_max_accel × auger_rd / bead
```

`_CLAY_APPLY` calls it, so **RESUME re-derives the cap at whatever ratio was set
during the pause**. `CLAY_JOG_END` restores the cap rather than the configured
limits, or priming by hand would hand the resumed print back the acceleration
that stalls the screw. `CLAY_PRINT_START` and the 60 s idle timeout both clear
`print_bead`, so a cancelled print cannot leave the machine crawling.

Measured on the machine at the 5.142 mm² bead, ceiling 307 RPM:

| ratio | XY cap | flow | auger |
|---|---|---|---|
| 1:5 | 38.93 mm/s | 200 mm³/s | 307 (file asks only 19.45 — file-limited) |
| 1:10 | 19.46 | 100 | 307 |
| 1:20 | 9.73 | **50.0** | 307 |
| 1:30 | 6.49 | 33.4 | 307 |
| 1:40 | 4.87 | 25.0 | 307 |

Exactly 307 RPM at every ratio, and 50.0 mm³/s at 1:20 reproduces the
measurement. **Lower the ratio to go faster** — that is now the only speed knob
that matters, and it needs no regenerated file.

### The auger RPM readout was 21× low until 2026-08-11

Two places still divided by `auger_vol_rev` after the balance moved onto the
auger, where the screw's rotation distance became `auger_vol_rev / balance`:

- **`clay.py auger_rpm()`** — displayed 10 RPM while the screw turned at 212.
  Operator-visible and the reason the bug was caught: *"it seems like the auger
  is rotating at a much higher RPM than is being displayed."*
- **`CLAY_AUGER_SPIN`** — `G1 E{revs × auger_vol_rev} F{rpm × auger_vol_rev}`
  turned the screw **`balance` times too far at `balance` times the stated
  speed**. `REVS=20 RPM=400` at 1:20.95 meant 419 revolutions at 8380 RPM. Both
  now derive from `ard = auger_vol_rev / balance`; verified at 5.00 turns for
  `REVS=5`. It also gained `FORCE=1` (to test above the believed ceiling) and an
  acceleration bounded in rev/s² — it previously inherited `jog_accel`, which is
  2141 rev/s² at this rotation distance, so the screw stalled on the ramp and
  the ceiling test measured the ramp.

`CLAY_STATUS` and `CLAY_FLOW_CALC` were correct throughout — they were updated
when the balance moved. **When the balance moves again, grep every use of
`auger_vol_rev`**: the correct denominator for anything about the screw's
rotation is `auger_vol_rev / balance`.

---

## 6. Files

| Path | What |
|---|---|
| `~/printer_data/config/printer.cfg` | **CRLF line endings — preserve them.** Only `[include clay_macros.cfg]` |
| `~/printer_data/config/clay_macros.cfg` | all clay macros, `[idle_timeout]`, `[save_variables]` |
| `~/printer_data/config/clay_vars.cfg` | persisted settings |
| `~/KlipperScreen/panels/clay.py` | the touchscreen panel — **lives only on the Pi**, not in any git repo |
| `~/printer_data/gcodes/` | print files |
| `mandel/slicer/` | PrusaSlicer bundle + `validate.py` (workstation only) — see §10 |
| backups | `printer.cfg.pre-clay-panel`, `.pre-auger`, `.bak-auger` |

**Older gcode in `~/printer_data/gcodes/` predates volumetric E** — those files
are hand-written (E ≈ XY path length, a feel-tuned fudge), not slicer output, and
their E values are **24.45× too small** now. Only `cylinder_d30_h50_clay.gcode`
calls `EXTRUDERS_SYNC`. The error direction is safe (under-extrusion). Do not
copy their E values.

---

## 7. Macro reference

| Macro | Purpose |
|---|---|
| `CLAY` | state variables; running it prints `CLAY_STATUS` |
| `CLAY_PRINT_LIMITS BEAD=` | arm the print-speed cap from the file's bead cross-section |
| `CLAY_PRINT_END` | release the cap |
| `CLAY_STATUS` | flow, ratio, both motor RPMs, rotation distances, sync state |
| `CLAY_PRINT_START X= Y=` | home → park centre at Z max → show clay panel → PAUSE |
| `CLAY_SET_FLOW FLOW=` | working flow, mm³/s |
| `CLAY_SET_BALANCE BALANCE=` / `CLAY_BALANCE_UP` / `_DOWN` | the ratio |
| `CLAY_SET_LIMITS MAX_FLOW=` | the one process ceiling |
| `CLAY_MODE MODE=LOAD\|EXTRUDE` | mode switch |
| `CLAY_SET_LOAD_RPM RPM=` | load-mode plunger speed |
| `CLAY_JOG D= F=` + `CLAY_JOG_BEGIN` / `_END` | press-and-hold jog chunks |
| `CLAY_RESYNC` / `EXTRUDERS_SYNC` | re-assert sync (the latter is a legacy alias) |
| `CLAY_AUGER_ZERO` | adopt the current ratio as the new 1:1 |
| `CLAY_AUGER_SPIN REVS= RPM=` | auger under load — find its stall speed |
| `CLAY_AUGER_TURN REVS= RPM=` | mechanical check: does a commanded rev turn the screw once |
| `CLAY_CAL_MOVE REVS= RPM= ACCEL=` + `CLAY_CAL_APPLY REVS= DIST=` | plunger drivetrain calibration |
| `CLAY_SET_AUGER_GEOM` / `_EFF` / `CLAY_SET_BARREL` | geometry |
| `CLAY_FLOW_CALC WIDTH= HEIGHT= SPEED=` | what a bead demands of both motors |

Deleted deliberately: `EXTRUDER_AUGER_ONLY`, `EXTRUDER_PLUNGER_ONLY`,
`PLUNGER_MOVE`, `SET_PLUNGER_RATIO`, `PLUNGER_TRACK`, `ZERO_PLUNGER`,
`QUERY_PLUNGER`. The plunger is permanently synced; only the ratio is adjustable.

---

## 8. The panel

Two controls — **Flow (mm³/s)** and **Plunger : Auger** — plus press-and-hold
jog pads and a mode toggle. RPM appears only as a derived readout, because it is
each motor's private business.

Flow and balance are genuinely orthogonal: flow is what you want out, balance is
how hard the screw works to deliver it, and changing the ratio leaves the flow
where you set it.

**Jog pacing.** Klipper cannot flush its queue and never junctions E-only moves
(gotchas §2–3), so the panel models the queue locally — each chunk costs
`material/peak + peak/accel` — and declines to send past `LEAD_S`. `chunk_peak()`
raises the commanded peak so a chunk still averages the requested flow despite
its ramp. Constants: `TICK_MS 40, CHUNK_S 0.12, LEAD_S 0.13`.

> **Do not shorten `CHUNK_S`.** Tried and measured: 0.12 → 0.08 took run-on from
> 0.34 s back to 1.1 s. Each chunk carries a fixed cost the model cannot see.

**Measured stop latency: >6 s before, 0.34 s after**, and now independent of how
long the button is held (0.336 s at a 2 s press, 0.361 s at 5 s). That stability
matters more than the number — the old queue grew for the entire hold.

Panel controls are enabled while **paused**, not only when idle, because the
print-start handover pauses on purpose.

Touch targets are sized as a fraction of screen height, never in pixels — `fbcp`
mirrors the 800×480 framebuffer onto the 480×320 panel at 0.6×, so a rendered
pixel is ~0.09 mm and any pixel-based sizing is wrong by 1.67×.

---

## 9. Print flow

```gcode
G21
G90
M83                          ; relative E, in mm3
CLAY_PRINT_START X=100 Y=100 ; home, park centre, clay panel, PAUSE
                             ; operator primes by hand, picks the ratio, RESUMEs
G28
CLAY_RESYNC
; skirt, then layers
```

`CLAY_PRINT_START` pauses last in the macro — nothing after `PAUSE` would run
until RESUME. Whatever ratio the operator settles on during that pause is the
ratio the print uses: `RESUME` re-applies the live balance and the file never
sets one.

Bed centre is **(100, 100)** — proven by the working test files, not the axis
midpoint. Z homes to **585 = maximum gap**; Z is the nozzle-to-bed distance, so
the first layer is a small Z and layers count upward.

`gen_cylinder.py` (in the session scratchpad) generates single-wall cylinders
with a skirt; bead area uses the slicer convention
`w·h − h²(1 − π/4)`, and flow pins XY speed since `flow = speed × bead area`.

---

## 10. Slicing

**PrusaSlicer 2.9.6.** The bundle, the reasoning for it over Cura and over the
other PrusaSlicer forks, and a validation harness live in
[`mandel/slicer/`](mandel/slicer/README.md). The generalisable findings are in
[gotchas §16](../klipper_motion_gotchas.md).

Three settings make a slicer fit this machine, and none of them is a preference:

| setting | why |
|---|---|
| `filament_diameter = 1.128379` | cross-section exactly 1 mm², so **1 mm of "filament" is 1 mm³** and the slicer's E is already in the machine's units |
| `filament_max_volumetric_speed` | the **auger's** ceiling in the slicer's own units — 50 mm³/s at 1:20, 100 at 1:10, 200 at 1:5. PrusaSlicer slows every move to fit, so the time estimate is honest too |
| every `*_acceleration = 0` | PrusaSlicer would otherwise write an acceleration before every feature and **overwrite the `ACCEL` that `CLAY_PRINT_LIMITS` set** to keep the screw inside its envelope |

Also pinned, because the machine lacks the sections they would need:
`perimeter_generator = classic` (Arachne varies bead width; a fixed bore cannot),
`arc_fitting = disabled` (no `[gcode_arcs]`), `gcode_label_objects = disabled`
(no `[exclude_object]`), and `gcode_flavor = marlin` — the `klipper` flavour
emits `SET_VELOCITY_LIMIT`, which is the very command the clay cap uses.

### The 3 mm profile is the cylinder test

`Clay 3mm nozzle` is the default preset and reproduces `gen_cylinder.py`
parameter for parameter: **2.0 mm layers, 1.0 mm first layer**, 3.0 mm bead,
5.142 mm² cross-section, 100 mm³/s design flow, 19.45 mm/s design speed, 15 mm/s
first layer, 1 perimeter, solid bottom, no top, no infill, one skirt loop. The
effective speed at 1:20 is 9.72 mm/s against the test file's 9.73.

Two ceilings act in series: the **design flow** (100 mm³/s, what the process
wants) and then the **auger ceiling** (what the screw passes at the live ratio).
Whichever is lower wins — so at 1:20 the screw binds, and at 1:5 the design flow
binds and the print does not run away just because the ratio is low.

The other nozzles keep the same ~2/3-of-nozzle layer ratio and the same design
flow, which is why they are slower: 100 mm³/s through a 20.57 mm² bead is
4.86 mm/s. First-layer speed is bounded by the design flow as well — a flat
15 mm/s is 42 mm³/s on the 3 mm bead but 167 mm³/s on the 6 mm one.

### How a print is wired together

```
start_gcode : CLAY_PRINT_START X=100 Y=100  -> home, park, clay panel, PAUSE
              --- operator primes by hand, sets the ratio, RESUME ---
              CLAY_RESYNC
              G1 X15 Y15 F6000              <- travel to the purge spot at Z MAX
              G1 Z{first_layer_height} F6000 <- descend THERE, fast, uncapped
              CLAY_PRINT_LIMITS BEAD={...}   <- arm the cap
              G1 X75 E{bead*60} F1800        <- 60 mm purge line, cap sets the rate
              G1 Z{first_layer_height+5} F1200 <- lift, so the travel cannot drag
layer_gcode : G92 E0                         <- mandatory with relative E
end_gcode   : M400 / CLAY_PRINT_END / G1 Z{max_layer_z + 30} F600
```

Four orderings in that block are load-bearing, and three of them were wrong at
some point:

- **Travel to the purge spot *before* descending.** PrusaSlicer otherwise
  descends at the park position — the middle of the part footprint — leaves
  whatever oozed during the pause right there, and then drags the nozzle out
  through it at layer height.
- **Descend before arming the cap.** The cap is a toolhead velocity limit, so a
  585 mm drop from Z max under it takes about a minute.
- **Arm the cap before the purge.** The purge is a *moving* line, so the cap
  gives it exactly the auger's flow rate. An extrude-only purge would instead be
  held to mm³/s = mm/s and crawl (gotchas §1).
- **Lift after purging**, or the travel to the part drags through the purge bead.

`CLAY_PRINT_LIMITS` **cannot** live in `layer_gcode` behind
`{if layer_num == 0}`: that hook is never emitted for the first layer, so it
fires never, silently (gotchas §16).

### Purging

There are three purges, in order of authority:

1. **The operator, by hand, during the print-start pause.** This is the real one
   and the reason the handover exists — you can see clay coming out before
   anything is committed.
2. **The 60 mm purge line** at (15, 15), laid before the part. 309 mm³ on the
   3 mm nozzle, 1234 mm³ on the 6 mm. Its length is the constant, so the line
   looks the same for every nozzle and the volume scales with the bead. It runs
   at exactly the auger's rate, which makes it a flow check you can look at.
3. **The skirt**, one loop, which establishes flow at the part's own radius.

### Always validate by slicing

```bash
python mandel/slicer/validate.py [--nozzle 3|4|5|6] [--ratio 5|10|20] [--vase]
```

It merges the profiles into a flat config, slices a real cylinder with the
PrusaSlicer CLI, and asserts on the G-code: macros present with **numeric**
arguments, no `M204` / `SET_VELOCITY_LIMIT` / `M201` / `M203` / `M200` /
temperature / fan / retraction, E in mm³ matching the computed bead, and peak
flow inside the ceiling.

**It has already caught three defects that inspection missed** — see §11. Sweep
the whole matrix, not one combination: the over-flow first layer only appeared at
the loosest ratio, because the tighter ceilings were hiding it.

Open: the bed is 200 × 200 × 300 until the Y endstop question in §12 is settled.
Everything else is measured, or reproduced from the test that has actually run.

---

## 11. What has already gone wrong

Every one of these looked correct when it was deployed. Read before proposing a
fix that resembles any of them.

| What | Symptom it produced | The actual cause |
|---|---|---|
| Balance applied to the **plunger's** rotation distance | "I need 500% flow and it still barely extrudes" — a 5.14 mm³ bead delivered 0.31 mm³ | E must be plunger-referenced; the ratio belongs on the auger (§2) |
| Panel `auger_rpm()` and `CLAY_AUGER_SPIN` left dividing by `auger_vol_rev` after that move | screen read 10 RPM while the screw turned 212; `SPIN REVS=20 RPM=400` meant 419 rev at 8380 RPM | the same ratio move, in two places nobody re-checked (§5) |
| `microsteps: 1` on both motors "for step-rate headroom" | operator: "I cannot move as fast as I was moving earlier" | interpolation smooths current, not commanded step timing — full stepping costs top speed (gotchas §12) |
| Auger geared to the plunger in LOAD mode | "Internal error in stepcompress", MCU shutdown, both motors dead | `auger_rd` scaled with `load_rpm`, so angular accel went as 1/rd — 21.8 M steps/s² (gotchas §2b) |
| Clearing `print_bead` without re-applying `SET_VELOCITY_LIMIT` | "homing is too slow" — G28 crawling a 585 mm axis at 9 mm/s | the variable is only an input; the limit persists until something sets it |
| `process_update` gating the jog on `state != "ready"` | clay only moved one burst per press while paused | the print-start handover pauses **on purpose**; "paused" is a working state here |
| Shortening the jog chunk to cut run-on | run-on went from 0.34 s to 1.1 s | more, shorter chunks deepen the queue (gotchas §3) |
| Five changes deployed in one batch | machine worse overall, whole batch reverted | one change at a time, with a print in between |
| Derating a measured ceiling 20% unasked | operator: "why did you mention 38, I told you 50" | do not add safety margin to someone else's measurement |
| `CLAY_PRINT_LIMITS` in the slicer's `layer_gcode` behind `{if layer_num == 0}` | the command was absent from every sliced file, silently | `layer_gcode` is not emitted for the first layer at all (gotchas §16) |
| Relative E without `G92 E0` in `layer_gcode` | PrusaSlicer produced no output whatsoever | it refuses to slice, not warn |
| A flat 15 mm/s first layer across all nozzles | 167 mm³/s on the 6 mm bead, 1.7× the design flow | only visible at the loosest ratio — the tighter flow ceilings were masking it |
| Driving the touchscreen with synthetic taps while the operator was at it | values drifting, modes refusing to stay set — looked exactly like bugs | it was their hand on the screen (gotchas §10c) |

**The pattern worth internalising:** on this machine the arithmetic is usually
right and the *plumbing* is wrong — a value updated in one place and not its
three derived readouts, a limit cleared as a variable but not as a command, a
guard that lists `ready` but not `paused`. When something is off by exactly a
ratio, or exactly one state, grep for every use of the thing that moved.

---

## 12. Still unmeasured / open

- **`auger_motor_max_rpm` = 300 is a bracket, not a measurement.** The screw is
  known to work at 269 RPM and to stall at 643; the truth is somewhere between.
  `CLAY_AUGER_SPIN REVS=20 RPM=<n>` stepping upward under load settles it. Every
  RPM found there is print speed, because the cap is derived from it.
- **`EXTRUSION_MULT` = 0.85 in `gen_cylinder.py`** came from one wall reported as
  slightly over-extruded — trim live with `M221 S<pct>` and fold the settled
  number back in.
- **Auger motor current is 2.0 A RMS = 2.83 A peak/phase** (raised from 1.8 for
  torque; hold 1.0). It is a "standard LDO NEMA 17" — if that is the common
  2.5 A part, **this is 13% over rated** (max continuous would be 1.77 A RMS).
  Check the motor by hand; see gotchas §12.
- **`[tmc5160 extruder1]` runs 2.8 A RMS = 3.96 A peak**, far beyond any NEMA 17.
  Assumed to be a larger geared motor — confirm.
- **`auger_eff` 0.7366 is an anchor, not a measurement** (§3).
- The auger reported `ola/olb` open-load flags at standstill — likely a false
  positive; re-read during a move.
- CO2 subsystem is entirely dead: `co2_macros.cfg` never included, bridge not
  running, dummy service POSTs to a GET-only endpoint, the ppm readout is a
  floating ADC pin. Deliberately not fixed.
