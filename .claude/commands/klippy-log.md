---
description: Parse klippy.log and explain every error found
argument-hint: [days to look back, default 1]
---

Parse the Klipper log and explain what it shows.

```bash
python .github/skills/3d-printer-expert/scripts/klipper_log_parser.py --days ${ARGUMENTS:-1}
```

Then, for each distinct error or shutdown the parser reports, look it up so you
explain the actual mechanism rather than guessing:

```bash
python .github/skills/3d-printer-expert/scripts/klipper_error_lookup.py --error "<message>"
```

If an error isn't in the curated database, escalate to the knowledge graph
(`graphify_kb.py --query`) and then the Klipper source
(`klipper_source_manager.py --locate-error`) before offering a theory.

Summarise as a table of: timestamp → error → mechanism → likely cause →
next diagnostic step. Quote the real log lines as evidence. Flag anything that
looks like undervoltage or MCU timing separately, since those masquerade as
unrelated failures.
