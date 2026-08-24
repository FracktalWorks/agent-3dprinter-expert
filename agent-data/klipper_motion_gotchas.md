# Klipper motion & extrusion gotchas

Non-obvious Klipper, Moonraker and KlipperScreen behaviours, each one found the
hard way while debugging a real machine. These are **general** — they apply to
any Klipper printer, not just the one that surfaced them. Machine-specific notes
live in `agent-data/machines/`.

Every entry is written as: what bites you, why, and what to do instead.

---

## 1. Toolhead velocity and acceleration limits apply to extrude-only moves — in E units

**The trap.** `[printer] max_velocity` and `max_accel` are written for XY, but
Klipper applies them to *every* move including pure-E ones. `Move.__init__` does
`velocity = min(speed, toolhead.max_velocity)`, and `extruder.check_move()` then
calls `move.limit_speed(max_e_velocity, max_e_accel)` — and **`limit_speed()`
only ever lowers**. So `max_extrude_only_velocity` and `max_extrude_only_accel`
can never raise a move above the toolhead's figures; they can only cut it
further.

**Why it matters.** If E is scaled to anything other than "mm of 1.75 mm
filament" — volumetric E, an auger, a peristaltic pump, a syringe — the toolhead
numbers are being applied in *your* unit. A machine with `max_velocity: 100`
meant as 100 mm/s of XY silently caps extrusion at **100 units/s**, and
`max_accel: 500` makes a stop take `rate / 500` seconds.

**Symptom.** Commanded flow is never achieved; the motion queue grows for the
whole of a long extrusion; a jog "runs on" for seconds after release; a purge
takes far longer than `volume / rate` predicts.

**What to do.** Bracket the operation with `SET_VELOCITY_LIMIT VELOCITY= ACCEL=
MINIMUM_CRUISE_RATIO=` and restore the config values afterwards. Raise
`max_extrude_only_accel` above the value you intend to use, or it becomes the
binding limit instead. Limits are baked into a move **when it is planned**, so
raise them *before* queueing and restoring them on release cannot lengthen a
stop already scheduled.

**Verify like this** — time a net-zero probe rather than guessing:

```gcode
SAVE_GCODE_STATE NAME=_p
M83
G1 E200 F<rate*60>
G1 E-200 F<rate*60>
M400
RESTORE_GCODE_STATE NAME=_p
```

Compare against `2 * (dist/v + v/a)` for a trapezoidal move. Net-zero so it
costs no material.

---

## 2. Klipper NEVER junctions extrude-only moves

**The trap.** `Move.calc_junction()` returns immediately if either move is
non-kinematic:

```python
if not self.is_kinematic_move or not prev_move.is_kinematic_move:
    return
```

`is_kinematic_move` is False for a move with no XYZ component, so `max_start_v2`
stays 0. **Every pure-E move accelerates from a standstill and decelerates back
to one**, even when the next move is already sitting in the queue behind it.

**Measured** (40 chunks vs one move, same total material, same feedrate):

| | achieved |
|---|---|
| one big move | 420 units/s (86% of requested) |
| 40 chunks back-to-back | 250 units/s (51%) |
| 40 chunks via a macro | 249 units/s (51%) — macro overhead is *not* the cause |

**Consequences, and they point the same way.** A deep queue buys **no**
smoothness for E-only motion, because the moves will not merge however many are
waiting — it only buys stop latency. And a chunk costs its material *plus* one
acceleration ramp, so chunk length (not tick rate) sets both throughput and
latency:

```
execution time = material/peak + peak/accel
```

**What to do when streaming E** (press-and-hold jogs, syringe pumps, live
extrusion):

- Model the queue locally from that formula instead of polling for it.
- Raise the peak feedrate so a chunk *averages* the rate you asked for. Solving
  `m/p + p/a = T` for `p` has no real root below `T = 4·rate/accel` — that
  inequality is the floor on usable chunk length.
- Do **not** shorten chunks hoping for a faster stop. Each chunk carries a fixed
  cost, so more chunks means more slip and the queue grows again. Measured on a
  real machine: 0.12 s → 0.08 s chunks took run-on from 0.34 s back to 1.1 s.

---

## 2b. "Internal error in stepcompress" = an acceleration no axis could ever be asked for

