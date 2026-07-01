# Agent Creator — Copilot Instructions

This is the **3D Printer Expert** — it diagnoses firmware and software
issues on Klipper-based 3D printers, interfaces with OctoPrint's API, parses
Klipper logs, validates printer.cfg configurations, and references the
ControlCenter codebase for application-level debugging.

**Key files:**
- `agents.py` — `build_agents()` entry point for CommandCenter dynamic agent loading
- `config.json` — CommandCenter contract (name, integrations, tags, tool_scope)
- `.github/prompts/system.md` — System prompt loaded by agents.py at runtime
- `.github/skills/3d-printer-expert/SKILL.md` — Skill definition for 3D Printer Expertging
- `.github/skills/3d-printer-expert/scripts/` — Klipper log parser, OctoPrint API client, firmware analyzer, ControlCenter reference

**Architecture:** Skills (what to do) → Orchestration (decision making) → Execution (doing the work)

**ControlCenter Reference:** `C:\Users\VijayRaghavVarada\Documents\Github\ControlCenter`
