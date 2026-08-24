#!/usr/bin/env python3
"""Generate a PrusaSlicer config bundle for MANDEL, the IISc clay printer.

Regenerate with:  python gen_prusaslicer_bundle.py
Import with:      PrusaSlicer -> File -> Import -> Import Config Bundle

WHY THE FILAMENT DIAMETER IS 1.128379 mm
----------------------------------------
This machine's E axis is VOLUMETRIC: one mm of commanded E is one mm3 of clay
out of the nozzle, at any Plunger:Auger ratio. Slicers emit E in linear mm of
filament, so the only way to make those two agree is to declare a filament
whose cross-section is exactly 1 mm2:

    area = pi/4 * d^2 = 1   ->   d = sqrt(4/pi) = 1.128379 mm

Then 1 mm of "filament" IS 1 mm3, and every E value the slicer writes is already
in the machine's units. It also keeps the slicer's own statistics honest (volume
is computed as length x area, so mm3 used comes out right), and it makes
filament_max_volumetric_speed a direct statement of the auger's ceiling.

Do NOT instead set Klipper's filament_diameter to 1.128379: Klipper rejects it
(minimum 4.0), and it is not needed, because nothing here uses Klipper's own
volumetric mode.
"""
import math

# -- the machine ------------------------------------------------------------
# Limited by what the CURRENT config can reach, not by the machine's physical
# size. Y homes to its MAX endstop and Klipper calls that Y=200, so any Y above
# 200 is a crash however long the axis really is. Raise these once printer.cfg
# is corrected and the travel measured -- see README.md.
BED_X, BED_Y = 200.0, 200.0
MAX_Z = 300.0
TRAVEL = 100.0           # printer.cfg max_velocity
AUGER_VOL_REV = 195.599  # mm3 of clay per screw revolution
AUGER_MAX_RPM = 307.0    # MEASURED: 50 mm3/s at a 1:20 ratio

FILAMENT_D = round(math.sqrt(4.0 / math.pi), 6)   # 1.128379 -> area 1.000 mm2

# nozzle -> (layer height, first layer height)
#
# The 3 mm row is not a guess: it is exactly what the hand-written cylinder test
# printed with (2.0 mm layers, 1.0 mm first layer, 3.0 mm bead). The others keep
# the same ~2/3 of nozzle ratio.
NOZZLES = {
    3.0: (2.0, 1.0),
    4.0: (2.5, 1.25),
    5.0: (3.0, 1.5),
    6.0: (4.0, 2.0),
}

# The DESIGN flow -- what the process wants, before the auger has its say. Also
# taken from the cylinder test, which was written around 100 mm3/s. Per nozzle it
# becomes a speed: 100/bead. The volumetric ceiling then reduces it further
# whenever the ratio demands, so this is the fastest the profile will ever ask
# for and the ratio decides what actually happens.
DESIGN_FLOW = 100.0     # mm3/s
FIRST_LAYER_SPEED = 15.0  # mm/s absolute, as in the cylinder test

# Purge line, laid before the part. Front-left corner, clear of any object
# centred on a 200 mm bed up to ~170 mm across. Length rather than volume is the
# constant, so the line looks the same for every nozzle and the volume scales
# with the bead: 60 mm x 5.14 mm2 = 309 mm3 on the 3 mm nozzle.
PURGE_X, PURGE_Y = 15.0, 15.0
PURGE_LEN = 60.0        # mm
SAFE_LIFT = 5.0         # mm above the first layer for the travel to the part

# The ratio chosen at the print-start pause decides how much clay the screw can
# pass, so it -- not the nozzle -- sets throughput. One filament profile per
# working ratio, each carrying that ratio's ceiling as max volumetric speed.
RATIOS = [5, 10, 20]


def bead(width, height):
    """Rectangle with semicircular sides -- the same model the slicer uses."""
    return width * height - height * height * (1.0 - math.pi / 4.0)


def flow_ceiling(ratio):
    return AUGER_MAX_RPM / 60.0 * (AUGER_VOL_REV / ratio)


NL = "\\n"      # PrusaSlicer .ini encodes newlines inside a value as literal \n