**The trap.** When two steppers are synced on one E axis, the acceleration limit
is expressed in the *active* extruder's unit. The other stepper sees
`accel / its_rotation_distance` rev/s² — and if its rotation distance is derived
from something the operator can turn down, that figure explodes as `1/rd`.

Real case: an auger pinned at its maximum RPM while the plunger's speed was
adjustable, so `auger_rd = plunger_rpm × plunger_base_rd / auger_max_rpm`.

| plunger setpoint | auger rd | auger accel | steps/s² |
|---|---|---|---|
| 500 RPM | 0.1333 | 750 rev/s² | 2.4 M |
| 55 RPM | 0.0147 | 6818 rev/s² | **21.8 M** |

A normal printer axis runs around 1 M steps/s². At 20× that, Klipper cannot
encode the step-interval sequence: **`Internal error in stepcompress`**, MCU
shutdown, every motor dead until `FIRMWARE_RESTART`.

**Symptom.** It worked at one setting and not another; nothing moves at all; the
console shows `Internal error in stepcompress` repeating for every subsequent
command because the printer is already shut down.

**What to do.** Bound the acceleration in the *other* stepper's own units and
convert back, taking the lower:

```jinja
{% set acc = [primary_accel, other_max_rev_accel * other_rd]|min %}
```

Both limits then scale together and the ramp takes the same time at every
setting. Publish the result as a derived variable so any UI modelling the motion
queue uses the same figure — a model using the uncut value under-estimates every
chunk and lets the queue grow.

**Sanity check before shipping any synced-stepper ratio:** compute
`accel / rd × steps_per_rev` and keep it near 10⁶ steps/s². Also check the step
*rate*: `rpm/60 × steps_per_rev`, and keep it under ~100 kHz per stepper.

---

## 2c. A geared secondary motor is bounded by nothing during a print

`SET_VELOCITY_LIMIT` and `max_extrude_only_*` do **not** bound a printing move's
extruder speed. `PrinterExtruder.check_move()` applies `max_e_velocity` /
`max_e_accel` only to *extrude-only* moves; for a kinematic move it checks the
cross-section ratio against `max_extrude_cross_section` and nothing else. The E
axis therefore runs at whatever `feedrate × E-per-mm` the file asks for.

That is harmless with a filament extruder, whose motor has orders of magnitude
of headroom. It is not harmless when the extruder is a **screw, a pump or any
motor near its torque limit** — and it is worse when a ratio multiplies its
speed, because the file's author sees only the flow, never the RPM.

The failure is silent and it is stage-dependent, which makes it look like
anything but a speed limit. On MANDEL: the first layer (2.79 mm² bead, 15 mm/s
= 42 mm³/s, 269 auger RPM) printed cleanly; layer two doubles the layer height,
so the same file at 19.4 mm/s asked for 100 mm³/s and **643 auger RPM**, and the
screw did not turn at all — it was commanded past its stall from a standstill.
No error, no shutdown, just no clay. Reported as *"from the second layer
onwards, the auger doesn't even turn before it's being commanded to rotate too
fast"*, which is a precise description of a stall on the acceleration ramp.

### The fix: convert the motor's ceiling into a toolhead ceiling

The missing link is the **bead cross-section**, mm³ per mm of travel, because
that is what turns a flow limit into a speed limit:

```
flow (mm3/s)    = XY speed (mm/s) x bead (mm2)
motor (rev/s)   = flow / rotation_distance
=> XY cap       = motor_max_rpm / 60 * rotation_distance / bead
=> XY accel cap = motor_max_accel(rev/s2) * rotation_distance / bead
```

Have the g-code declare its largest bead, hold it in a macro variable, and
re-derive both limits on every apply. Klipper then just slows the toolhead and
the print comes out right, only slower. Three details matter:

- **Arm it after homing.** The cap applies to *every* move. A 585 mm Z axis at
  11 mm/s is a minute of homing.
- **Re-derive on ratio change.** `rotation_distance` carries the ratio, so
  halving the ratio doubles the allowed print speed for free — no regenerated
  g-code. That is the argument for computing the cap on the machine rather than
  baking a feedrate into the file.
- **Anything that restores limits must respect it**, including the jog-release
  bracket. Restoring `configfile.settings.printer.max_accel` after a
  prime-by-hand hands the resumed print exactly the acceleration that stalled it.

