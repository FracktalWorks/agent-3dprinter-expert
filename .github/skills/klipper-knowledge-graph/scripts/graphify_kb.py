#!/usr/bin/env python3
"""
Graphify Knowledge-Graph Manager — Builds and queries the Klipper debugging
knowledge graph using Graphify (https://github.com/Graphify-Labs/graphify).

⚠ Graphify must be installed for the knowledge-graph features of this agent
to work:

    uv tool install graphifyy      # recommended
    # or: pipx install graphifyy
    graphify install               # registers the /graphify skill with your AI assistant

The graph is built from:
  • agent-data/knowledge-base/  — scraped Klipper GitHub issues + forum threads
                                  (populate with klipper_kb_scraper.py)
  • agent-data/                 — curated references (error DB, hardware refs)
  • .tmp/klipper-src/           — local Klipper source clone (optional,
                                  populate with klipper_source_manager.py)

Usage:
    python graphify_kb.py --check                 # verify graphify installation
    python graphify_kb.py --build                 # build/refresh the knowledge graph
    python graphify_kb.py --build --include-source  # also ingest local Klipper source
    python graphify_kb.py --update                # incremental re-extract of changed files
    python graphify_kb.py --status                # graph stats (nodes/edges/files)
    python graphify_kb.py --query "why does Timer too close happen"
    python graphify_kb.py --explain "TMC5160"
    python graphify_kb.py --path "heater_bed" "ADC out of range"
    python graphify_kb.py --serve                 # start Graphify MCP server on the graph
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
CORPUS_DIR = REPO_ROOT / "agent-data" / "knowledge-base"
AGENT_DATA_DIR = REPO_ROOT / "agent-data"
KLIPPER_SRC_DIR = Path(os.environ.get("KLIPPER_SRC_DIR",
                       REPO_ROOT / ".tmp" / "klipper-src"))
GRAPH_OUT_DIR = Path(os.environ.get("GRAPHIFY_OUT_DIR", REPO_ROOT / "graphify-out"))
GRAPH_JSON = GRAPH_OUT_DIR / "graph.json"

INSTALL_HELP = """\
Graphify is NOT installed — the knowledge-graph features of this agent
require it. Install it with:

    uv tool install graphifyy        # recommended (isolated environment)
    # or:
    pipx install graphifyy

Then register the /graphify skill with your AI assistant (Claude Code,
Copilot, Cursor, ...):

    graphify install

