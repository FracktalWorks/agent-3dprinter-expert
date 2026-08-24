"""Generate a single-wall clay cylinder for MANDEL, with E in mm3.

Everything on this machine is volumetric now — one mm of commanded E is one mm3
of clay — so the extrusion figures here are bead cross-sections, not the
arbitrary units the older files in ~/printer_data/gcodes use. Those predate the
change and are wrong by 24.45x; do not copy their E values.
"""
import math

DIA = 50.0          # cylinder outside diameter, mm
NOZZLE = 3.0        # nozzle bore -> bead width, mm
LAYER_H = 2.0       # layer height, mm
FIRST_H = 1.0       # first layer height, mm
LAYERS = 20         # 1 first layer + 19 at LAYER_H -> 39.0 mm tall
# THE FILE ASKS; THE MACHINE DECIDES.
#
# The feedrates below are what this part wants at full speed. They are NOT a
# promise the screw can keep: the flow it can pass depends on the ratio, which
# is chosen on the touchscreen after this file has already started. So the file
# arms CLAY_PRINT_LIMITS with its bead cross-section and the printer derives its
# own ceiling from the live ratio —
#
#   XY cap = auger_motor_max_rpm / 60 x (auger_vol_rev / balance) / bead
#
# — clamping every move below. Pick a low ratio at the pause and the print runs
# at the speeds below; pick a high one and it slows itself to suit. Nothing here
# needs regenerating either way.
#
# The auger ceiling is MEASURED: 50 mm3/s at 1:20 = 307 RPM.
AUGER_MAX_RPM = 307.0    # MEASURED: 50 mm3/s at 1:20
AUGER_VOL_REV = 195.599  # mm3 of clay per screw revolution
TARGET_FLOW = 100.0  # mm3/s — the DESIGN flow, i.e. the fastest this part wants
FIRST_SPEED = 15.0   # first layer, mm/s — slower so it keys onto the bed
CX, CY = 100.0, 100.0   # bed centre used by the existing working test file
# Chord length, not a fixed count: a 60 mm circle needs half again as many
# segments as a 40 mm one to keep the facets the same size.
CHORD = 1.3         # mm — target straight-line length of each circle segment


def bead_area(width, height):
    """Cross-section of an extruded bead: a rectangle with semicircular sides,
    which is the same convention slicers use for extrusion width."""
    return width * height - height * height * (1.0 - math.pi / 4.0)


A_FIRST = bead_area(NOZZLE, FIRST_H)
A_MAIN = bead_area(NOZZLE, LAYER_H)
# Flow is speed x bead area, and the bead is fixed by the nozzle and the layer
# height, so pinning the flow pins the XY speed. There is no third degree of
# freedom here short of changing the layer height.
XY_SPEED = TARGET_FLOW / A_MAIN
R = DIA / 2.0 - NOZZLE / 2.0     # path radius: the bead centreline, not the wall
CIRC = 2 * math.pi * R
SEGMENTS = max(96, int(round(CIRC / CHORD)))
HEIGHT = FIRST_H + (LAYERS - 1) * LAYER_H
TOTAL_VOL = CIRC * (A_FIRST + (LAYERS - 1) * A_MAIN)
FLOW = XY_SPEED * A_MAIN

# CONCENTRIC RINGS, not N loops retracing one circle — stacking loops in the
# same place just builds a thin wall of skirt and tells you nothing. At
# SKIRT_LOOPS = 1 this is a single ring; raise it and the extra rings step
# OUTWARD one bead at a time and print outermost first, so the nozzle always
# finishes on the innermost ring, closest to the part.
SKIRT_LOOPS = 1
SKIRT_GAP = 2 * NOZZLE          # clear of the wall, but close enough to be useful
SKIRT_R = R + SKIRT_GAP + NOZZLE / 2                      # innermost ring
SKIRT_RADII = [SKIRT_R + i * NOZZLE for i in range(SKIRT_LOOPS)][::-1]
SKIRT_VOL = sum(2 * math.pi * r * A_FIRST for r in SKIRT_RADII)

