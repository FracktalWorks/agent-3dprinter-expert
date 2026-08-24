---
description: Query the Klipper knowledge graph for community fixes and error relations
argument-hint: "<question or symptom>"
---

Query the Klipper knowledge graph: **$ARGUMENTS**

First confirm the graph is usable, since Graphify is a hard requirement for
this path:

```bash
python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py --check
```

If Graphify is missing, tell the user to install it
(`uv tool install graphifyy && graphify install`) and fall back to the curated
offline database (`klipper_error_lookup.py`) for this question. If the graph
exists but hasn't been built, say so — building is a separate, deliberate step
(`--build`), not something to run silently mid-question.

Then query:

```bash
python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py --query "$ARGUMENTS"
```

Useful follow-ups once you have candidate nodes:

```bash
python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py --explain "<node>"
python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py --path "<node A>" "<node B>"
```

Distinguish clearly between what the graph actually contains and your own
inference. Community threads are evidence of what worked for someone else's
hardware, not proof for this printer — say which findings still need
verification on the user's machine.