On MANDEL this was built, measured working, and then **reverted the same day**
— not because it was wrong but because it shipped alongside several other
changes and the machine got worse overall. Ship a cap like this on its own,
after the motor's ceiling is measured, and change one thing at a time. That rule
exists for a reason and this is what breaking it looks like.

### Corollary: set the ceiling from what the machine has demonstrated

A motor spec RPM is not a working ceiling for anything driving a load. Bracket
it from the print itself — 269 RPM worked, 643 did not — and set the limit just
above the demonstrated-good point, not in the middle of the unknown range. It
costs print speed, which is recoverable; the alternative costs a print.

## 3. There is no motion-queue flush, so stop latency IS queue depth

`M410` is a Marlin command and does not exist in Klipper. Nothing drains the
queue short of an emergency stop. Any "stop when the button is released"
behaviour must come from never letting the queue get deep in the first place.

Budget the release overrun as: **queue depth + deceleration time**.

---

## 4. `BUFFER_TIME_START` adds 0.25 s of queue that is never recovered

When motion starts from idle, `toolhead._calc_print_time()` sets
`print_time = est_print_time + BUFFER_TIME_START` (0.250 s). It is a **module
constant in `toolhead.py`, not a config option** in current Klipper — older
versions exposed `buffer_time_start` under `[printer]`; check before assuming.

If you then feed material at exactly wall-clock rate, the machine stays
permanently that 0.25 s behind, and it all comes back as run-on. Seed it into
your queue model, or anchor pacing to measured execution rather than the clock.

**Measure it:** from idle, issue a move of known duration, then read
`print_time - estimated_print_time`. A 1.00 s move read 1.15 s.

---

## 5. `print_time − estimated_print_time` is the queue depth — but it is a poor sensor

Both come from the `toolhead` object, and their difference is genuinely the
seconds of motion still queued. Useful for one-shot diagnosis.

**Do not close a tight control loop on it.** Through Moonraker it is ~250 ms
stale, and it updates burstily as moves are flushed — readings of 0.01 s and
1.56 s a few hundred ms apart on a steady stream. A controller chasing it
oscillates. Model the queue locally instead (§2).

When idle it reads a large negative number (stale `print_time`); treat anything
below ~0 as "idle", not as data.

---

## 6. `minimum_cruise_ratio` caps deceleration on short moves

Default 0.5, meaning at least half of every move must be spent at cruise speed —
which limits how hard a short move may accelerate or decelerate. The last chunk
of a streamed jog is exactly that: a short move that has to stop. Set
`MINIMUM_CRUISE_RATIO=0` via `SET_VELOCITY_LIMIT` for the duration and restore
it. (Older Klipper called this `max_accel_to_decel`.)

---

## 7. Config validation traps

- **`filament_diameter` must be ≥ `nozzle_diameter`.** This kills the otherwise
  neat trick of choosing a diameter that makes `filament_area` exactly 1.0 so
  `max_extrude_cross_section` reads directly in mm² of bead.
- **`max_extrude_cross_section / filament_area`** is the limit on E-per-mm-of-XY.
  With volumetric E that ratio *is* the bead cross-section in mm², so size it
  from the widest bead you intend to print.
- **`max_extrude_only_distance`** is in E units. Volumetric E makes the default
  50 mm mean 50 mm³, which is nothing.

---

## 8. `[save_variables]` rewrites the whole file from memory

Editing `variables.cfg` while Klipper is running is futile — the next
`SAVE_VARIABLE` writes the entire in-memory dict back and silently reverts your
edit. To remove a stale key: **stop Klipper, edit, start Klipper.** There is no
`DELETE_VARIABLE`.

Also: saved values override config defaults at startup. Changing a
`variable_foo` default in a macro does nothing if `foo` was ever saved — push the
new value through its setter macro as well.

---

## 9. Jinja2 in Klipper macros

- **`{% set %}` inside `{% if %}` does not escape the block.** A clamp written as
  an if-block silently does nothing. Use filters: `{% set v = [[v, hi]|min, lo]|max %}`
- **String variables** need quotes inside the value:
  `SET_GCODE_VARIABLE MACRO=X VARIABLE=mode VALUE="'load'"` — the value is parsed
  with `ast.literal_eval`.
- **A macro renders once, then executes.** Values read via `printer[...]` are
  captured at render time, so a variable set earlier *in the same macro* is not
  visible later in it. Split into two macros when you need the updated value.

---

