#!/usr/bin/env python3
"""
Klipper Error Lookup — Matches a raw Klipper error message (from klippy.log,
the UI, or a user report) against the comprehensive error reference database
(agent-data/klipper_error_reference.json) and explains exactly why the error
occurs, where it's raised in the Klipper source, and how to fix it.

Covers MCU communication/shutdown errors, TMC driver flags (ot, s2ga, uv_cp,
open-load, GSTAT), thermal watchdog errors, homing/probing failures, extrusion
guards, CAN bus faults, and config/startup errors.

Usage:
    python klipper_error_lookup.py --error "MCU 'mcu' shutdown: Timer too close"
    python klipper_error_lookup.py --error "TMC 'stepper_x' reports error: ... uv_cp=1"
    python klipper_error_lookup.py --search thermistor
    python klipper_error_lookup.py --category tmc_drivers
    python klipper_error_lookup.py --list
    python klipper_error_lookup.py --error "..." --json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
DB_PATH = REPO_ROOT / "agent-data" / "klipper_error_reference.json"


def load_db() -> dict:
    if not DB_PATH.exists():
        print(f"ERROR: error database not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)
    return json.loads(DB_PATH.read_text(encoding="utf-8"))


def iter_errors(db: dict):
    for cat_name, cat in db.get("categories", {}).items():
        for err in cat.get("errors", []):
            yield cat_name, err


def match_error(db: dict, message: str) -> list:
    """Return (category, error, score) matches for a raw error message."""
    msg = message.lower()
    matches = []
    for cat_name, err in iter_errors(db):
        score = 0
        for pattern in err.get("patterns", []):
            if pattern.lower() in msg:
                # Longer patterns are more specific matches
                score = max(score, len(pattern))
        if score:
            matches.append((cat_name, err, score))
    matches.sort(key=lambda m: -m[2])
    return matches


def print_error(cat_name: str, err: dict) -> None:
    print(f"\n══ {err['id']}  [{cat_name}] ══")
    print(f"  Example:   {err.get('example', '')}")
    print(f"  Raised in: {err.get('raised_in', '?')}")
    print(f"\n  WHY IT OCCURS:\n    {err.get('why', '')}")
    if err.get("common_causes"):
        print("\n  Common causes:")
        for c in err["common_causes"]:
            print(f"    • {c}")
    if err.get("diagnostics"):
        print("\n  Diagnostics:")
        for d in err["diagnostics"]:
            print(f"    → {d}")
    if err.get("fixes"):
        print("\n  Fixes:")
        for f in err["fixes"]:
            print(f"    ✓ {f}")


def main():
    parser = argparse.ArgumentParser(description="Look up Klipper errors in the reference database")
    parser.add_argument("--error", default="", help="Raw error message to identify")
    parser.add_argument("--search", default="", help="Free-text search across the database")
    parser.add_argument("--category", default="", help="Show all errors in a category")
    parser.add_argument("--list", action="store_true", help="List all categories and error IDs")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args()

    db = load_db()

    if args.list:
        for cat_name, cat in db.get("categories", {}).items():
            print(f"\n{cat_name}: {cat.get('description', '')}")
            for err in cat.get("errors", []):
                print(f"  • {err['id']:<28} {err.get('patterns', [''])[0]}")
        return

    if args.category:
        cat = db.get("categories", {}).get(args.category)
        if not cat:
            print(f"Unknown category '{args.category}'. "
                  f"Options: {', '.join(db.get('categories', {}))}", file=sys.stderr)
            sys.exit(1)
        if args.json:
            print(json.dumps(cat, indent=2))
            return
        for err in cat.get("errors", []):
            print_error(args.category, err)
        return

    if args.search:
        needle = args.search.lower()
        hits = []
        for cat_name, err in iter_errors(db):
            haystack = json.dumps(err).lower()
            if needle in haystack:
                hits.append((cat_name, err))
        if args.json:
            print(json.dumps([{"category": c, **e} for c, e in hits], indent=2))
            return
        if not hits:
            print(f"No entries mention '{args.search}'. Try klipper_source_manager.py "
                  "--grep or graphify_kb.py --query for wider coverage.")
            sys.exit(1)
        for cat_name, err in hits:
            print_error(cat_name, err)
        return

    if args.error:
        matches = match_error(db, args.error)
        if args.json:
            print(json.dumps([{"category": c, "score": s, **e}
                              for c, e, s in matches[:3]], indent=2))
            return
        if not matches:
            print("No database match for this message. Next steps:")
            print("  1. klipper_source_manager.py --locate-error \"<distinctive fragment>\"")
            print("  2. graphify_kb.py --query \"<the error>\" (knowledge graph)")
            print("  3. klipper_kb_scraper.py --query \"<the error>\" (scrape fresh reports)")
            sys.exit(1)
        best = matches[0]
        print_error(best[0], best[1])
        if len(matches) > 1:
            print("\n  Other possible matches: "
                  + ", ".join(m[1]["id"] for m in matches[1:4]))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