Docs: https://github.com/Graphify-Labs/graphify
"""


def graphify_bin() -> str:
    return shutil.which("graphify") or ""


def require_graphify() -> str:
    binary = graphify_bin()
    if not binary:
        print(INSTALL_HELP, file=sys.stderr)
        sys.exit(3)
    return binary


def run_graphify(args: list, capture: bool = False) -> subprocess.CompletedProcess:
    binary = require_graphify()
    cmd = [binary] + args
    print(f"$ {' '.join(cmd)}", file=sys.stderr)
    return subprocess.run(cmd, cwd=str(REPO_ROOT), text=True,
                          capture_output=capture)


def action_check() -> None:
    binary = graphify_bin()
    if not binary:
        print(INSTALL_HELP, file=sys.stderr)
        sys.exit(3)
    version = subprocess.run([binary, "--version"], capture_output=True, text=True)
    print(f"✓ graphify found: {binary}")
    print(f"  version: {(version.stdout or version.stderr).strip()}")
    print(f"  corpus:  {CORPUS_DIR} "
          f"({'exists' if CORPUS_DIR.exists() else 'MISSING — run klipper_kb_scraper.py'})")
    print(f"  graph:   {GRAPH_JSON} "
          f"({'built' if GRAPH_JSON.exists() else 'not built yet — run --build'})")
    print(f"  klipper source: {KLIPPER_SRC_DIR} "
          f"({'present' if KLIPPER_SRC_DIR.exists() else 'absent (optional — klipper_source_manager.py --clone)'})")


def _build_targets(include_source: bool) -> list:
    targets = []
    if CORPUS_DIR.exists() and any(CORPUS_DIR.rglob("*.md")):
        targets.append(str(CORPUS_DIR))
    # Curated references (error DB, hardware reference, print quality DB)
    targets.append(str(AGENT_DATA_DIR))
    if include_source and KLIPPER_SRC_DIR.exists():
        targets.append(str(KLIPPER_SRC_DIR))
    return targets


def action_build(include_source: bool, update_only: bool, backend: str) -> None:
    if not CORPUS_DIR.exists() or not any(CORPUS_DIR.rglob("*.md")):
        print(f"NOTE: no scraped corpus at {CORPUS_DIR} — the graph will only "
              "contain curated agent-data. Populate it first with:\n"
              "  python .github/skills/klipper-knowledge-graph/scripts/"
              "klipper_kb_scraper.py --source all", file=sys.stderr)
    targets = _build_targets(include_source)
    GRAPH_OUT_DIR.mkdir(parents=True, exist_ok=True)
    for target in targets:
        args = ["extract", target, "--out", str(GRAPH_OUT_DIR)]
        if update_only:
            args.append("--update")
        if backend:
            args.extend(["--backend", backend])
        result = run_graphify(args)
        if result.returncode != 0:
            print(f"graphify extract failed for {target} "
                  f"(exit {result.returncode}). If this is a docs-only target, "
                  "make sure an LLM backend key is set (ANTHROPIC_API_KEY / "
                  "OPENAI_API_KEY / GEMINI_API_KEY).", file=sys.stderr)
            sys.exit(result.returncode)
    print(f"\n✓ Knowledge graph written to {GRAPH_OUT_DIR}/")
    print("  graph.html      — interactive visualization")
    print("  GRAPH_REPORT.md — key concepts and suggested questions")
    print("  graph.json      — queryable graph (also served via MCP)")


def action_status() -> None:
    if not GRAPH_JSON.exists():
        print(f"No graph at {GRAPH_JSON} — run --build first.")
        sys.exit(1)
    try:
        data = json.loads(GRAPH_JSON.read_text(encoding="utf-8"))
        nodes = data.get("nodes", data.get("entities", []))
        edges = data.get("edges", data.get("links", data.get("relationships", [])))
        print(f"Graph: {GRAPH_JSON}")
        print(f"  nodes: {len(nodes)}")
        print(f"  edges: {len(edges)}")
    except (json.JSONDecodeError, OSError) as e:
        print(f"Graph exists but could not be parsed: {e}")
    if CORPUS_DIR.exists():
        docs = len(list(CORPUS_DIR.rglob("*.md")))
        print(f"  corpus documents: {docs}")


def action_serve(transport: str, host: str, port: str) -> None:
    require_graphify()
    if not GRAPH_JSON.exists():
        print(f"No graph at {GRAPH_JSON} — run --build first.", file=sys.stderr)
        sys.exit(1)
    cmd = [sys.executable, "-m", "graphify.serve", str(GRAPH_JSON)]
    if transport == "http":
        cmd.extend(["--transport", "http", "--host", host, "--port", port])
    print(f"Starting Graphify MCP server: {' '.join(cmd)}", file=sys.stderr)
    print("Exposed MCP tools: query_graph, get_node, get_neighbors, shortest_path",
          file=sys.stderr)
    os.execvp(cmd[0], cmd)


def main():
    parser = argparse.ArgumentParser(description="Build/query the Klipper knowledge graph via Graphify")
    parser.add_argument("--check", action="store_true", help="Verify graphify installation + graph state")
    parser.add_argument("--build", action="store_true", help="Build/refresh the knowledge graph")
    parser.add_argument("--update", action="store_true", help="Incremental re-extract of changed files")
    parser.add_argument("--include-source", action="store_true",
                        help="Also ingest the local Klipper source clone into the graph")
    parser.add_argument("--backend", default="",
                        help="LLM backend for doc extraction (anthropic|openai|gemini)")
    parser.add_argument("--status", action="store_true", help="Show graph statistics")
    parser.add_argument("--query", default="", help="Semantic query against the graph")
    parser.add_argument("--explain", default="", help="Explain a single concept/entity")
    parser.add_argument("--path", nargs=2, metavar=("NODE_A", "NODE_B"),
                        help="Trace the connection between two entities")
    parser.add_argument("--serve", action="store_true", help="Start the Graphify MCP server")
    parser.add_argument("--transport", default="stdio", choices=["stdio", "http"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default="8765")
    args = parser.parse_args()

    if args.check:
        action_check()
    elif args.build or args.update:
        action_build(args.include_source, args.update and not args.build, args.backend)
    elif args.status:
        action_status()
    elif args.query:
        sys.exit(run_graphify(["query", args.query]).returncode)
    elif args.explain:
        sys.exit(run_graphify(["explain", args.explain]).returncode)
    elif args.path:
        sys.exit(run_graphify(["path", args.path[0], args.path[1]]).returncode)
    elif args.serve:
        action_serve(args.transport, args.host, args.port)
    else:
        action_check()


if __name__ == "__main__":
    main()