START_GCODE = NL.join([
    "; MANDEL clay printer -- E is mm3 of clay out of the nozzle",
    "G21 ; mm",
    "G90 ; absolute XYZ",
    "M83 ; relative E",
    "; Homes, parks at the bed centre with the bed at Z max, throws the",
    "; touchscreen onto the clay panel and PAUSES. Prime the nozzle by hand,",
    "; choose the Plunger:Auger ratio, then RESUME.",
    "CLAY_PRINT_START X={0:.0f} Y={1:.0f}".format(BED_X / 2, BED_Y / 2),
    "; --- everything below runs after RESUME ---",
    "; Re-assert the synced state at whatever ratio was just chosen.",
    "CLAY_RESYNC",
    "; Travel to the purge spot FIRST, still at Z max, and descend there.",
    "; PrusaSlicer would otherwise descend at the park position -- the middle of",
    "; the part footprint -- deposit whatever oozed during the pause right there,",
    "; and then drag the nozzle out through it at layer height.",
    "G1 X{0:.0f} Y{1:.0f} F6000".format(PURGE_X, PURGE_Y),
    "G1 Z{first_layer_height} F6000",
    "; Arm the cap before the purge, not after: the purge is a MOVING line, so",
    "; the cap's velocity limit gives it exactly the right flow. (An",
    "; extrude-only purge would instead be held to mm3/s = mm/s and crawl.)",
    "CLAY_PRINT_LIMITS BEAD="
    "{extrusion_width * layer_height - layer_height * layer_height * 0.214602}",
    "; Purge line -- the flow check you can look at before the part starts. F is",
    "; deliberately generous; the cap clamps it to the auger's rate.",
    "G1 X{0:.0f} E".format(PURGE_X + PURGE_LEN)
    + "{(extrusion_width * layer_height - layer_height * layer_height * 0.214602)"
      " * " + "%.1f" % PURGE_LEN + "} F1800",
    "; Lift clear so the travel to the part does not drag through the purge.",
    "G1 Z{first_layer_height + " + "%.1f" % SAFE_LIFT + "} F1200",
])

# G92 E0 IS MANDATORY, not decoration. With use_relative_e_distances = 1
# PrusaSlicer REFUSES TO SLICE unless layer_gcode resets the extruder position
# each layer -- "Relative extruder addressing requires resetting the extruder
# position at each layer to prevent loss of floating point accuracy." It is also
# genuinely needed here: E is mm3, so the accumulated value is enormous (tens of
# thousands per print) and float precision would start to bite.
#
# NOTE: layer_gcode is NOT emitted for the first layer. Verified by slicing --
# the first G92 E0 lands at the SECOND layer change. So {if layer_num == 0} here
# never fires, and anything that must happen once at the start belongs in
# start_gcode instead. That is where CLAY_PRINT_LIMITS lives.
LAYER_GCODE = "G92 E0"

END_GCODE = NL.join([
    "M400",
    "CLAY_PRINT_END        ; release the auger speed cap",
    "; Lift well clear of the part, which is wet and easily knocked. Only after",
    "; CLAY_PRINT_END, so this runs at full Z speed rather than the auger's.",
    "G1 Z{max_layer_z + 30} F600",
    "M117 Done",
    "; the extruder motors release themselves after the 60s idle timeout",
])

out = []
w = out.append

w("# PrusaSlicer config bundle -- MANDEL (IISc clay printer)")
w("# Generated by gen_prusaslicer_bundle.py. Edit that, not this.")
w("#")
w("# E is mm3 of clay out of the nozzle. Read ./README.md before changing")
w("# filament_diameter or filament_max_volumetric_speed -- both encode")
w("# properties of the machine, not preferences.")
w("")

