#!/usr/bin/env python3
"""Prove MANDEL_clay.ini actually slices, and that the G-code suits Klipper.

A config bundle can be syntactically fine and still be wrong in ways that only
show up in the output: an unknown key that PrusaSlicer silently drops, an
acceleration that reappears and fights the clay speed cap, E in the wrong unit.
So this does not inspect the bundle -- it runs the real slicer over a real
object and audits the G-code that comes out.

    python validate.py [--nozzle 3] [--ratio 20] [--vase]

Needs PrusaSlicer installed. Writes into ./_validate/ (gitignored).
"""
import argparse
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "_validate")
BUNDLE = os.path.join(HERE, "MANDEL_clay.ini")

CANDIDATES = [
    r"C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer-console.exe",
    r"C:\Program Files\PrusaSlicer\prusa-slicer-console.exe",
    "/usr/bin/prusa-slicer",
    "/usr/local/bin/prusa-slicer",
    "prusa-slicer",
]


def find_slicer():
    for c in CANDIDATES:
        if os.path.exists(c):
            return c
    return None


def parse_bundle(path):
    """Return {section_name: {key: value}} for a PrusaSlicer config bundle."""
    out, cur = {}, None
    for raw in open(path, encoding="utf-8"):
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("[") and line.rstrip().endswith("]"):
            cur = line.strip()[1:-1]
            out[cur] = {}
        elif cur is not None and "=" in line:
            k, _, v = line.partition("=")
            out[cur][k.strip()] = v.strip()
    return out


def resolve(sections, name):
    """Flatten one section, following `inherits` within the same kind."""
    kind = name.split(":", 1)[0]
    sec = dict(sections[name])
    parent = sec.pop("inherits", None)
    if parent:
        base = resolve(sections, "%s:%s" % (kind, parent.strip()))
        base.update(sec)
        return base
    return sec


def cylinder_stl(path, dia=50.0, height=40.0, facets=64):
    """A plain cylinder centred on the origin -- the shape this machine prints."""
    r, tris = dia / 2.0, []

    def ang(i):
        a = 2 * math.pi * i / facets
        return r * math.cos(a), r * math.sin(a)

    for i in range(facets):
        x0, y0 = ang(i)
        x1, y1 = ang(i + 1)
        tris.append(((x0, y0, 0), (x1, y1, 0), (x1, y1, height)))
        tris.append(((x0, y0, 0), (x1, y1, height), (x0, y0, height)))
        tris.append(((0, 0, 0), (x1, y1, 0), (x0, y0, 0)))            # bottom
        tris.append(((0, 0, height), (x0, y0, height), (x1, y1, height)))  # top
    with open(path, "w", encoding="ascii") as f:
        f.write("solid cyl\n")
        for t in tris:
            f.write(" facet normal 0 0 0\n  outer loop\n")
            for v in t:
                f.write("   vertex %.4f %.4f %.4f\n" % v)
            f.write("  endloop\n endfacet\n")
        f.write("endsolid cyl\n")