## 10. `idle_timeout`'s default gcode is `M84` — it un-homes the machine

The stock gcode is `TURN_OFF_HEATERS` + `M84`, and `M84` drops **every** stepper.
On any printer where a print can legitimately sit idle — an operator-popup
`PAUSE`, a filament change, a manual intervention — that silently loses the
gantry's position mid-job.

Release only what you mean to:

```ini
[idle_timeout]
timeout: 60
gcode:
    {% if 'heaters' in printer %}
        TURN_OFF_HEATERS
    {% endif %}
    SET_STEPPER_ENABLE STEPPER=extruder ENABLE=0
    SET_STEPPER_ENABLE STEPPER=extruder1 ENABLE=0
```

**Steppers re-arm themselves.** A Klipper stepper is re-enabled automatically as
soon as a move needs it (`stepper.add_active_callback`), so nothing has to turn
them back on. Verified: released at idle, re-armed on the next 1 mm³ jog.

Note `idle_timeout.state` reports `"Printing"` for *any* activity including
jogging, so it is the wrong thing to guard macros with. Use
`printer.print_stats.state == "printing"`, which correctly excludes `"paused"`.

---

## 10b. A ratio that moves changes every derived figure, not just the motion

When a ratio is moved from one axis to another — MANDEL's `balance` went from
the plunger's `rotation_distance` to the auger's — the motion is usually fixed
carefully and the **derived read-outs are forgotten**. They keep dividing by the
old constant and are then wrong by exactly the ratio, silently, forever.

On MANDEL the screw's rotation distance became `auger_vol_rev / balance`, so
anything computing revolutions still using `auger_vol_rev` alone was **21× out
at 1:20.95**. The panel under-reported the auger as 10 RPM while it turned at
212, and a characterisation macro turned the screw 21× further than asked, at
21× the stated speed. Two other macros doing the same arithmetic had been fixed
at the time; these two were missed.

Two habits that would have caught it:

- After moving a ratio, **grep the whole tree for the old constant** and check
  every use against the new rotation distance. It is a mechanical check.
- **Believe the operator over the display.** "It seems to be spinning faster
  than it says" is a measurement. The panel is not.

---

## 10c. Do not drive an operator's touchscreen while they are standing at it

Injecting synthetic taps to verify a panel is a legitimate technique (§14) and
it is unusable the moment someone is at the machine. Symptoms of the collision
look exactly like bugs: values changing on their own, a mode that will not stay
where it is put, controls that appear stuck. Hours can go into chasing them.

Check `print_stats` / recent `gcode_store` for input you did not send, and if
the operator is present, **read the state over the API and ask them what the
screen shows** rather than screenshotting and tapping.

---

## 10d. `rename_existing` must keep the command's *type*

Overriding a built-in G-code with a macro is the standard way to hook it, and it
has one trap that stops the printer dead:

```ini
[gcode_macro G28]
rename_existing: BASE_G28      # CONFIG ERROR — will not boot
rename_existing: G28.1         # correct
```

`gcode_macro` compares `is_traditional_gcode(alias)` against
`is_traditional_gcode(rename_existing)` and refuses a mismatch:

    G-Code macro rename of different types ('G28' vs 'BASE_G28')

A traditional G-code (`G28`, `M104`) must be renamed to another traditional name
— the convention is a decimal suffix, `G28.1`, `M104.1`. Extended commands
(`PAUSE`, `CANCEL_PRINT`) rename to extended names, which is why
`rename_existing: BASE_CANCEL_PRINT` is fine and looks like a counter-example.

**This is a config error, not a runtime one**: the printer refuses to start at
all, and Moonraker's `FIRMWARE_RESTART` request simply times out rather than
returning the message. Read `state_message` from `/printer/info` to see it.

---

## 10e. A persistent limit needs a release path, not just a guard

`SET_VELOCITY_LIMIT` persists until something sets it again. Any scheme that
*computes* a limit from state — a variable, a print-status gate — must also
answer **"what runs to put it back?"**, for every exit path including the ones
nobody plans: cancel, error, power-cycle mid-print, an operator homing from the
touchscreen.

On MANDEL a print-speed cap was reported as "homing is too slow" **three times**,
each with a different missing release path:

1. clearing the variable but not calling `SET_VELOCITY_LIMIT` again
2. gating re-arming on `print_stats`, which stops it being re-applied but never
   releases what is already set
