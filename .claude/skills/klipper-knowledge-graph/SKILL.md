---
name: klipper-knowledge-graph
description: >
  Build and query a Graphify knowledge graph of Klipper debugging knowledge —
  scraped Klipper GitHub issues, Discourse forum threads, the curated error
  database, and the Klipper source code. Use when an error isn't in the local
  database, when the user asks why an error happens or how others fixed it,
  or when the user wants the knowledge base refreshed or the Klipper source
  cloned/searched.
---

# Klipper Knowledge Graph (Graphify)

Canonical skill: `.github/skills/klipper-knowledge-graph/SKILL.md`.

> ⚠ **Graphify must be installed to properly use this agent**:
> `uv tool install graphifyy` (or `pipx install graphifyy`), then
> `graphify install`. Check with `--check` below. If missing, tell the user
> to install it — the local error DB still works without it.

## Commands

```bash
# Installation / graph status
python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py --check

# Scrape knowledge (GitHub issues + Discourse forums → markdown corpus)
python .github/skills/klipper-knowledge-graph/scripts/klipper_kb_scraper.py --source all --query "<symptom>"
python .github/skills/klipper-knowledge-graph/scripts/klipper_kb_scraper.py --stats

# Local Klipper source (find exactly where/why an error is raised)
python .github/skills/klipper-knowledge-graph/scripts/klipper_source_manager.py --clone
python .github/skills/klipper-knowledge-graph/scripts/klipper_source_manager.py --locate-error "Timer too close"

# Build + query the graph
python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py --build --include-source
python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py --query "MCU shutdown during long prints"
python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py --explain "TMC5160"
python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py --path "heater_bed" "ADC out of range"

# Serve graph as MCP tools (query_graph, get_node, get_neighbors, shortest_path)
python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py --serve
```

Escalation order when debugging an unknown error:
1. `klipper_error_lookup.py --error` (curated DB, offline — 3d-printer-debug skill)
2. `graphify_kb.py --query` (community knowledge graph)
3. `klipper_source_manager.py --locate-error` (read the actual raise site)
4. `klipper_kb_scraper.py --query` then `graphify_kb.py --update` (fresh evidence)

Env: `GITHUB_TOKEN` (scraper rate limits), one of `ANTHROPIC_API_KEY`/
`OPENAI_API_KEY`/`GEMINI_API_KEY` (Graphify doc extraction). Outputs
(`agent-data/knowledge-base/`, `graphify-out/`, `.tmp/klipper-src/`) are
gitignored — never commit them.