L = []
w = L.append
w(";" + "=" * 68)
w(f"; Clay cylinder  D{DIA:.0f} x H{HEIGHT:.0f} mm, single wall")
w("; MANDEL (IISc clay printer) — generated for the VOLUMETRIC config")
w(";")
w(f";   nozzle {NOZZLE} mm, layer {LAYER_H} mm, first layer {FIRST_H} mm")
w(f";   bead cross-section {A_MAIN:.2f} mm2 (first layer {A_FIRST:.2f} mm2)")
w(f";   path radius {R:.2f} mm on the bead centreline, {SEGMENTS} segments")
w(f";   skirt: {'1 ring' if SKIRT_LOOPS == 1 else str(SKIRT_LOOPS) + ' concentric rings, outermost first'}"
  f" at r=" + ", ".join(f"{r:.1f}" for r in SKIRT_RADII) + " mm")
w(f";   {SEGMENTS} segments = {CIRC/SEGMENTS:.2f} mm chords")
w(f";   XY {XY_SPEED:.2f} mm/s ({FIRST_SPEED:.0f} on the first layer and skirt)")
w(";   Z offset comes from the printer (CLAY_SET_Z_OFFSET), not from this file")
w(";")
w("; E IS IN mm3 OF CLAY OUT OF THE NOZZLE, measured at the plunger, and that")
w("; holds at any ratio — the balance moves the auger, not the plunger.")
w(";")
w(f";   flow demand {FLOW:.0f} mm3/s at {XY_SPEED:.1f} mm/s (first layer {A_FIRST*FIRST_SPEED:.0f} mm3/s)")
w(f";   plunger {FLOW * 60 / (3216.99 * 0.4):.1f} RPM  (motor ceiling 800)")
w(";")
w(f";   The auger ceiling is {AUGER_MAX_RPM:.0f} RPM (measured: 50 mm3/s at 1:20).")
w(";   CLAY_PRINT_LIMITS holds the toolhead under it at whatever ratio is set")
w(";   on the clay panel, so the effective speed is:")
w(";")
w(";     ratio      XY mm/s   mm3/s   auger RPM")
for _b in (5, 10, 15, 20, 25, 30, 40):
    _cap = AUGER_MAX_RPM / 60.0 * (AUGER_VOL_REV / _b) / A_MAIN
    _eff = min(_cap, XY_SPEED)
    w(f";     1:{_b:<8} {_eff:7.2f}  {_eff*A_MAIN:6.1f}  {_eff*A_MAIN*60/AUGER_VOL_REV*_b:8.0f}"
      + ("   (file-limited)" if _cap > XY_SPEED else ""))
w(";")
w(";   M220 S<pct> trims the speed live; M221 S<pct> trims the bead.")
w(f";   total {TOTAL_VOL + SKIRT_VOL:.0f} mm3 = {(TOTAL_VOL + SKIRT_VOL)/1000:.1f} mL"
  f" (part {TOTAL_VOL/1000:.1f} + skirt {SKIRT_VOL/1000:.1f})")
