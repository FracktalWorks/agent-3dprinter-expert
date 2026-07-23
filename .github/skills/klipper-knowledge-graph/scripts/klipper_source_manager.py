#!/usr/bin/env python3
"""
Klipper Source Manager — Maintains a local clone of the Klipper codebase
(and the FracktalWorks klipper_IDEX production fork) so the agent can answer
"where does this error come from and exactly why is it raised?" from the
actual source, offline, and feed the code into the Graphify knowledge graph.

Klipper error messages are string literals in the source: MCU shutdown
reasons live in src/*.c (sched.c, adccmds.c, stepper.c, ...), host-side
errors in klippy/*.py and klippy/extras/*.py (mcu.py, verify_heater.py,
tmc.py, homing.py, ...). Grepping the clone finds the exact raise site and
the surrounding logic that explains the root cause.

Usage:
    python klipper_source_manager.py --clone                    # official Klipper3d/klipper
    python klipper_source_manager.py --clone --repo idex        # FracktalWorks/klipper_IDEX fork
    python klipper_source_manager.py --update                   # git pull all local clones
    python klipper_source_manager.py --status
    python klipper_source_manager.py --locate-error "Timer too close"
    python klipper_source_manager.py --grep "TRINAMIC_DRIVERS" --context 5
    python klipper_source_manager.py --show klippy/extras/verify_heater.py
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SRC_BASE = Path(os.environ.get("KLIPPER_SRC_DIR", REPO_ROOT / ".tmp" / "klipper-src"))

REPOS = {
    "klipper": "https://github.com/Klipper3d/klipper.git",
    "idex": "https://github.com/FracktalWorks/klipper_IDEX.git",
    "moonraker": "https://github.com/Arksine/moonraker.git",
}

# Where error strings live, in search-priority order
ERROR_HOTSPOTS = [
    "klippy/mcu.py",              # MCU connect/comms errors, shutdown handling
    "klippy/klippy.py",           # startup/state errors
    "klippy/serialhdl.py",        # serial/CAN connection errors
    "klippy/stepper.py",
    "klippy/toolhead.py",         # Move out of range, lookahead
    "klippy/gcode.py",
    "klippy/extras/tmc.py",       # TMC driver error decoding (drv_err, GSTAT)
    "klippy/extras/tmc2130.py",
    "klippy/extras/tmc2209.py",
    "klippy/extras/tmc5160.py",
    "klippy/extras/tmc_uart.py",
    "klippy/extras/verify_heater.py",  # 'not heating at expected rate'
    "klippy/extras/heaters.py",
    "klippy/extras/adc_temperature.py",
    "klippy/extras/homing.py",
    "klippy/extras/probe.py",
    "klippy/extras/bltouch.py",
    "src/",                       # MCU firmware shutdown strings (C)
]


def _run(cmd: list, cwd: Path = None, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                          capture_output=capture, text=True)


def clone_dir(repo_key: str) -> Path:
    return SRC_BASE / repo_key


def action_clone(repo_key: str, shallow: bool) -> None:
    url = REPOS.get(repo_key)
    if not url:
        print(f"Unknown repo key '{repo_key}'. Options: {', '.join(REPOS)}", file=sys.stderr)
        sys.exit(1)
    dest = clone_dir(repo_key)
    if (dest / ".git").exists():
        print(f"✓ {repo_key} already cloned at {dest} — running update instead")
        action_update(repo_key)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "clone"]
    if shallow:
        cmd.extend(["--depth", "1"])
    cmd.extend([url, str(dest)])
    print(f"$ {' '.join(cmd)}")
    result = _run(cmd, capture=False)
    if result.returncode != 0:
        print(f"Clone failed (exit {result.returncode})", file=sys.stderr)
        sys.exit(result.returncode)
    print(f"✓ {repo_key} cloned to {dest}")
    print("Tip: include it in the knowledge graph with\n"
          "  python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py "
          "--build --include-source")


def action_update(repo_key: str = "") -> None:
    keys = [repo_key] if repo_key else list(REPOS)
    for key in keys:
        dest = clone_dir(key)
        if not (dest / ".git").exists():
            if repo_key:
                print(f"{key}: not cloned (run --clone --repo {key})")
            continue
        result = _run(["git", "pull", "--ff-only"], cwd=dest)
        print(f"{key}: {(result.stdout or result.stderr).strip()}")


def action_status() -> None:
    print(f"Source base: {SRC_BASE}")
    for key, url in REPOS.items():
        dest = clone_dir(key)
        if (dest / ".git").exists():
            head = _run(["git", "log", "-1", "--format=%h %cs %s"], cwd=dest)
            branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=dest)
            print(f"  ✓ {key:<10} [{branch.stdout.strip()}] {head.stdout.strip()}")
        else:
            print(f"  ✗ {key:<10} not cloned ({url})")


def _grep(pattern: str, root: Path, context: int, fixed: bool) -> str:
    if (root / ".git").exists():
        cmd = ["git", "grep", "-n", "-I"]
        if fixed:
            cmd.append("-F")
        if context:
            cmd.extend(["-C", str(context)])
        cmd.append(pattern)
        result = _run(cmd, cwd=root)
        return result.stdout
    return ""


def action_locate_error(message: str, context: int) -> None:
    """Find where an error message is raised and show the surrounding code."""
    found_any = False
    for key in REPOS:
        root = clone_dir(key)
        if not (root / ".git").exists():
            continue
        out = _grep(message, root, context, fixed=True)
        if not out:
            # Error strings are often split/formatted — retry with the longest words
            words = [w for w in message.split() if len(w) > 3][:3]
            if words:
                out = _grep(" ".join(words), root, context, fixed=True)
        if out:
            found_any = True
            print(f"\n══ {key} ({root}) ══")
            # Prioritize hotspot files in output ordering
            lines = out.splitlines()
            hot = [l for l in lines if any(h in l for h in ERROR_HOTSPOTS)]
            rest = [l for l in lines if l not in hot]
            print("\n".join((hot + rest)[:120]))
    if not found_any:
        cloned = [k for k in REPOS if (clone_dir(k) / ".git").exists()]
        if not cloned:
            print("No local Klipper source found. Clone it first:\n"
                  "  python klipper_source_manager.py --clone", file=sys.stderr)
            sys.exit(1)
        print(f"'{message}' not found verbatim in {', '.join(cloned)}. "
              "Error strings are sometimes built dynamically — try --grep "
              "with a distinctive fragment (e.g. --grep 'too close').")


def action_show(rel_path: str, repo_key: str) -> None:
    root = clone_dir(repo_key)
    target = root / rel_path
    if not target.exists():
        print(f"{target} not found. Is {repo_key} cloned?", file=sys.stderr)
        sys.exit(1)
    print(target.read_text(encoding="utf-8", errors="replace"))


def main():
    parser = argparse.ArgumentParser(description="Manage and search local Klipper source clones")
    parser.add_argument("--clone", action="store_true", help="Clone the source repo")
    parser.add_argument("--repo", default="klipper", choices=list(REPOS),
                        help="Which repo (klipper|idex|moonraker)")
    parser.add_argument("--full", action="store_true", help="Full clone instead of shallow")
    parser.add_argument("--update", action="store_true", help="git pull all local clones")
    parser.add_argument("--status", action="store_true", help="Show clone state")
    parser.add_argument("--locate-error", default="",
                        help="Find where an error message is raised in the source")
    parser.add_argument("--grep", default="", help="Search pattern across the source")
    parser.add_argument("--context", type=int, default=3, help="Context lines for grep/locate")
    parser.add_argument("--show", default="", help="Print a file from the clone (relative path)")
    args = parser.parse_args()

    if args.clone:
        action_clone(args.repo, shallow=not args.full)
    elif args.update:
        action_update()
    elif args.status:
        action_status()
    elif args.locate_error:
        action_locate_error(args.locate_error, args.context)
    elif args.grep:
        for key in REPOS:
            root = clone_dir(key)
            if (root / ".git").exists():
                out = _grep(args.grep, root, args.context, fixed=False)
                if out:
                    print(f"\n══ {key} ══")
                    print("\n".join(out.splitlines()[:150]))
    elif args.show:
        action_show(args.show, args.repo)
    else:
        action_status()


if __name__ == "__main__":
    main()