CHECKS_MUST = [
    ("CLAY_PRINT_START", r"^CLAY_PRINT_START X=\d+ Y=\d+"),
    ("CLAY_RESYNC", r"^CLAY_RESYNC"),
    ("CLAY_PRINT_LIMITS with a numeric BEAD", r"^CLAY_PRINT_LIMITS BEAD=[\d.]+"),
    ("CLAY_PRINT_END", r"^CLAY_PRINT_END"),
    ("relative E (M83)", r"^M83"),
    ("purge line (single-axis X move with E)", r"^G1 X[\d.]+ E[\d.]+"),
    ("lift clear after the purge", r"^G1 Z[\d.]+ F1200"),
    ("end lift clear of the part", r"^G1 Z[\d.]+ F600$"),
]
# Anything here in the output means a setting did not take, and the clay speed
# cap would be overwritten mid-print.
CHECKS_MUST_NOT = [
    ("M204 acceleration", r"^M204"),
    ("SET_VELOCITY_LIMIT", r"^SET_VELOCITY_LIMIT"),
    ("M201 machine accel limits", r"^M201"),
    ("M203 machine feedrate limits", r"^M203"),
    ("M200 volumetric mode", r"^M200"),
    ("temperature command", r"^M10[49]\s+S[1-9]"),
    ("fan on", r"^M106\s+S[1-9]"),
    ("retraction (negative E)", r"^G1\s+E-"),
    # An expression that failed to evaluate is emitted verbatim, braces and all,
    # and Klipper would reject the line mid-print.
    ("unresolved placeholder", r"[{}]"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nozzle", default="3")
    ap.add_argument("--ratio", default="20")
    ap.add_argument("--vase", action="store_true")
    a = ap.parse_args()

    slicer = find_slicer()
    if not slicer:
        sys.exit("PrusaSlicer not found. Install it, or add its path to CANDIDATES.")
    os.makedirs(WORK, exist_ok=True)

    sections = parse_bundle(BUNDLE)
    pr = "print:Clay %smm nozzle%s" % (a.nozzle, " - VASE" if a.vase else "")
    fl = "filament:Clay @ 1-%s ratio" % a.ratio
    pt = "printer:MANDEL Clay %smm" % a.nozzle
    for n in (pr, fl, pt):
        if n not in sections:
            sys.exit("no such section: [%s]" % n)

    flat = {}
    for n in (pr, fl, pt):
        flat.update(resolve(sections, n))
    # Bundle-only bookkeeping that a flat config must not carry.
    for k in ("compatible_printers_condition", "inherits", "default_print_profile"):
        flat.pop(k, None)

    cfg = os.path.join(WORK, "flat.ini")
    with open(cfg, "w", encoding="utf-8", newline="\n") as f:
        for k in sorted(flat):
            f.write("%s = %s\n" % (k, flat[k]))

    stl = os.path.join(WORK, "cylinder.stl")
    cylinder_stl(stl)
    gcode = os.path.join(WORK, "out.gcode")
    if os.path.exists(gcode):
        os.remove(gcode)

    print("slicer   : %s" % slicer)
    print("profiles : %s + %s + %s" % (pr, fl, pt))
    print("flat cfg : %d keys\n" % len(flat))

    cmd = [slicer, "--export-gcode", "--load", cfg,
           "--center", "100,100", "--output", gcode, stl]
    p = subprocess.run(cmd, capture_output=True, text=True)
    blob = (p.stdout or "") + (p.stderr or "")
    for line in blob.splitlines():
        if line.strip():
            print("  slicer: %s" % line.strip())

    if not os.path.exists(gcode):
        print("\nFAILED: no G-code produced.")
        return 1

    lines = open(gcode, encoding="utf-8", errors="replace").read().splitlines()
    body = [l.strip() for l in lines if l.strip() and not l.strip().startswith(";")]
    print("\n%d G-code lines\n" % len(lines))

    bad = 0
    for label, pat in CHECKS_MUST:
        hits = [l for l in body if re.search(pat, l)]
        ok = bool(hits)
        bad += not ok
        print("  [%s] %-38s %s" % ("ok" if ok else "MISSING", label,
                                   hits[0][:60] if hits else ""))
    print()
    for label, pat in CHECKS_MUST_NOT:
        hits = [l for l in body if re.search(pat, l)]
        bad += bool(hits)
        print("  [%s] %-38s %s" % ("ok" if not hits else "PRESENT", "no " + label,
                                   hits[0][:60] if hits else ""))

    # E must be mm3. A 3 mm nozzle at 2 mm layer is 5.14 mm3 per mm of travel,
    # so a ~1 mm segment carries E~5, not E~0.05. Getting this wrong by the
    # filament-area factor is the single most likely silent failure.
    # Sample from AFTER the second layer change, so the measurement is the main
    # bead and not the (deliberately thinner) first layer.
    started, es = False, []
    seen_change = 0
    for l in body:
        if l.startswith("G92 E0"):
            seen_change += 1
            started = seen_change >= 2
        if not started:
            continue
        m = re.match(r"^G1 X([-\d.]+) Y([-\d.]+) E([\d.]+)", l)
        if m:
            es.append((float(m.group(3)), float(m.group(1)), float(m.group(2))))
    print()
    if len(es) > 3:
        # per-mm flow from consecutive extruding moves
        rates = []
        for i in range(1, min(len(es), 400)):
            e, x, y = es[i]
            _, px, py = es[i - 1]
            d = math.hypot(x - px, y - py)
            if d > 0.2:
                rates.append(e / d)
            if len(rates) > 50:
                break
        med = sorted(rates)[len(rates) // 2] if rates else 0.0
        want = (float(flat["extrusion_width"]) * float(flat["layer_height"])
                - float(flat["layer_height"]) ** 2 * (1 - math.pi / 4))
        first = (float(flat["extrusion_width"]) * float(flat["first_layer_height"])
                 - float(flat["first_layer_height"]) ** 2 * (1 - math.pi / 4))
        # Spiral vase ramps Z continuously, so a sampled bead legitimately lands
        # anywhere between the first-layer and main values.
        lo, hi = min(first, want) * 0.9, max(first, want) * 1.1
        ok = lo <= med <= hi
        bad += not ok
        print("  [%s] %.3f mm3 per mm of travel; expected %.2f (main) or %.2f"
              " (first layer)" % ("ok" if ok else "WRONG UNIT", med, want, first))
        if not ok:
            print("       ~%.2f would mean E is linear mm, not mm3 -- the"
                  " volumetric filament diameter is not in effect"
                  % (want / 12.566))
    else:
        print("  no extruding XY moves found -- check the profile")
        bad += 1

    # The purge must descend somewhere OTHER than the park position, or the ooze
    # from the pause lands in the middle of the part and the nozzle drags out
    # through it. Check the first Z-to-first-layer move is preceded by a travel.
    park = None
    for l in body:
        m = re.match(r"^CLAY_PRINT_START X=([\d.]+) Y=([\d.]+)", l)
        if m:
            park = (float(m.group(1)), float(m.group(2)))
            break
    first_xy = None
    for l in body:
        m = re.match(r"^G1 X([\d.]+) Y([\d.]+) F", l)
        if m:
            first_xy = (float(m.group(1)), float(m.group(2)))
            break
    if park and first_xy:
        moved = math.hypot(first_xy[0] - park[0], first_xy[1] - park[1]) > 10
        bad += not moved
        print("  [%s] descends clear of the park point (%.0f,%.0f -> %.0f,%.0f)"
              % ("ok" if moved else "DRAGS", park[0], park[1],
                 first_xy[0], first_xy[1]))

    # THE FUNCTIONAL CHECK: no move may ask for more flow than the auger can
    # pass. Measured from the G-code itself -- E per move, the distance covered,
    # and the feedrate in force -- rather than trusted from the profile. This is
    # what proves filament_max_volumetric_speed actually did something.
    ceiling = float(flat.get("filament_max_volumetric_speed", 0)) or None
    if ceiling:
        feed, worst, worst_line, px, py = None, 0.0, "", None, None
        for l in body:
            m = re.match(r"^G1 F([\d.]+)\s*$", l)
            if m:
                feed = float(m.group(1)) / 60.0
                continue
            m = re.match(r"^G1 X([-\d.]+) Y([-\d.]+)(?: Z[-\d.]+)?"
                         r" E([\d.]+)(?: F([\d.]+))?", l)
            if not m:
                continue
            if m.group(4):
                feed = float(m.group(4)) / 60.0
            x, y, e = float(m.group(1)), float(m.group(2)), float(m.group(3))
            if px is not None and feed:
                d = math.hypot(x - px, y - py)
                if d > 0.05 and e / d * feed > worst:
                    worst, worst_line = e / d * feed, l
            px, py = x, y
        over = worst > ceiling * 1.02
        bad += over
        print()
        print("  [%s] peak flow %.2f mm3/s against a %.1f mm3/s ceiling (%.0f%%)"
              % ("OVER" if over else "ok", worst, ceiling, worst / ceiling * 100))
        if over:
            print("       worst move: %s" % worst_line[:80])

    print("\n%s" % ("ALL CHECKS PASSED" if not bad else "%d PROBLEM(S)" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
