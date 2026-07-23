# TODO — Anil Agent

## 🔲 1. Seed the Klipper knowledge corpus (run on DESKTOP)

> The cloud/remote session cannot scrape: its network proxy scopes GitHub API
> access to this repo only and blocks the Discourse forums. Run these on a
> desktop with normal network access + a `GITHUB_TOKEN` (Settings → Developer
> settings → Fine-grained token, public repo read is enough).

```bash
# From the repo root, with the venv active:
export GITHUB_TOKEN=ghp_...        # PowerShell: $env:GITHUB_TOKEN="ghp_..."

SCRAPER=.github/skills/klipper-knowledge-graph/scripts/klipper_kb_scraper.py

# 1a. Targeted GitHub scrapes — the classic error families (≈20 threads each)
for q in "timer too close" "mcu shutdown" "lost communication" \
         "ADC out of range" "not heating at expected rate" "tmc driver error" \
         "bltouch" "canbus uuid" "input shaper" "pressure advance" \
         "bed mesh" "sensorless homing"; do
  python $SCRAPER --source github --repos Klipper3d/klipper --query "$q" --max 20
done

# 1b. Bulk: most-discussed threads per project
python $SCRAPER --source github --repos Klipper3d/klipper --max 60
python $SCRAPER --source github --repos Arksine/moonraker --max 25
python $SCRAPER --source github --repos mainsail-crew/mainsail --max 25
python $SCRAPER --source github --repos OctoPrint/OctoPrint --query "klipper serial" --max 15

# 1c. Forums (Discourse) — official Klipper forum + OctoPrint community
python $SCRAPER --source discourse --max 100
python $SCRAPER --source discourse --query "timer too close" --max 20
python $SCRAPER --source discourse --query "tmc" --max 20

# 1d. Verify and COMMIT the corpus (it is version-controlled on purpose)
python $SCRAPER --stats
git add agent-data/knowledge-base && git commit -m "data: seed Klipper knowledge corpus"
```

## 🔲 2. Keep a local copy of the Klipper source (run on DESKTOP)

```bash
python .github/skills/klipper-knowledge-graph/scripts/klipper_source_manager.py --clone            # Klipper3d/klipper
python .github/skills/klipper-knowledge-graph/scripts/klipper_source_manager.py --clone --repo idex # FracktalWorks/klipper_IDEX
python .github/skills/klipper-knowledge-graph/scripts/klipper_source_manager.py --status
```

Clones live in `.tmp/klipper-src/` (gitignored — each machine keeps its own).

## 🔲 3. Install Graphify and build the knowledge graph (run on DESKTOP)

```bash
uv tool install graphifyy          # or: pipx install graphifyy
graphify install                   # register the /graphify skill
python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py --check
python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py --build --include-source
python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py --query "MCU shutdown during long prints"   # smoke test
```

Needs one LLM key for doc extraction: `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` /
`GEMINI_API_KEY`. `graphify-out/` stays gitignored (regenerates from the
committed corpus in minutes).

## 🔲 4. Refresh cadence

Re-run 1a-1d + `graphify_kb.py --update` monthly, or whenever debugging hits
a symptom the graph doesn't cover
(`klipper_kb_scraper.py --query "<symptom>"` → `graphify_kb.py --update`).

---

## ✅ Done

- Anil agent (Copilot + Claude Code), 20 registered tools
- Comprehensive Klipper error database (`agent-data/klipper_error_reference.json`)
- Klipper peripherals & combinations reference (`agent-data/klipper_peripherals_reference.json`)
- Moonraker / Mainsail / Pi / display diagnostic scripts
- Scraper, Graphify wrapper, and Klipper source manager scripts (tested; blocked only by cloud proxy)