# -- print profiles ---------------------------------------------------------
for nz in sorted(NOZZLES):
    lh, flh = NOZZLES[nz]
    w("[print:Clay %gmm nozzle]" % nz)
    w("layer_height = %s" % lh)
    w("first_layer_height = %s" % flh)
    # Every width is the nozzle bore: clay leaves the nozzle at its own diameter
    # and is not squashed into a wider bead the way plastic is.
    for k in ("extrusion_width", "first_layer_extrusion_width",
              "perimeter_extrusion_width", "external_perimeter_extrusion_width",
              "infill_extrusion_width", "solid_infill_extrusion_width",
              "top_infill_extrusion_width"):
        w("%s = %g" % (k, nz))
    w("perimeters = 1")
    w("extra_perimeters = 0")
    w("extra_perimeters_on_overhangs = 0")
    # CLASSIC, never Arachne. Arachne varies extrusion width to fit thin
    # features -- which is exactly what a fixed-bore clay nozzle cannot do. A
    # varying width would mean a varying bead and therefore a varying flow the
    # screw was never asked about.
    w("perimeter_generator = classic")
    w("seam_position = aligned")
    # Never 'random' or 'nearest' on clay: a wet wall shows every seam, and an
    # aligned seam is one vertical line instead of a spiral of blemishes.
    w("top_solid_layers = 0")
    w("bottom_solid_layers = 1")
    w("fill_density = 0%")
    w("fill_pattern = concentric")
    w("bottom_fill_pattern = concentric")
    w("top_fill_pattern = concentric")
    # No G2/G3: the machine has no [gcode_arcs] section, so arcs would be
    # rejected as unknown commands mid-print.
    w("arc_fitting = disabled")
    w("spiral_vase = 0")
    w("thin_walls = 0")
    w("gap_fill_enabled = 0")
    w("overhangs = 0")
    w("ensure_vertical_shell_thickness = 0")
    # One speed everywhere, from the design flow, so no feature can surprise you
    # with a different bead. small_perimeter_speed matters on a 50 mm circle,
    # which PrusaSlicer would otherwise slow on its own.
    design_speed = DESIGN_FLOW / bead(nz, lh)
    for k in ("perimeter_speed", "external_perimeter_speed", "infill_speed",
              "solid_infill_speed", "top_solid_infill_speed", "bridge_speed",
              "small_perimeter_speed", "gap_fill_speed"):
        w("%s = %.2f" % (k, design_speed))
    w("max_print_speed = %.2f" % design_speed)
    # Absolute, not a percentage: the test used 15 mm/s flat, and a percentage
    # would drift every time the design speed changed.
    #
    # But it must also respect the design flow. 15 mm/s on the 3 mm nozzle's
    # 2.79 mm2 first-layer bead is 42 mm3/s, comfortably under; on the 6 mm
    # nozzle's 11.14 mm2 bead it is 167 mm3/s, which is 1.7x the design flow and
    # only got caught by the volumetric ceiling at high ratios. Measured in the
    # validation matrix at 1:5, where the ceiling is loose enough not to hide it.
    first_speed = min(FIRST_LAYER_SPEED, DESIGN_FLOW / bead(nz, flh))
    w("first_layer_speed = %.2f" % first_speed)
    w("travel_speed = %g" % TRAVEL)
    w("travel_speed_z = %g" % TRAVEL)
    w("brim_width = 0")
    w("skirts = 1")
    # Edge-to-edge gap between skirt and wall, matching the cylinder test's 4.5.
    w("skirt_distance = 5")
    w("skirt_height = 1")
    w("min_skirt_length = 0")
    w("support_material = 0")
    w("complete_objects = 0")
    w("elefant_foot_compensation = 0")
    w("gcode_comments = 1")
    # ACCELERATION CONTROL OFF -- 0 means "do not emit". This matters here:
    # PrusaSlicer would otherwise write an acceleration before every feature
    # (M204, or SET_VELOCITY_LIMIT under the klipper flavour) and overwrite the
    # ACCEL that CLAY_PRINT_LIMITS set to keep the auger inside its envelope.
    # Klipper's own configured acceleration, as capped by the clay macros, is the
    # only authority on this machine.
    for _a in ("default_acceleration", "perimeter_acceleration",
               "external_perimeter_acceleration", "infill_acceleration",
               "solid_infill_acceleration", "top_solid_infill_acceleration",
               "bridge_acceleration", "first_layer_acceleration",
               "travel_acceleration"):
        w("%s = 0" % _a)
    w("compatible_printers_condition = nozzle_diameter[0] == %g" % nz)
    w("")

