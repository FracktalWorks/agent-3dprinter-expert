# Klipper Debugging Knowledge Base (Graphify corpus)

This directory holds the scraped markdown corpus that Graphify ingests into
the debugging knowledge graph. Content is **generated, not committed** —
populate it with:

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
