# 3D Printer Debugging Expert

> Expert agent that debugs Fracktal Works Klipper-based 3D printers across
> the full stack: Klipper firmware (every MCU/TMC/thermal error, with exact
> causes), OctoPrint, Moonraker, Mainsail, Raspberry Pi, SPI/HDMI display
> boards, electronics — plus a Graphify-powered knowledge graph of Klipper
> GitHub issues and community forums.

**Works in both:**
- **GitHub Copilot (VS Code)** — select **"3D Printer Expert"** from the Copilot Chat agent
  dropdown (`.github/agents/3d-printer-expert.agent.md`)
- **Claude Code** — open this repo in Claude Code; `CLAUDE.md` and the skills
  in `.claude/skills/` load automatically (plus a `3d-printer-expert` subagent in
  `.claude/agents/`)

## ⚠ Required: Install Graphify

**Graphify must be installed to properly use this agent.** It powers the
Klipper debugging knowledge graph (scraped GitHub issues, forum threads,
error database, and Klipper source):

```bash
uv tool install graphifyy      # recommended (or: pipx install graphifyy)
graphify install               # registers the /graphify skill with your assistant
```

Verify + build the graph:

```bash
python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py --check
python .github/skills/klipper-knowledge-graph/scripts/klipper_kb_scraper.py --source all --max 200
python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py --build
```

Without Graphify the agent still works using its local curated references
(comprehensive Klipper error DB, hardware/electronics reference, print
quality DB) — but knowledge-graph queries will be unavailable.

## What this agent can debug

| Domain | Tooling |
|--------|---------|
| **Klipper errors** — MCU comms/shutdowns, TMC driver flags (ot, s2ga, uv_cp, open-load), thermal watchdog, homing/probing, extrusion guards, CAN bus, config | `klipper_error_lookup.py` (exact mechanism for each error), `klipper_log_parser.py`, `klipper_docs.py` |
| **Peripherals & combinations** — motor drivers, temperature sensors, hotends, heaters, probes, extruders, accelerometers, endstops, CAN toolhead boards, and the rules for valid permutations | `peripheral_lookup.py` (`agent-data/klipper_peripherals_reference.json`) |
| **Klipper source** — where and why an error is raised | `klipper_source_manager.py` (local clones of Klipper3d/klipper + FracktalWorks/klipper_IDEX) |
| **OctoPrint** | `octoprint_api.py`, `octoprint_websocket_client.py`, `live_printer_diagnostics.py` |
| **Moonraker** | `moonraker_api.py` (REST + WebSocket test, full health sweep) |
| **Mainsail** — blank page, "cannot connect", 502, CORS, updates | `mainsail_diagnostics.py` |
| **Raspberry Pi** — undervoltage, throttling, SD health, CAN, services, boot config | `pi_system_diagnostics.py` |
| **Display boards** — SPI TFT (fbtft/ili9486), HDMI, DSI, KlipperScreen, touch | `display_diagnostics.py` |
| **Electronics** — BTT Manta, RP2040 CAN toolheads, TMC5160/2209, PSU | `agent-data/electronics_hardware_reference.json` |
| **Print quality** | `print_quality_analyzer.py` (24+ symptom database) |
| **printer.cfg** — validate + safe remote editing | `firmware_analyzer.py`, `remote_config_editor.py` |
| **Community knowledge** | Graphify graph over scraped GitHub issues + Discourse forums |
| **ControlCenter** (PyQt5 touchscreen app) | `controlcenter_reference.py` |

## 🚀 Instant Start (VS Code / Copilot)

**Just double-click:** `agent-3dprinter-expert.code-workspace`

VS Code will automatically:
1. Open the workspace
2. Prompt to trust the folder (click **Yes**)
3. Run setup (creates venv, installs dependencies)
4. Prompt to install recommended extensions

Then select **"3D Printer Expert"** from the Copilot Chat agent dropdown and describe
what's wrong with your printer.

## Instant Start (Claude Code)

```bash
cd agent-3dprinter-expert
claude
# "My TwinDragon shows 'MCU shutdown: Timer too close' mid-print — debug it"
```

`CLAUDE.md` gives Claude Code the same SOPs, skills, and scripts as the
Copilot agent.

## Manual Setup

**Windows (PowerShell):**
```powershell
.\setup.ps1
```

**macOS/Linux:**
```bash
chmod +x setup.sh && ./setup.sh
```

This automatically:
- ✅ Creates Python virtual environment
- ✅ Installs all dependencies (incl. paramiko for SSH diagnostics)
- ✅ Copies `.env.example` to `.env`
- ✅ Creates `.tmp/` directory

Then edit `.env` with your printer's connection details (`OCTOPRINT_IP`,
`MOONRAKER_HOST`, `PRINTER_SSH_HOST`, ...) and install Graphify (above).

## Structure

```
agent-3dprinter-expert/
├── agent-3dprinter-expert.code-workspace # ← Double-click to open VS Code!
├── setup.ps1 / setup.sh     # One-command setup scripts
├── AGENTS.md                # Human + AI orientation document
├── CLAUDE.md                # Claude Code entry point (same agent)
├── config.json              # CommandCenter contract
├── agents.py                # build_agents() entry point (19 registered tools)
├── .env.example             # Template for connection settings / API keys
├── requirements.txt         # Python dependencies
├── .github/
│   ├── prompts/system.md    # Runtime system prompt
│   ├── agents/3d-printer-expert.agent.md  # Copilot Chat agent
│   └── skills/
│       ├── 3d-printer-expert/       # Live debugging skill + 16 scripts
│       └── klipper-knowledge-graph/ # Graphify graph + scraper + source manager
├── .claude/
│   ├── agents/3d-printer-expert.md  # Claude Code subagent
│   └── skills/              # Claude Code skill wrappers
├── agent-data/              # Curated references (error DB, hardware, print quality)
│   └── knowledge-base/      # Scraped corpus (generated, gitignored)
├── graphify-out/            # Knowledge graph output (generated, gitignored)
├── inputs/ / outputs/       # User files / debug reports
├── tests/                   # pytest suite — CI gate
└── memory/                  # Persistent memory database
```

## Available Skills

- **3D Printer Expert** (`.github/skills/3d-printer-expert/SKILL.md`) — Klipper
  log parsing, comprehensive error lookup, OctoPrint/Moonraker/Mainsail
  APIs, firmware config analysis, SSH management, Pi + display diagnostics,
  data visualization, remote config editing, live diagnostics wizard,
  WebSocket monitoring, print quality analysis
- **Klipper Knowledge Graph** (`.github/skills/klipper-knowledge-graph/SKILL.md`)
  — scrape GitHub issues + forums, build/query the Graphify graph, local
  Klipper source management

## Required API Keys

- None required for core debugging.
- Optional: `GITHUB_TOKEN` (scraper rate limits), one of `ANTHROPIC_API_KEY` /
  `OPENAI_API_KEY` / `GEMINI_API_KEY` (Graphify document extraction).

---

*This workspace was generated from the [DOE Framework](https://github.com/vjvarada/DOE-Framework-Agentic-AI)*