# -- spiral vase siblings ---------------------------------------------------
# The usual clay part is a single continuous wall, and spiral vase is strictly
# better for it than a stack of closed loops: no seam, no layer-change stop, and
# no moment where the screw is asked to stop and restart against barrel
# pressure. Kept as separate profiles rather than the default because it cannot
# print anything with a lid, a hole, or more than one wall.
for nz in sorted(NOZZLES):
    lh, flh = NOZZLES[nz]
    w("[print:Clay %gmm nozzle - VASE]" % nz)
    w("inherits = Clay %gmm nozzle" % nz)
    w("spiral_vase = 1")
    w("bottom_solid_layers = 1")
    w("top_solid_layers = 0")
    w("perimeters = 1")
    w("fill_density = 0%")
    # Spiral vase raises Z continuously, so the layer-0-only hook still fires
    # exactly once. No other change is needed.
    w("compatible_printers_condition = nozzle_diameter[0] == %g" % nz)
    w("")


# -- filament profiles, one per working ratio -------------------------------
for ratio in RATIOS:
    cap = flow_ceiling(ratio)
    w("[filament:Clay @ 1-%d ratio]" % ratio)
    w("filament_type = FLEX")
    w("filament_diameter = %s" % FILAMENT_D)
    w("extrusion_multiplier = 1")
    w("filament_density = 1.8")
    w("filament_cost = 0")
    # THE AUGER'S CEILING, in the slicer's own units. At this ratio the screw
    # cannot pass more than this, so PrusaSlicer slows the toolhead until the
    # flow fits -- the same guarantee CLAY_PRINT_LIMITS gives on the machine,
    # applied at slicing time so the time estimate is honest too.
    w("filament_max_volumetric_speed = %.1f" % cap)
    w("temperature = 0")
    w("first_layer_temperature = 0")
    w("bed_temperature = 0")
    w("first_layer_bed_temperature = 0")
    w("cooling = 0")
    w("fan_always_on = 0")
    w("min_fan_speed = 0")
    w("max_fan_speed = 0")
    w("disable_fan_first_layers = 0")
    w("slowdown_below_layer_time = 0")
    w("min_print_speed = 0")
    w("filament_retract_length = 0")
    w("filament_notes = \"Plunger:Auger 1:%d -> the screw tops out at %.1f mm3/s "
      "(%.0f auger RPM). SET THE SAME RATIO on the clay panel during the "
      "print-start pause: a HIGHER ratio on the machine than the one sliced for "
      "will stall the auger.\"" % (ratio, cap, AUGER_MAX_RPM))
    w("")

