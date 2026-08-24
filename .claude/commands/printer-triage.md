---
description: Run the full 3D printer debugging SOP from triage through root cause
argument-hint: [symptom description, e.g. "Dragon 400 shuts down mid-print"]
---

Triage this printer problem: **$ARGUMENTS**

Follow the debugging SOP in `CLAUDE.md` strictly, in order. Do not skip
straight to a hypothesis.

1. **Triage** — establish what fails, when it started, what changed, and which
   printer model. If the user hasn't said, ask before running remote commands.
2. **klippy.log is ground truth** — parse it first:
   `python .github/skills/3d-printer-expert/scripts/klipper_log_parser.py --days 1`
3. **Identify the exact error** from the log:
   `python .github/skills/3d-printer-expert/scripts/klipper_error_lookup.py --error "<message>"`
   If it isn't in the curated DB, escalate in this order:
   - `python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py --query "<symptom>"`
   - `python .github/skills/klipper-knowledge-graph/scripts/klipper_source_manager.py --locate-error "<message>"`
4. **Rule out power early** — undervoltage mimics dozens of software bugs:
   `python .github/skills/3d-printer-expert/scripts/pi_system_diagnostics.py --check power`
5. **Propose ONE fix at a time.** Show a before/after config diff. Use
   `remote_config_editor.py` (auto-backup + validate) rather than hand-editing.
   Never suggest a firmware reflash as a first response.

Report as: symptom → evidence (actual log lines / readings) → root cause →
fix (one change) → verification steps.

Remember the Fracktal Works modular config rule: exactly ONE `[include
PRINTER_*.cfg]` is active, features toggle by commenting includes, and included
files are never edited directly.