w(";" + "=" * 68)
w("")
w("G21                      ; mm")
w("G90                      ; absolute XYZ")
w("M83                      ; RELATIVE E, so every value below is one bead")
w("")
w("; ---- home, park over the middle, hand the screen over ----")
w("; Homes XYZ, leaves the bed at Z max, moves XY to centre, switches the")
w("; touchscreen to the clay panel and pauses. Prime the nozzle by hand there,")
w("; using either Extrude or Load mode, and set the ratio you want to print at.")
w("; Press RESUME when clay is flowing properly.")
w(f"CLAY_PRINT_START X={CX:.0f} Y={CY:.0f}")
w("")
w("; ---- straight into the print, at the ratio just chosen ----")
w("; NO SECOND G28. CLAY_PRINT_START already homed, and PAUSE/RESUME restores")
w("; the position, so re-homing only delays the print while the primed nozzle")
w("; sits there oozing. The idle timeout releases the two EXTRUDER motors only,")
w("; never X/Y/Z, so the machine is still homed however long the pause lasted.")
w("CLAY_RESYNC")
w("")
w(f"M117 Cylinder D{DIA:.0f} H{HEIGHT:.0f}")
w("")
w("; -- approach the bed at FULL speed, and only then arm the cap --")
w("; The cap is a toolhead velocity limit, so it slows travels and the Z")
w("; descent as much as it slows extrusion. Coming down from Z max that is")
w(f"; {(585 - FIRST_H - 10) / (AUGER_MAX_RPM / 60 * (AUGER_VOL_REV / 20.95) / A_MAIN):.0f}s of watching nothing happen at a 1:20.95 ratio. Arm it at the")
w("; first bead instead, where it is the only thing that matters.")
w(f"G1 X{CX + SKIRT_RADII[0]:.3f} Y{CY:.3f} F6000")
w(f"G1 Z{FIRST_H + 10:.3f} F6000")
w(f"G1 Z{FIRST_H:.3f} F600")
w(f"CLAY_PRINT_LIMITS BEAD={A_MAIN:.3f}   ; the machine now honours the auger ceiling")
w("")
w(f"; -- skirt: {'1 ring' if SKIRT_LOOPS == 1 else str(SKIRT_LOOPS) + ' concentric rings, outermost first'} at z={FIRST_H} --")
for _n, _r in enumerate(SKIRT_RADII):
    _se = A_FIRST * (2 * math.pi * _r) / SEGMENTS
    w(f"; ring {_n + 1}/{SKIRT_LOOPS}  r={_r:.2f}  E{_se:.3f}/segment")
    # step across to this ring's radius before tracing it, without extruding
    if _n:
        w(f"G1 X{CX + _r:.3f} Y{CY:.3f} F1800")
    for _i in range(1, SEGMENTS + 1):
        _a = 2 * math.pi * _i / SEGMENTS
        w(f"G1 X{CX + _r * math.cos(_a):.3f} Y{CY + _r * math.sin(_a):.3f}"
          f" E{_se:.3f} F{FIRST_SPEED * 60:.0f}")
w("")
w("; -- hop across to the part --")
w(f"G1 Z{FIRST_H + 5:.3f} F1200")
w(f"G1 X{CX + R:.3f} Y{CY:.3f} F6000")

z = 0.0
for layer in range(LAYERS):
    h = FIRST_H if layer == 0 else LAYER_H
    area = A_FIRST if layer == 0 else A_MAIN
    speed = FIRST_SPEED if layer == 0 else XY_SPEED
    z += h
    seg = CIRC / SEGMENTS
    e = area * seg
    w("")
    w(f"; -- layer {layer + 1}/{LAYERS}  z={z:.2f}  h={h}  {area:.2f} mm2 --")
    w(f"G1 Z{z:.3f} F600")
    for i in range(1, SEGMENTS + 1):
        a = 2 * math.pi * i / SEGMENTS
        w(f"G1 X{CX + R * math.cos(a):.3f} Y{CY + R * math.sin(a):.3f}"
          f" E{e:.3f} F{speed * 60:.0f}")

w("")
w("; ---- finish ----")
w("M400")
w("CLAY_PRINT_END")
w(f"G1 Z{z + 30:.3f} F600      ; lift clear of the part")
w("M117 Done")
w("; motors release themselves after the 60s idle timeout")
w("")

# Named from the geometry, so a changed diameter cannot quietly overwrite
# the previous test file — and the operator can tell them apart in Mainsail.
OUT = f"cylinder_d{DIA:.0f}_clay.gcode"
open(OUT, "w", newline="\n").write("\n".join(L))
print(f"{OUT}: D{DIA:.0f} x H{HEIGHT:.0f} mm, {LAYERS} layers, {len(L)} lines")
print(f"bead {A_MAIN:.2f} mm2 -> flow {FLOW:.1f} mm3/s at {XY_SPEED:.2f} mm/s")
print(f"clay {(TOTAL_VOL + SKIRT_VOL)/1000:.1f} mL "
      f"(part {TOTAL_VOL/1000:.1f} + skirt {SKIRT_VOL/1000:.1f}); "
      f"{SEGMENTS} segments, {CIRC/SEGMENTS:.2f} mm chords")
print(f"plunger {FLOW*60/(3216.99*0.4):.1f} RPM")
print(f"auger RPM demanded, against the {AUGER_MAX_RPM:.0f} ceiling:")
for b in (5, 10, 20.95, 25, 30):
    r = FLOW * 60 / AUGER_VOL_REV * b
    print(f"   at 1:{b:<6} -> {r:6.0f} RPM" + ("   *** OVER" if r > AUGER_MAX_RPM + 1 else ""))
