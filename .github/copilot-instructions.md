# Anil — Copilot Instructions

This is **Anil**, the 3D printer debugging expert — it diagnoses firmware,
software, and hardware issues on Klipper-based 3D printers: Klipper errors
(comprehensive MCU/TMC/thermal/homing/CAN error database with exact causes),
OctoPrint, Moonraker, and Mainsail APIs, Raspberry Pi health, SPI/HDMI
display boards, electronics, printer.cfg validation, and the ControlCenter
codebase for application-level debugging. A Graphify-powered knowledge graph
holds scraped Klipper GitHub issues and forum threads.

> ⚠ Graphify must be installed to properly use the agent
> (`uv tool install graphifyy` && `graphify install`).

**Key files:**
- `agents.py` — `build_agents()` entry point for CommandCenter dynamic agent loading
- `config.json` — CommandCenter contract (name, integrations, tags, tool_scope)
- `.github/prompts/system.md` — System prompt loaded by agents.py at runtime
- `.github/agents/anil.agent.md` — VS Code Copilot Chat agent definition
- `CLAUDE.md` + `.claude/` — Claude Code entry point (same agent, same scripts)
- `.github/skills/3d-printer-expert/` — Live debugging skill (16 diagnostic scripts)
- `.github/skills/klipper-knowledge-graph/` — Graphify graph, GitHub/forum scraper, Klipper source manager
- `agent-data/klipper_error_reference.json` — Comprehensive Klipper error database

**Architecture:** Skills (what to do) → Orchestration (decision making) → Execution (doing the work)

**ControlCenter Reference:** `C:\Users\VijayRaghavVarada\Documents\Github\ControlCenter`
