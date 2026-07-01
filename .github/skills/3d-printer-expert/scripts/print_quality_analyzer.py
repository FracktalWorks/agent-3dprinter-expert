#!/usr/bin/env python3
"""
Print Quality Analyzer — Matches user-described print symptoms to known
3D printing issues and provides targeted solutions. References the
comprehensive print_quality_issues.json database.

Correlates symptoms across:
  - Bed adhesion & first layer
  - Extrusion problems (under/over/inconsistent)
  - Surface quality (ringing, z-banding, blobs, scaring)
  - Structural issues (layer shift, delamination, weak infill)
  - Dimensional accuracy (size, elephant foot, bridging, overhangs)

Also provides material-specific guidance and slicer setting recommendations.

Usage:
    python print_quality_analyzer.py --symptom "stringing between towers"
    python print_quality_analyzer.py --symptom "first layer not sticking" --material PETG
    python print_quality_analyzer.py --symptom "waves around corners" --printer CoreXY
    python print_quality_analyzer.py --list-categories
    python print_quality_analyzer.py --category extrusion
    python print_quality_analyzer.py --material-guide ABS
    python print_quality_analyzer.py --tuning-guide
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


# ── Path to the issues database ─────────────────────────────────────────────
_DB_PATH = Path(__file__).parent.parent.parent.parent.parent / "agent-data" / "print_quality_issues.json"


def load_database() -> dict:
    """Load the print issues database."""
    if not _DB_PATH.exists():
        return {"error": f"Database not found: {_DB_PATH}"}
    try:
        return json.loads(_DB_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": f"Failed to load database: {e}"}


# ── Symptom-to-Issue Keyword Mapping ──────────────────────────────────────

SYMPTOM_KEYWORDS = {
    # Bed adhesion
    "not sticking": ["not_sticking_to_bed"],
    "wont stick": ["not_sticking_to_bed"],
    "adhesion": ["not_sticking_to_bed", "warping"],
    "first layer": ["not_sticking_to_bed", "elephant_foot"],
    "lifts off": ["not_sticking_to_bed", "warping"],
    "warping": ["warping"],
    "curling corners": ["warping"],
    "corner lift": ["warping"],

    # Extrusion
    "under extrusion": ["under_extrusion"],
    "underextrusion": ["under_extrusion"],
    "gaps": ["under_extrusion", "weak_infill", "pillowing"],
    "thin layers": ["under_extrusion"],
    "over extrusion": ["over_extrusion"],
    "overextrusion": ["over_extrusion"],
    "blobs": ["over_extrusion", "blobs_zits"],
    "bulging": ["over_extrusion", "elephant_foot"],
    "stringing": ["stringing_oozing"],
    "strings": ["stringing_oozing"],
    "oozing": ["stringing_oozing"],
    "hairs": ["stringing_oozing"],
    "clog": ["clogged_extruder"],
    "jammed": ["clogged_extruder"],
    "clicking extruder": ["clogged_extruder", "under_extrusion"],
    "grinding filament": ["clogged_extruder"],
    "inconsistent extrusion": ["inconsistent_extrusion"],
    "varying extrusion": ["inconsistent_extrusion"],

    # Surface quality
    "ringing": ["ringing_ghosting"],
    "ghosting": ["ringing_ghosting"],
    "echo": ["ringing_ghosting"],
    "ripples": ["ringing_ghosting"],
    "waves around corners": ["ringing_ghosting"],
    "oscillation": ["ringing_ghosting"],
    "layer lines": ["layer_lines"],
    "z banding": ["layer_lines"],
    "ribbed": ["layer_lines"],
    "horizontal lines": ["layer_lines"],
    "zits": ["blobs_zits"],
    "pimples": ["blobs_zits"],
    "bumps": ["blobs_zits"],
    "scars": ["scars_top_surface"],
    "nozzle drag": ["scars_top_surface"],
    "scratches top": ["scars_top_surface"],

    # Structural
    "layer shift": ["layer_shift"],
    "shifted layers": ["layer_shift"],
    "misaligned": ["layer_shift"],
    "stepped": ["layer_shift"],
    "layer separation": ["layer_separation"],
    "splitting": ["layer_separation"],
    "delamination": ["layer_separation"],
    "cracks": ["layer_separation"],
    "weak infill": ["weak_infill"],
    "stringy infill": ["weak_infill"],
    "infill gaps": ["weak_infill"],
    "top gaps": ["pillowing"],
    "pillowing": ["pillowing"],
    "rough top": ["pillowing", "scars_top_surface"],

    # Dimensional
    "wrong size": ["dimensional_inaccuracy"],
    "dimensional": ["dimensional_inaccuracy"],
    "holes too small": ["dimensional_inaccuracy"],
    "elephant foot": ["elephant_foot"],
    "bulging bottom": ["elephant_foot"],
    "bridging": ["poor_bridging"],
    "sagging bridges": ["poor_bridging"],
    "overhangs": ["curling_overhangs"],
    "curling overhangs": ["curling_overhangs"],
    "rough overhang": ["curling_overhangs"],
}


def match_symptoms(query: str, db: dict) -> list[dict]:
    """Match a natural language symptom description to known issues."""
    query_lower = query.lower()
    matched_ids = set()

    for keyword, issue_ids in SYMPTOM_KEYWORDS.items():
        if keyword in query_lower:
            matched_ids.update(issue_ids)

    # Also search directly in issue names and symptoms
    categories = db.get("categories", {})
    for cat_name, cat_data in categories.items():
        for issue in cat_data.get("issues", []):
            # Check issue name
            if query_lower in issue["name"].lower():
                matched_ids.add(issue["id"])
            # Check symptoms
            for symptom in issue.get("symptoms", []):
                if any(word in query_lower for word in symptom.lower().split()):
                    matched_ids.add(issue["id"])

            # Check causes
            for cause in issue.get("causes", []):
                detail = cause.get("detail", "")
                if any(word in query_lower for word in detail.lower().split()
                       if len(word) > 3):
                    matched_ids.add(issue["id"])

    # Retrieve full issue objects
    results = []
    for cat_name, cat_data in categories.items():
        for issue in cat_data.get("issues", []):
            if issue["id"] in matched_ids:
                results.append({
                    **issue,
                    "category": cat_name,
                    "category_label": cat_data["label"],
                })

    return results


def format_issue(issue: dict, db: dict, material: str = "") -> str:
    """Format a single issue for display."""
    lines = []
    lines.append(f"\n{'='*60}")
    lines.append(f"🔍 ISSUE: {issue['name']}")
    lines.append(f"   Category: {issue.get('category_label', issue.get('category', ''))}")
    lines.append(f"{'='*60}")

    if issue.get("symptoms"):
        lines.append("\n📋 Symptoms:")
        for s in issue["symptoms"]:
            lines.append(f"   • {s}")

    if issue.get("causes"):
        lines.append("\n🎯 Possible Causes:")
        for c in issue["causes"]:
            lines.append(f"   • [{c['factor']}] {c['detail']}")

    if issue.get("fixes"):
        lines.append("\n🔧 Fixes (try in order):")
        for i, f in enumerate(issue["fixes"], 1):
            lines.append(f"   {i}. {f}")

    if issue.get("klipper_commands"):
        lines.append("\n⚙️  Klipper Commands:")
        for cmd in issue["klipper_commands"]:
            lines.append(f"   → {cmd}")

    if issue.get("slicer_settings"):
        lines.append("\n🖨️  Check Slicer Settings:")
        for s in issue["slicer_settings"]:
            lines.append(f"   → {s}")

    # Material-specific guidance
    if material and material.upper() in db.get("material_reference", {}):
        mat = db["material_reference"][material.upper()]
        lines.append(f"\n🧪 Material-Specific ({material.upper()}):")
        lines.append(f"   Nozzle temp: {mat['nozzle_temp']}")
        lines.append(f"   Bed temp: {mat['bed_temp']}")
        lines.append(f"   Cooling: {mat['cooling']}")
        lines.append(f"   Retraction: {mat['retraction']}")
        lines.append(f"   Notes: {mat['notes']}")

    return "\n".join(lines)


def list_categories(db: dict) -> str:
    """List all diagnostic categories and their issues."""
    lines = ["\n📂 DIAGNOSTIC CATEGORIES", "="*60]
    for cat_name, cat_data in db.get("categories", {}).items():
        lines.append(f"\n## {cat_data['label']}")
        for issue in cat_data.get("issues", []):
            lines.append(f"   • {issue['name']} ({issue['id']})")
    return "\n".join(lines)


def show_category(db: dict, category: str) -> str:
    """Show all issues in a category."""
    cat_data = db.get("categories", {}).get(category)
    if not cat_data:
        # Try fuzzy match
        for k, v in db.get("categories", {}).items():
            if category.lower() in k.lower() or category.lower() in v["label"].lower():
                cat_data = v
                break
    if not cat_data:
        return f"Unknown category: {category}. Use --list-categories to see options."

    lines = [f"\n📂 {cat_data['label']}", "="*60]
    for issue in cat_data.get("issues", []):
        lines.append(format_issue(issue, db))
    return "\n".join(lines)


def show_material_guide(db: dict, material: str) -> str:
    """Show material-specific printing guide."""
    mat_data = db.get("material_reference", {}).get(material.upper())
    if not mat_data:
        available = ", ".join(db.get("material_reference", {}).keys())
        return f"Unknown material: {material}. Available: {available}"

    lines = [f"\n🧪 MATERIAL GUIDE: {material.upper()}", "="*60]
    for key, val in mat_data.items():
        if isinstance(val, list):
            lines.append(f"   {key}: {', '.join(val)}")
        else:
            lines.append(f"   {key}: {val}")
    return "\n".join(lines)


def show_tuning_guide(db: dict) -> str:
    """Show the Klipper calibration tuning sequence."""
    seq = db.get("klipper_tuning_sequence", [])
    lines = ["\n⚙️  KLIPPER CALIBRATION TUNING SEQUENCE", "="*60]
    lines.append("Follow these steps in order for optimal print quality:\n")
    for step in seq:
        lines.append(f"  Step {step['step']}: {step['name']}")
        lines.append(f"    Command: {step['command']}")
        lines.append(f"    Note: {step['note']}")
        lines.append("")

    # Slicer best practices
    sbp = db.get("slicer_best_practices", {})
    lines.append("\n📐 SLICER BEST PRACTICES")
    lines.append("-"*40)

    lh = sbp.get("layer_height", {})
    lines.append(f"\n  Layer Heights: {lh.get('description', '')}")
    lines.append(f"  Optimal: {', '.join(str(v) for v in lh.get('optimal_values_mm', []))} mm")

    nd = sbp.get("nozzle_diameter", {})
    lines.append(f"\n  Nozzle (0.4mm):")
    lines.append(f"    Max layer: {nd.get('max_layer_height', '')}")
    lines.append(f"    Extrusion width: {nd.get('min_extrusion_width', '')} to {nd.get('max_extrusion_width', '')}")

    sp = sbp.get("speed_ranges", {})
    lines.append("\n  Speed Ranges:")
    for k, v in sp.items():
        lines.append(f"    {k}: {v}")

    lines.append("\n💡 PRO TIP: Print a calibration cube after each change to verify improvement.")

    return "\n".join(lines)


def show_post_processing(db: dict) -> str:
    """Show post-processing techniques."""
    pp = db.get("post_processing", {})
    lines = ["\n🔨 POST-PROCESSING TECHNIQUES", "="*60]

    support = pp.get("support_removal", {})
    lines.append(f"\n  Support Removal: {', '.join(support.get('tools', []))}")
    for method in support.get("methods", []):
        lines.append(f"    - {method}")

    sanding = pp.get("sanding", {})
    lines.append(f"\n  Sanding: {' → '.join(sanding.get('grit_progression', []))}")
    lines.append(f"    Tip: {sanding.get('tips', '')}")

    painting = pp.get("priming_painting", {})
    lines.append(f"\n  Painting: {painting.get('primer', '')}")
    for step in painting.get("steps", []):
        lines.append(f"    - {step}")

    vapor = pp.get("vapor_smoothing", {})
    lines.append("\n  Vapor Smoothing:")
    for mat, solvent in vapor.get("materials", {}).items():
        lines.append(f"    {mat}: {solvent}")
    lines.append(f"    ⚠️  {vapor.get('safety', '')}")

    gluing = pp.get("gluing_assembly", {})
    lines.append("\n  Gluing / Assembly:")
    for mat, method in gluing.items():
        if mat.startswith("_"):
            continue
        lines.append(f"    {mat}: {method}")

    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="3D Print Quality Analyzer — Diagnose print issues from symptoms",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python print_quality_analyzer.py --symptom "stringing between towers"
  python print_quality_analyzer.py --symptom "first layer not sticking" --material PETG
  python print_quality_analyzer.py --category extrusion
  python print_quality_analyzer.py --list-categories
  python print_quality_analyzer.py --material-guide ABS
  python print_quality_analyzer.py --tuning-guide
  python print_quality_analyzer.py --post-processing
        """,
    )
    parser.add_argument("--symptom", "-s",
                        help="Describe the print quality issue (natural language)")
    parser.add_argument("--category", "-c",
                        help="Show all issues in a category (adhesion|extrusion|surface_quality|structural|dimensional)")
    parser.add_argument("--list-categories", action="store_true",
                        help="List all diagnostic categories and issues")
    parser.add_argument("--material", "-m",
                        help="Filter by material for material-specific guidance (PLA|PETG|ABS|ASA|TPU|NYLON|PC)")
    parser.add_argument("--material-guide",
                        help="Show complete material printing guide")
    parser.add_argument("--tuning-guide", action="store_true",
                        help="Show Klipper calibration tuning sequence")
    parser.add_argument("--post-processing", action="store_true",
                        help="Show post-processing techniques")
    args = parser.parse_args()

    db = load_database()
    if "error" in db:
        print(f"ERROR: {db['error']}", file=sys.stderr)
        sys.exit(1)

    if args.list_categories:
        print(list_categories(db))
    elif args.tuning_guide:
        print(show_tuning_guide(db))
    elif args.post_processing:
        print(show_post_processing(db))
    elif args.material_guide:
        print(show_material_guide(db, args.material_guide))
    elif args.category:
        print(show_category(db, args.category))
    elif args.symptom:
        # Match symptoms to issues
        matches = match_symptoms(args.symptom, db)
        if not matches:
            print(f"\n❓ No exact matches for: '{args.symptom}'")
            print("Try broader keywords or use --list-categories to browse issues.")
            print("\nClosest categories to explore:")
            # Suggest closest categories based on partial word match
            query_words = set(args.symptom.lower().split())
            for cat_name, cat_data in db.get("categories", {}).items():
                cat_words = set(cat_data["label"].lower().split())
                for issue in cat_data.get("issues", []):
                    issue_words = set(issue["name"].lower().split())
                    for symptom in issue.get("symptoms", []):
                        issue_words.update(symptom.lower().split())
                    if query_words & issue_words:
                        print(f"   → --category {cat_name} ({cat_data['label']})")
                        break
        else:
            for match in matches:
                print(format_issue(match, db, args.material or ""))

            if len(matches) > 1:
                print(f"\n📊 Found {len(matches)} matching issues.")
                print("Start with the most likely cause based on your specific symptoms.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