# -- printer profiles, one per nozzle ---------------------------------------
for nz in sorted(NOZZLES):
    w("[printer:MANDEL Clay %gmm]" % nz)
    w("printer_technology = FFF")
    w("printer_model = MANDEL")
    w("printer_variant = %gmm" % nz)
    w("bed_shape = 0x0,%gx0,%gx%g,0x%g" % (BED_X, BED_X, BED_Y, BED_Y))
    w("max_print_height = %g" % MAX_Z)
    w("nozzle_diameter = %g" % nz)
    # Marlin, not klipper: Klipper's own documentation recommends the Marlin
    # flavour, and it is accepted by every PrusaSlicer version. A dedicated
    # klipper flavour is absent from older releases, and an unknown value makes
    # the whole bundle fail to import.
    # marlin, not klipper. Both are valid -- the shipped Voron profiles use
    # klipper -- but the klipper flavour makes PrusaSlicer emit
    # SET_VELOCITY_LIMIT for acceleration control, which is the exact command
    # CLAY_PRINT_LIMITS uses to hold the auger inside its envelope. marlin is
    # also accepted by every PrusaSlicer version, and Klipper's own
    # documentation recommends it.
    w("gcode_flavor = marlin")
    # Never write M201/M203/M204 machine limits into the file: Klipper's config
    # and the clay macros own those. time_estimate_only keeps them for the
    # preview only, which is what the numbers below are for.
    w("machine_limits_usage = time_estimate_only")
    # No EXCLUDE_OBJECT / M486: the machine has no [exclude_object] section, so
    # object labelling would abort the print on an unknown command.
    w("gcode_label_objects = disabled")
    w("thumbnails = ")
    w("use_relative_e_distances = 1")
    w("use_volumetric_e = 0")
    w("use_firmware_retraction = 0")
    w("single_extruder_multi_material = 0")
    # No retraction anywhere: there is nothing to retract. Pulling the plunger
    # back only decompresses the barrel, and the clay takes a long time to come
    # back. retract_before_travel is set past any travel this bed can contain.
    w("retract_length = 0")
    w("retract_lift = 0")
    w("retract_speed = 0")
    w("retract_before_travel = 1000")
    w("wipe = 0")
    w("z_offset = 0")
    w("silent_mode = 0")
    w("remaining_times = 0")
    w("machine_max_feedrate_x = %g" % TRAVEL)
    w("machine_max_feedrate_y = %g" % TRAVEL)
    w("machine_max_feedrate_z = %g" % TRAVEL)
    w("machine_max_acceleration_x = 500")
    w("machine_max_acceleration_y = 500")
    w("machine_max_acceleration_z = 200")
    w("machine_max_acceleration_extruding = 500")
    w("machine_max_acceleration_travel = 500")
    w("machine_max_jerk_x = 5")
    w("machine_max_jerk_y = 5")
    w("printer_notes = %s" % NL.join([
        "PRINTER_MODEL_MANDEL",
        "CLAY",
        "Do not remove the keywords above -- the print and filament profiles",
        "match on them.",
        "",
        "MANDEL, IISc clay printer. Plunger feeding an auger, no heaters.",
        "E IS VOLUMETRIC: 1 E mm = 1 mm3 of clay out of the nozzle, which is",
        "why filament_diameter is 1.128379 (cross-section exactly 1 mm2).",
        "filament_max_volumetric_speed is the AUGER's measured ceiling:",
        "50 mm3/s at a 1:20 Plunger:Auger ratio (307 RPM). Slice and print at",
        "the same ratio -- a higher ratio on the machine stalls the screw.",
        "Acceleration control is deliberately disabled; the machine owns it.",
    ]))
    w("start_gcode = %s" % START_GCODE)
    w("end_gcode = %s" % END_GCODE)
    w("layer_gcode = %s" % LAYER_GCODE)
    w("between_objects_gcode = ")
    w("toolchange_gcode = ")
    w("")

# Moonraker speaks the OctoPrint upload API, so host_type octoprint is correct.
# The API key is per-user and deliberately blank: fill it in PrusaSlicer, or add
# the workstation to Moonraker's trusted_clients and leave it empty.
w("[physical_printer:MANDEL]")
w("host_type = octoprint")
w("print_host = http://192.168.0.34")
w("printhost_apikey = ")
w("preset_names = " + ";".join("MANDEL Clay %gmm" % n for n in sorted(NOZZLES)))
w("")

w("[presets]")
w("print = Clay 3mm nozzle")
w("filament = Clay @ 1-20 ratio")
w("printer = MANDEL Clay 3mm")
w("")

open("MANDEL_clay.ini", "w", encoding="utf-8", newline="\n").write("\n".join(out))

print("MANDEL_clay.ini written")
print("filament_diameter %.6f mm -> cross-section %.6f mm2  (1 E mm = 1 mm3)"
      % (FILAMENT_D, math.pi / 4 * FILAMENT_D ** 2))
print()
print("flow ceiling by ratio: "
      + ",  ".join("1:%d = %.1f mm3/s" % (r, flow_ceiling(r)) for r in RATIOS))
print()
print("nozzle  layer   bead      max XY speed (mm/s) at ratio")
print("                mm2    " + "".join("   1:%-5d" % r for r in RATIOS))
for nz in sorted(NOZZLES):
    lh, _ = NOZZLES[nz]
    b = bead(nz, lh)
    print("%5g   %4s  %6.2f   " % (nz, lh, b)
          + "".join("  %7.2f" % (flow_ceiling(r) / b) for r in RATIOS))
