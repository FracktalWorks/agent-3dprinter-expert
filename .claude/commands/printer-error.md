---
description: Explain a Klipper error message and how to fix it
argument-hint: "<error message>"
---

Explain this Klipper error exactly: **$ARGUMENTS**

Escalate in this order and stop as soon as you can explain the real mechanism:

1. Curated error database (offline, authoritative for known errors):
   ```bash
   python .github/skills/3d-printer-expert/scripts/klipper_error_lookup.py --error "$ARGUMENTS"
   ```
2. Community knowledge graph — how others hit and fixed it:
   ```bash
   python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py --query "$ARGUMENTS"
   ```
3. The Klipper source itself — read the actual raise site:
   ```bash
   python .github/skills/klipper-knowledge-graph/scripts/klipper_source_manager.py --locate-error "$ARGUMENTS"
   ```

Answer with: what the error literally means (which subsystem raises it and
under what condition) → the causes ranked by likelihood → the diagnostic that
distinguishes them → the fix. If any peripheral is implicated, check
compatibility with `peripheral_lookup.py --name "<part>"`.

Do not recommend reflashing firmware as a first response.
