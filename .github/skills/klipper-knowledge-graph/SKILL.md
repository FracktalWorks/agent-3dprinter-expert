---
name: klipper-knowledge-graph
description: >
  Build and query a Graphify knowledge graph of Klipper debugging knowledge —
  scraped GitHub issues, Discourse forum threads, curated error references,
  and the Klipper source code itself. Answers "why does this error happen"
  and "what fixed this for others" from real-world evidence.
when_to_use: >
  User hits a Klipper/Moonraker/Mainsail/OctoPrint error that isn't resolved
  by the local error database; user asks how issues relate (error ↔ config ↔
  hardware); user wants the knowledge base refreshed from GitHub/forums; user
  asks where an error comes from in the Klipper source.
authority: write
cost_tier: 2
version: 0.1.0
---

# Klipper Knowledge Graph Skill

Turns community debugging knowledge into a queryable graph using
**Graphify** (https://github.com/Graphify-Labs/graphify).

> ⚠ **Graphify must be installed to properly use this agent's knowledge-graph
> features.** Install with `uv tool install graphifyy` (or
> `pipx install graphifyy`), then run `graphify install` to register the
> `/graphify` skill with your AI assistant. Without it, only the local
> curated references in `agent-data/` are available.

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/klipper_kb_scraper.py` | Scrape Klipper GitHub issues (Klipper3d/klipper, Arksine/moonraker, mainsail-crew/mainsail, OctoPrint/OctoPrint) and Discourse forums (klipper.discourse.group, community.octoprint.org) into a markdown corpus at `agent-data/knowledge-base/` |
| `scripts/graphify_kb.py` | Build/update/query/serve the Graphify knowledge graph over the corpus + curated `agent-data/` + optional Klipper source |
| `scripts/klipper_source_manager.py` | Maintain local clones of Klipper (official + FracktalWorks klipper_IDEX fork + Moonraker); locate the exact source line where any error is raised |

## Workflow

```bash
# 0. One-time: verify Graphify is installed
python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py --check

# 1. Populate the corpus (targeted scrapes are faster & richer than bulk)
python .github/skills/klipper-knowledge-graph/scripts/klipper_kb_scraper.py --source all --query "timer too close"
python .github/skills/klipper-knowledge-graph/scripts/klipper_kb_scraper.py --source all --max 200   # bulk: top threads
python .github/skills/klipper-knowledge-graph/scripts/klipper_kb_scraper.py --stats

# 2. (Optional but recommended) keep a local copy of the Klipper source
python .github/skills/klipper-knowledge-graph/scripts/klipper_source_manager.py --clone
python .github/skills/klipper-knowledge-graph/scripts/klipper_source_manager.py --clone --repo idex
python .github/skills/klipper-knowledge-graph/scripts/klipper_source_manager.py --locate-error "Timer too close"

# 3. Build the graph (needs an LLM key for doc extraction: ANTHROPIC_API_KEY etc.)
python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py --build
python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py --build --include-source

# 4. Query during debugging
python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py --query "MCU shutdown during long prints"
python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py --explain "TMC5160"
python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py --path "heater_bed" "ADC out of range"

# 5. (Optional) expose the graph as MCP tools for the assistant
python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py --serve
```

Once built, `graphify-out/graph.html` is an interactive visualization and
`graphify-out/GRAPH_REPORT.md` lists key concepts + suggested questions.
You can also use Graphify's own `/graphify` skill directly on this repo.

## Debugging routing

1. **Known error?** → `klipper_error_lookup.py --error "<message>"` (3d-printer-expert skill) — curated, instant, offline
2. **Not in DB / want evidence?** → `graphify_kb.py --query` — community knowledge graph
3. **Need the exact mechanism?** → `klipper_source_manager.py --locate-error` — read the raise site
4. **Graph stale/missing the topic?** → `klipper_kb_scraper.py --query "<topic>"` then `graphify_kb.py --update`

## Required Environment Variables

- `GITHUB_TOKEN` — optional, raises GitHub API rate limits (60/hr → 5000/hr)
- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` — one required by
  Graphify for extracting non-code documents into the graph
- `KLIPPER_SRC_DIR` — optional, override local Klipper clone location
  (default `.tmp/klipper-src/`)
- `GRAPHIFY_OUT_DIR` — optional, override graph output (default `graphify-out/`)

## Outputs

- `agent-data/knowledge-base/` — scraped markdown corpus (gitignored; regenerate anytime)
- `graphify-out/` — graph.json, graph.html, GRAPH_REPORT.md (gitignored)
- `.tmp/klipper-src/` — local source clones (gitignored)
