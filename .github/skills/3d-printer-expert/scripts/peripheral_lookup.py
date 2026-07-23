#!/usr/bin/env python3
"""
Peripheral Lookup — Queries the Klipper peripherals compatibility reference
(agent-data/klipper_peripherals_reference.json): motor drivers, temperature
sensors, hotends, heaters, probes, extruders, accelerometers, filament
sensors, endstops, fans, CAN toolhead boards — and the combination rules
that govern which permutations work together.

Usage:
    python peripheral_lookup.py --list
    python peripheral_lookup.py --category motor_drivers
    python peripheral_lookup.py --name "TMC5160"
    python peripheral_lookup.py --search "PT1000"
    python peripheral_lookup.py --combos                 # all combination rules
    python peripheral_lookup.py --combos sensorless      # rules mentioning a term
    python peripheral_lookup.py --name "BLTouch" --json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
DB_PATH = REPO_ROOT / "agent-data" / "klipper_peripherals_reference.json"


def load_db() -> dict:
    if not DB_PATH.exists():
        print(f"ERROR: peripherals database not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)
    return json.loads(DB_PATH.read_text(encoding="utf-8"))


def print_entry(cat_name: str, entry: dict) -> None:
    print(f"\n══ {entry.get('name', entry.get('rule', '?'))}  [{cat_name}] ══")
    for key, val in entry.items():
        if key in ("name", "rule"):
            continue
        label = key.replace("_", " ")
        if isinstance(val, list):
            print(f"  {label}:")
            for item in val:
                print(f"    • {item}")
        else:
            print(f"  {label}: {val}")


def iter_entries(db: dict):
    for cat_name, cat in db.get("categories", {}).items():
        for entry in cat.get("entries", []):
            yield cat_name, entry


def main():
    parser = argparse.ArgumentParser(description="Klipper peripherals & combinations lookup")
    parser.add_argument("--list", action="store_true", help="List categories and entry names")
    parser.add_argument("--category", default="", help="Show all entries in a category")
    parser.add_argument("--name", default="", help="Look up a peripheral by (partial) name")
    parser.add_argument("--search", default="", help="Free-text search across the database")
    parser.add_argument("--combos", nargs="?", const="", default=None,
                        help="Show combination rules (optionally filtered by a term)")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args()

    db = load_db()
    categories = db.get("categories", {})

    if args.list:
        for cat_name, cat in categories.items():
            print(f"\n{cat_name}: {cat.get('description', '')}")
            for entry in cat.get("entries", []):
                print(f"  • {entry.get('name', entry.get('rule', '?'))}")
        return

    if args.combos is not None:
        rules = categories.get("combination_rules", {}).get("entries", [])
        if args.combos:
            needle = args.combos.lower()
            rules = [r for r in rules if needle in json.dumps(r).lower()]
        if args.json:
            print(json.dumps(rules, indent=2))
            return
        if not rules:
            print(f"No combination rules mention '{args.combos}'.")
            sys.exit(1)
        for rule in rules:
            print(f"\n══ {rule['rule']} ══")
            print(f"  {rule['statement']}")
        return

    if args.category:
        cat = categories.get(args.category)
        if not cat:
            print(f"Unknown category '{args.category}'. "
                  f"Options: {', '.join(categories)}", file=sys.stderr)
            sys.exit(1)
        if args.json:
            print(json.dumps(cat, indent=2))
            return
        print(f"{args.category}: {cat.get('description', '')}")
        for entry in cat.get("entries", []):
            print_entry(args.category, entry)
        return

    if args.name:
        needle = args.name.lower()
        hits = [(c, e) for c, e in iter_entries(db)
                if needle in e.get("name", e.get("rule", "")).lower()]
        if args.json:
            print(json.dumps([{"category": c, **e} for c, e in hits], indent=2))
            return
        if not hits:
            print(f"No peripheral named like '{args.name}'. Try --search or --list.")
            sys.exit(1)
        for cat_name, entry in hits:
            print_entry(cat_name, entry)
        return

    if args.search:
        needle = args.search.lower()
        hits = [(c, e) for c, e in iter_entries(db)
                if needle in json.dumps(e).lower()]
        if args.json:
            print(json.dumps([{"category": c, **e} for c, e in hits], indent=2))
            return
        if not hits:
            print(f"Nothing mentions '{args.search}'. Broader coverage: "
                  "graphify_kb.py --query, or klipper_docs.py --search.")
            sys.exit(1)
        for cat_name, entry in hits:
            print_entry(cat_name, entry)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