3. a cancelled print, which reaches neither the end-of-file macro nor the idle
   timeout promptly

The fix that finally held was to stop enumerating exits and **put the release
where the symptom is**: override `G28` to restore the configured limits before
homing and re-derive afterwards. Homing is never an extruding move, so it can
always be fast; and re-deriving afterwards means a genuine mid-print homing is
not weakened. Enumerating exit paths is a losing game — find the operation that
must always be safe and make it safe unconditionally.

---

## 11. Diagnostic instruments that lie

- **`motion_report.live_velocity` is the toolhead's XY speed** and is identically
  zero for an extrude-only move. Use **`live_extruder_velocity`**.
- **`/server/gcode_store` retains old output.** Reading the tail after issuing
  `DUMP_TMC` or `SET_EXTRUDER_ROTATION_DISTANCE` will happily hand you the
  *previous* run's values and confirm a state that no longer exists. Anchor to a
  unique marker: `RESPOND MSG=MARKER`, then read only entries after it.
- **Moonraker's REST round-trip is ~250 ms even on localhost.** Any harness that
  drives a timed loop over HTTP cannot replicate a websocket client's timing —
  it will report its own latency as the machine's behaviour. Use the websocket
  (`websocket-client` lives in KlipperScreen's venv, not system python).
- **TMC `DRV_STATUS` `stealth=1` persists at standstill** even on spreadCycle;
  it is a `stst=1` artifact. Compare `TPWMTHRS` against a known-good axis
  instead.

---

## 12. Stepper current: rated is peak, `run_current` is RMS

Motor datasheets (LDO, Moons, OMC…) quote **peak amps per phase**. Klipper's
`run_current` is **RMS**. With sinusoidal microstepping the peak phase current is
`run_current × √2`, so:

```
max continuous run_current = rated / √2
```

A 2.5 A NEMA 17 tops out at **1.77 A RMS**. Setting `run_current: 2.0` on it is
13% over rated, and copper loss scales with the square. Sustained operation
above ~80 °C risks permanently demagnetising the rotor — not recoverable by
turning the current back down.

**Microstepping does not change torque.** With `interpolate: True` the TMC
reconstructs 256 microsteps internally whatever Klipper sends, so the motor sees
the same sinusoidal current; peak torque is set by current alone. When more
torque is genuinely needed and current is maxed, the answer is gearing, not amps.

**Lowering microsteps is the right lever for step rate, but it is NOT free —
it costs usable top speed.** `steps/s = rpm/60 × full_steps × microsteps`, and
`rotation_distance` is untouched, so every derived figure (volumetric E,
calibration, flow) survives exactly as it was. That much is true and is why the
lever is tempting. What is not true is that interpolation makes it costless.

MANDEL was taken to `microsteps: 1` on both extruder motors and the operator
reported, unprompted, *"I cannot move as fast as I was moving earlier."*
Restoring 16 fixed it. Two mechanisms, neither of which interpolation covers:

- **MicroPlyer interpolates from the PREVIOUS step interval.** It is predictive,
  not lookahead — it spreads 256 microsteps across the time it expects the next
  step to take, based on the last one. At constant speed that is accurate. During
  acceleration it systematically mispredicts, and the error scales with how long
  a commanded step lasts, which is 16× longer at full stepping.
- **Full-step commanding excites rotor resonance.** A 1.8° yank per pulse drives
  the motor's mid-band resonance directly; microstepping is the standard cure for
  exactly this. Under load the resonance shows up as a stall well below the speed
  the motor would otherwise reach.

So treat microstepping as a **speed-vs-pulse-rate trade**, not a free win:

| Want | Do |
|---|---|
| Step-rate headroom, load tolerates it | drop to 8 or 4 — still 1600/800 steps/rev |
| Maximum usable RPM under load | keep 16 or higher |
| Fix positional quantisation | raise it |

Worked example of the temptation: an auger asked for 1500 RPM at 16 microsteps
needs 80,000 steps/s, near the sane per-stepper ceiling. But check whether the
motor ever reaches that speed first — MANDEL's stalls between 270 and 640 RPM,
i.e. 14,000–34,000 steps/s, so there was never a step-rate problem to solve and
the microstep drop was pure cost. **Size the ceiling from measured RPM, not from
the configured placeholder.** For a volumetric extruder the quantum that matters
is `mm³ per step = rotation_distance / (full_steps × microsteps)`.

---

## 13. KlipperScreen

- **`// action:ks_show <panel>` switches panels** — a built-in mechanism
  (`screen.py: process_action → parse_ks_action → show_panel`), no patching
  required. From a macro: `{ action_respond_info("action:ks_show clay") }`.
  It also accepts `ks_show <panel> <key>=<value>`.
- **Fire it from a `[delayed_gcode]` ~1.5 s AFTER `PAUSE`**, not inline. `PAUSE`
  itself moves KlipperScreen to `job_status` and would overwrite the switch.
- **KlipperScreen validates `[printer X]` config options against a whitelist** —
  unknown keys raise an error modal at startup. Reuse an existing key rather than
  inventing one.
- **It does not subscribe to `gcode_macro` objects.** A panel that needs live
  macro variables must query them explicitly with `printer.objects.query` in
  `activate()`.
- **`leave-notify-event` on a Gtk.Button must be filtered to
  `Gdk.CrossingMode.NORMAL`** — GTK synthesises crossings around the implicit
  pointer grab, so an unfiltered handler aborts every press-and-hold the instant
  it starts.
- **Layout:** `set_size_request` sets a *minimum* only, and `row_homogeneous`
  makes every row as tall as the tallest row's minimum. What governs row height
  is each button's natural size — shrink it with the `scale` argument and
  `lines=1` (`format_label` reserves two text lines).

---

## 14. Driving a touchscreen headlessly (for verification)

When there is no xdotool and no python-Xlib, write `input_event` structs directly
to `/dev/input/eventN` as root — writing to an evdev node injects into the input
subsystem. Struct is `llHHi` on 64-bit, `iiHHi` on 32-bit. Emit ABS_X, ABS_Y,
ABS_PRESSURE, BTN_TOUCH=1, SYN_REPORT; hold ~120 ms; then release.

**Do not trust the calibration file to tell you the axis mapping** — it composes
with any panel rotation. Probe it: KlipperScreen logs `Loading panel: <name>` for
every navigation, which is a free oracle, and main-menu taps move nothing.
Never probe against a panel whose buttons issue `G28` or `G1`.

Screenshots: `DISPLAY=:0 XAUTHORITY=~/.Xauthority import -window root out.png`.

---

## 15. Calibrating a drivetrain you cannot observe

When nothing in the drivetrain can be counted (a rotating nut inside a gearbox, a
sealed reducer), commanded revolutions against measured linear travel is the only
measurement available — and it is enough.

Set `rotation_distance` to **1.0** for the test so one mm of commanded E is
exactly one motor revolution, whatever the configured value happens to be. Then:

- **Guard the acceleration.** With `rotation_distance: 1.0`, `max_extrude_only_accel`
  is in rev/s². A stock 500 means 500 rev/s², violent enough to stall on the ramp
  and under-read the travel — you then blame the wrong thing. Pass an explicit
  low `SET_VELOCITY_LIMIT ACCEL=`.
- **Lost steps only ever shorten travel.** When two calibration runs disagree,
  trust the longer one.
- **Verify rotation separately from ratio.** Turning a whole number of
  revolutions and checking a mark on the coupler returns confirms
  `full_steps_per_rotation` (200 vs 400 — a 0.9° motor makes every derived figure
  wrong by exactly 2×), `microsteps`, and that the coupling really is 1:1. It is
  a different question from how much material moved, and worth its own test.

---

## 16. Slicing for a volumetric or paste extruder

Everything here was found configuring PrusaSlicer 2.9.6 for a clay printer whose
E axis is volumetric (1 E mm = 1 mm³ out of the nozzle). Most of it applies to
any machine whose extruder is a pump, a screw or a syringe rather than a hotend.

### Make the slicer's E match the machine, with a fake filament diameter

Slicers emit E in linear mm of filament. If the machine's E is mm³, declare a
filament whose cross-section is exactly 1 mm²:

```
area = pi/4 * d^2 = 1   ->   d = sqrt(4/pi) = 1.128379 mm
```

Then one mm of "filament" **is** one mm³ and no conversion is needed anywhere.
Three side benefits: the slicer's material statistics stay correct (it computes
volume as length × area), `filament_max_volumetric_speed` becomes a direct
statement of the pump's ceiling in mm³/s, and the numbers in the G-code are
readable against the machine's own units.

