# Klipper Debugging Knowledge Base (Graphify corpus)

This directory holds the scraped markdown corpus that Graphify ingests into
the debugging knowledge graph. The corpus **IS committed** once scraped — it
is the stored community knowledge (GitHub issues + forum threads) that makes
answers instantly available without re-scraping.

> ⚠ Scraping must run on a machine with normal network access (desktop) — the
> cloud session's proxy blocks off-scope GitHub repos and the Discourse
> forums. **See `TODO.md` at the repo root for the full seeding runbook.**

Populate it with:

```bash
# Targeted scrape (recommended — richest signal)
python .github/skills/klipper-knowledge-graph/scripts/klipper_kb_scraper.py --source all --query "your symptom"

# Bulk scrape of the most-discussed threads
python .github/skills/klipper-knowledge-graph/scripts/klipper_kb_scraper.py --source all --max 200

# Corpus stats
python .github/skills/klipper-knowledge-graph/scripts/klipper_kb_scraper.py --stats
```

Layout after scraping:

```
knowledge-base/
├── github/
│   ├── Klipper3d__klipper/<issue>.md
│   ├── Arksine__moonraker/<issue>.md
│   ├── mainsail-crew__mainsail/<issue>.md
│   └── OctoPrint__OctoPrint/<issue>.md
└── discourse/
    ├── klipper.discourse.group/<topic>.md
    └── community.octoprint.org/<topic>.md
```

Then build the graph:

```bash
python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py --build
```

> ⚠ Requires Graphify: `uv tool install graphifyy` && `graphify install`