This is better than the slicer's own "volumetric E" option, which is not present
everywhere and interacts with firmware `M200`.

### `filament_max_volumetric_speed` is the right home for a flow ceiling

A pump has a hard flow limit; a hotend has a soft one. Put the limit there, in
mm³/s, and the slicer slows every move to fit — including the time estimate,
which is otherwise a fiction. Do not translate it into a speed by hand: the speed
that respects it changes with every bead cross-section.

Design a profile with **two ceilings in series** — a *design flow* (what the
process wants) and the *machine flow* (what the pump can pass). Whichever is
lower wins, and neither has to know about the other.

### Slicer-side acceleration control silently overwrites firmware limits

This is the one that bites hardest when the firmware is enforcing something.
PrusaSlicer writes an acceleration before every feature — `M204` under Marlin
flavours, **`SET_VELOCITY_LIMIT` under the Klipper flavour** — which overwrites
whatever the firmware had set. Any scheme where a macro caps acceleration to
protect a motor is defeated by it, mid-print, invisibly.

Set every `*_acceleration` to **0**, which in PrusaSlicer means *do not emit*.
Also set `machine_limits_usage = time_estimate_only` so `M201`/`M203` stay out of
the file. Then audit the output for both — see the harness below.

Corollary: **prefer the `marlin` flavour over `klipper` on a Klipper machine** if
firmware macros own the velocity limits, precisely because the Klipper flavour
emits the same command the macros use. Klipper's own documentation recommends
Marlin anyway.

### `layer_gcode` is NOT emitted for the first layer

Verified by slicing: the first `G92 E0` from `layer_gcode` lands at the **second**
layer change. So the common idiom

```
{if layer_num == 0}DO_SOMETHING_ONCE{endif}
```

placed in "After layer change G-code" **never fires**, and does so silently — the
command is simply absent from every file. Anything that must happen once at the
start belongs in `start_gcode`.

If it must happen *after* the first Z move (for example arming a limit that would
otherwise slow that move), do the Z move yourself at the end of `start_gcode`:

```
G1 Z{first_layer_height} F6000
ARM_THE_LIMIT
```

The slicer's own first-layer Z move is then already satisfied and costs nothing.

### Relative E requires `G92 E0` in `layer_gcode` — it refuses to slice otherwise

> Relative extruder addressing requires resetting the extruder position at each
> layer to prevent loss of floating point accuracy. Add "G92 E0" to layer_gcode.

Not advisory: PrusaSlicer produces no output at all. It also matters more than
usual with volumetric E, where the accumulated value reaches tens of thousands.

### A fixed-bore nozzle must use the classic perimeter generator

Arachne varies extrusion width to fit thin features. A pump feeding a fixed bore
cannot vary its bead width, so a varying width becomes a varying flow that the
machine's ceiling was never told about. `perimeter_generator = classic`.

### Pin off anything that needs a firmware section you do not have

- `arc_fitting` emits `G2`/`G3`, which needs Klipper's `[gcode_arcs]`
- `gcode_label_objects` emits `EXCLUDE_OBJECT_*` or `M486`, which needs
  `[exclude_object]`

Both abort the print on an unknown command. They are usually already off — pin
them anyway, so enabling one later is deliberate rather than a default drifting
in on an upgrade.

### Validate by slicing, not by reading

A config bundle can be syntactically perfect and still wrong in ways only the
output shows. Automate it: merge the profiles into a flat config, slice a real
object with the slicer's CLI, and assert on the G-code —

- the custom macros are present, with **numeric** arguments (an unevaluated
  expression shows up as an empty or literal value)
- **no** `M204`, `SET_VELOCITY_LIMIT`, `M201`, `M203`, `M200`, temperature, fan
  or retraction commands
- **E is in the expected unit**: measure mm³ per mm of travel from the file and
  compare against the profile's computed bead
- **peak flow does not exceed the ceiling**, computed from the file's own E,
  distances and feedrates

`agent-data/machines/mandel/slicer/validate.py` is a working example. Both
first-layer bugs above, and a first-layer speed 1.7× over the design flow, were
found by running the matrix — none were visible by inspection.

### Sweep the whole matrix, not one combination

The over-flow first layer only appeared at the *loosest* ratio, because the
tighter ceilings were masking it. Run every nozzle against every flow ceiling: a
limit that is doing its job hides the errors underneath it.
