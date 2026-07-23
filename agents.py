"""agent-3d-printer-expert — MAF Agent definitions.

Exports:
    build_agents() -> list[GitHubCopilotAgent]   (Dynamic Agent Loader entry point)

Architecture (DOE v2):
  Layer 1 (Skills)        — .github/skills/3d-printer-expert/SKILL.md + scripts/
  Layer 2 (Orchestration) — THIS FILE (GitHubCopilotAgent via MAF)
  Layer 3 (Execution)     — .tmp/scripts/ shared utilities + skill scripts
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# ── Paths ─────────────────────────────────────────────────────────────────────
AGENT_DIR   = Path(__file__).parent.resolve()
PROMPTS_DIR = AGENT_DIR / ".github" / "prompts"
SKILLS_DIR  = AGENT_DIR / ".github" / "skills"
SCRIPTS_DIR = AGENT_DIR / ".tmp" / "scripts"

# Make .tmp/scripts/ importable by skill scripts at runtime
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


# ── Subprocess helpers ────────────────────────────────────────────────────────

def _run_env() -> dict[str, str]:
    """Add .tmp/scripts/ to PYTHONPATH so skill scripts can import shared utilities."""
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    scripts = str(SCRIPTS_DIR)
    env["PYTHONPATH"] = f"{scripts}{os.pathsep}{existing}" if existing else scripts
    return env


async def _run(args: list[str]) -> str:
    """Run a script as a subprocess. Raises RuntimeError on non-zero exit."""
    result = await asyncio.to_thread(
        subprocess.run, args,
        capture_output=True, text=True,
        cwd=str(AGENT_DIR), env=_run_env(),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or f"Script exited {result.returncode}")
    return result.stdout or "(no output)"


# ── System prompt ─────────────────────────────────────────────────────────────

def _build_system_prompt() -> str:
    """Load .github/prompts/system.md + append each .github/skills/*/SKILL.md as a tool block."""
    parts: list[str] = []
    system_md = PROMPTS_DIR / "system.md"
    if system_md.exists():
        parts.append(system_md.read_text(encoding="utf-8", errors="replace"))
    if SKILLS_DIR.exists():
        skill_sections: list[str] = []
        for skill_md in sorted(SKILLS_DIR.glob("*/SKILL.md")):
            content = skill_md.read_text(encoding="utf-8", errors="replace")
            skill_sections.append(f"\n### Tool: {skill_md.parent.name}\n\n{content}")
        if skill_sections:
            parts.append("\n\n---\n\n## Registered Skill Tool Descriptions\n")
            parts.extend(skill_sections)
    if not parts:
        agents_md = AGENT_DIR / "AGENTS.md"
        if agents_md.exists():
            parts.append(agents_md.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


SYSTEM_PROMPT = _build_system_prompt()


# ── Tool functions ────────────────────────────────────────────────────────────

async def parse_klipper_log(log_path: str = "", days: int = 1) -> str:
    """Parse Klipper logs for errors, warnings, and anomalies.
    Use when the user asks about Klipper errors, print failures, or log analysis.
    log_path: path to klippy.log (auto-detected if empty). days: how many days of logs to analyze."""
    args = [sys.executable,
        str(SKILLS_DIR / "3d-printer-expert" / "scripts" / "klipper_log_parser.py")]
    if log_path:
        args.extend(["--log-path", log_path])
    if days:
        args.extend(["--days", str(days)])
    return await _run(args)


async def octoprint_api(action: str, **kwargs) -> str:
    """Query or control OctoPrint via its REST API.
    Use when the user asks about printer status, job control, file management, or OctoPrint settings.
    action: one of status|connection|files|job|printer|settings|system|version.
    Additional kwargs passed as query/body params (--ip, --api-key, --port, --timeout)."""
    args = [sys.executable,
        str(SKILLS_DIR / "3d-printer-expert" / "scripts" / "octoprint_api.py"),
        "--action", action]
    for key, val in kwargs.items():
        args.extend([f"--{key.replace('_', '-')}", str(val)])
    return await _run(args)


async def analyze_firmware_config(config_path: str = "", check: str = "all") -> str:
    """Analyze Klipper printer.cfg and included config files for common issues.
    Use when the user asks about firmware configuration, printer.cfg problems, MCU settings, or Klipper config validation.
    config_path: path to printer.cfg (auto-detected if empty).
    check: one of all|syntax|mcu|thermistor|stepper|endstop|probe|macros|include|save_config."""
    args = [sys.executable,
        str(SKILLS_DIR / "3d-printer-expert" / "scripts" / "firmware_analyzer.py"),
        "--check", check]
    if config_path:
        args.extend(["--config-path", config_path])
    return await _run(args)


async def reference_controlcenter(query: str) -> str:
    """Search the ControlCenter codebase for relevant code patterns, configs, or debug techniques.
    Use when debugging a 3D printer issue that may relate to the ControlCenter PyQt5/OctoPrint application.
    query: what to search for (e.g., 'websocket reconnect', 'printer error handling', 'temperature polling')."""
    return await _run([sys.executable,
        str(SKILLS_DIR / "3d-printer-expert" / "scripts" / "controlcenter_reference.py"),
        "--query", query])


async def ssh_manager(action: str, **kwargs) -> str:
    """SSH into the printer's Raspberry Pi for remote diagnostics.
    Use when you need to read logs directly, restart services, execute commands,
    check system health, or get ground-truth data from the printer.
    action: one of logs|read-config|list-configs|restart-klipper|restart-octoprint|
            check-services|exec|system-info|backup-config|edit-config|klipper-errors|update-check.
    Additional kwargs: --host, --tail, --grep, --cmd, --section, --key, --value."""
    args = [sys.executable,
        str(SKILLS_DIR / "3d-printer-expert" / "scripts" / "ssh_manager.py"),
        "--action", action]
    for key, val in kwargs.items():
        args.extend([f"--{key.replace('_', '-')}", str(val)])
    return await _run(args)


async def visualize_data(source: str = "log", viz_type: str = "all",
                         log_path: str = "", **kwargs) -> str:
    """Visualize 3D printer data — temperature graphs, MCU stats, print timelines,
    input shaper results. Use when the user wants to see trends, patterns, or
    needs data plotted to understand intermittent issues.
    source: 'log' or 'api'. viz_type: temperature|stats|timeline|input-shaper|all.
    log_path: path to klippy.log (auto-detected if empty)."""
    args = [sys.executable,
        str(SKILLS_DIR / "3d-printer-expert" / "scripts" / "visualize_data.py"),
        "--source", source, "--type", viz_type]
    if log_path:
        args.extend(["--log-path", log_path])
    for key, val in kwargs.items():
        args.extend([f"--{key.replace('_', '-')}", str(val)])
    return await _run(args)


async def klipper_docs(topic: str = "", command: str = "",
                      search: str = "", diagnose: str = "",
                      action: str = "links") -> str:
    """Access the complete Klipper documentation reference — G-code commands,
    config topics, troubleshooting guides, official doc links, and Klipper tools.
    Use when you need authoritative Klipper documentation, want to look up a
    diagnostic command, need a troubleshooting guide for a symptom, or want
    official Klipper source links.
    action: links|topics|commands|tools|fetch.
    topic: doc topic key (bed_mesh, input_shaper, pressure_advance, etc.).
    command: G-code command name (QUERY_ENDSTOPS, PID_CALIBRATE, etc.).
    search: free-text search across all reference material.
    diagnose: symptom key (heater_error, mcu_disconnect, layer_shift, etc.)."""
    args = [sys.executable,
        str(SKILLS_DIR / "3d-printer-expert" / "scripts" / "klipper_docs.py")]
    if topic:
        args.extend(["--topic", topic])
    elif command:
        args.extend(["--command", command])
    elif search:
        args.extend(["--search", search])
    elif diagnose:
        args.extend(["--diagnose", diagnose])
    else:
        if action == "commands":
            args.append("--list-commands")
        elif action == "topics":
            args.append("--list-topics")
        elif action == "tools":
            args.append("--tools")
        elif action == "fetch":
            args.append("--fetch")
        else:
            args.append("--links")
    return await _run(args)


async def live_printer_diagnostics(
    ip: str = "", api_key: str = "",
    check: str = "all", interactive: bool = True,
    output: str = "", **kwargs,
) -> str:
    """Run interactive live diagnostic checks on a 3D printer via OctoPrint.
    Connects via REST API, runs a comprehensive checklist covering:
    system health, thermistors, heaters, extrusion, homing, motion, and probe.
    Supports human-in-the-loop for physical verification tests.
    Use when the user asks about live debugging, printer health checks,
    or wants to run a diagnostic wizard on a connected printer.
    check: all|system|thermistor|heater|extrusion|homing|motion|probe|adc.
    interactive: True to prompt for human verification, False for automated.
    output: path to save JSON report."""
    args = [sys.executable,
        str(SKILLS_DIR / "3d-printer-expert" / "scripts"
            / "live_printer_diagnostics.py")]
    if ip:
        args.extend(["--ip", ip])
    if api_key:
        args.extend(["--api-key", api_key])
    args.extend(["--check", check])
    if not interactive:
        args.append("--no-interactive")
    if output:
        args.extend(["--output", output])
    for key, val in kwargs.items():
        if val:
            args.extend([f"--{key.replace('_', '-')}", str(val)])
    return await _run(args)


async def print_quality_analyzer(
    symptom: str = "", category: str = "",
    material: str = "", action: str = "symptom",
    **kwargs,
) -> str:
    """Diagnose 3D print quality issues from symptom descriptions.
    Matches user-described print symptoms to a comprehensive database
    of 24+ known 3D printing issues. Provides targeted fixes, Klipper
    G-code commands, slicer setting recommendations, and material-
    specific guidance. Also provides Klipper calibration tuning guide
    and post-processing techniques.
    action: symptom|category|list-categories|material-guide|tuning-guide|post-processing.
    symptom: natural language description of the print issue.
    category: show all issues in a category (adhesion|extrusion|surface|structural|dimensional).
    material: filter by material for specific guidance (PLA|PETG|ABS|ASA|TPU|NYLON|PC)."""
    args = [sys.executable,
        str(SKILLS_DIR / "3d-printer-expert" / "scripts"
            / "print_quality_analyzer.py")]
    if action == "list-categories":
        args.append("--list-categories")
    elif action == "tuning-guide":
        args.append("--tuning-guide")
    elif action == "post-processing":
        args.append("--post-processing")
    elif action == "material-guide" and material:
        args.extend(["--material-guide", material])
    elif action == "category" and category:
        args.extend(["--category", category])
    elif symptom:
        args.extend(["--symptom", symptom])
        if material:
            args.extend(["--material", material])
    else:
        args.append("--list-categories")
    for key, val in kwargs.items():
        if val:
            args.extend([f"--{key.replace('_', '-')}", str(val)])
    return await _run(args)


async def octoprint_websocket(
    ip: str = "", api_key: str = "",
    monitor: str = "all", duration: int = 60,
    trend: str = "", detect_anomalies: bool = False,
    **kwargs,
) -> str:
    """Open a real-time WebSocket connection to OctoPrint for live
    temperature monitoring, event capture, and anomaly detection.
    Use when you need live temperature streaming, want to watch for
    intermittent issues in real-time, or need to capture events
    during a print for later analysis.
    monitor: temps|events|all.
    duration: seconds to monitor (0 = indefinite, requires manual stop).
    trend: heater name to analyze trend (e.g., 'tool0').
    detect_anomalies: scan collected data for temperature anomalies."""
    args = [sys.executable,
        str(SKILLS_DIR / "3d-printer-expert" / "scripts"
            / "octoprint_websocket_client.py")]
    if ip:
        args.extend(["--ip", ip])
    if api_key:
        args.extend(["--api-key", api_key])
    if monitor:
        args.extend(["--monitor", monitor])
    if duration:
        args.extend(["--duration", str(duration)])
    if trend:
        args.extend(["--trend", trend])
    if detect_anomalies:
        args.append("--detect-anomalies")
    for key, val in kwargs.items():
        if val:
            args.extend([f"--{key.replace('_', '-')}", str(val)])
    return await _run(args)


async def remote_config_editor(host: str = "", action: str = "read",
                               **kwargs) -> str:
    """Safely edit Klipper printer.cfg on a remote printer via SSH.
    Auto-creates timestamped backups, validates syntax, shows diffs, and can
    apply changes with Klipper restart + verification.
    Use when you need to change config values, enable/disable modules,
    or safely apply config changes to a live printer.
    action: read|list-sections|get-section|edit|validate|backup|list-backups|
            restore|diff|apply-and-restart|enable|disable.
    Requires --host (or PRINTER_SSH_HOST env var).
    For --edit: also needs --section, --key, --value.
    For --enable/--disable: pass the include filename (e.g. 'MAG_DOOR.cfg')."""
    args = [sys.executable,
        str(SKILLS_DIR / "3d-printer-expert" / "scripts" / "remote_config_editor.py"),
        "--action", action]
    if host:
        args.extend(["--host", host])
    for key, val in kwargs.items():
        kebab = key.replace("_", "-")
        if isinstance(val, bool):
            if val:
                args.append(f"--{kebab}")
        else:
            args.extend([f"--{kebab}", str(val)])
    return await _run(args)


async def klipper_error_lookup(error: str = "", search: str = "",
                               category: str = "", action: str = "") -> str:
    """Explain exactly why a Klipper error occurs — comprehensive database of
    MCU communication/shutdown errors, TMC driver flags (ot, s2ga, uv_cp,
    open-load, GSTAT), thermal watchdog, homing/probing, extrusion guards,
    CAN bus faults, and config errors, each with source location, mechanism,
    diagnostics, and fixes.
    Use FIRST whenever the user reports a specific Klipper error message.
    error: the raw error message to identify.
    search: free-text search across the database.
    category: mcu_communication|mcu_shutdown|tmc_drivers|thermal|motion_homing|extrusion|canbus|config_startup.
    action: 'list' to list all known errors."""
    args = [sys.executable,
        str(SKILLS_DIR / "3d-printer-expert" / "scripts" / "klipper_error_lookup.py")]
    if error:
        args.extend(["--error", error])
    elif search:
        args.extend(["--search", search])
    elif category:
        args.extend(["--category", category])
    else:
        args.append("--list")
    return await _run(args)


async def peripheral_lookup(name: str = "", search: str = "",
                            category: str = "", combos: str = "",
                            action: str = "") -> str:
    """Look up Klipper-compatible peripherals and the rules for combining
    them — motor drivers (TMC2209/2130/2240/5160, step-dir), temperature
    sensors (NTC thermistors, PT1000/PT100, thermocouples, chamber sensors),
    hotends, heaters, probes (BLTouch, inductive, eddy current, load cell),
    extruders (rotation_distance starting points), accelerometers, filament
    sensors, endstops (incl. sensorless), fans, and CAN toolhead boards.
    Use for hardware selection, 'can I combine X with Y', wiring/config
    section questions, and sanity-checking a peripheral setup.
    name: peripheral name (partial ok, e.g. 'TMC5160', 'BLTouch').
    search: free-text search across the database.
    category: motor_drivers|temperature_sensors|hotends|heaters|probes|
              extruders|accelerometers|filament_sensors|endstops|fans|
              can_toolhead_boards|displays_leds|combination_rules.
    combos: term to filter combination rules (or 'all' for every rule).
    action: 'list' to list all categories and entries."""
    args = [sys.executable,
        str(SKILLS_DIR / "3d-printer-expert" / "scripts" / "peripheral_lookup.py")]
    if combos:
        args.append("--combos")
        if combos != "all":
            args.append(combos)
    elif name:
        args.extend(["--name", name])
    elif search:
        args.extend(["--search", search])
    elif category:
        args.extend(["--category", category])
    else:
        args.append("--list")
    return await _run(args)


async def moonraker_api(action: str, **kwargs) -> str:
    """Query or control Moonraker (the API server behind Mainsail, Fluidd,
    and KlipperScreen) via its REST API.
    Use for klippy state, printer object queries, temperatures, running
    G-code, job history, update manager status, power devices, service
    restarts, or a full health sweep.
    action: diagnose|info|server|klippy-state|temps|query|gcode|gcode-history|
            print-status|history|sysinfo|proc-stats|update-status|power|files|
            restart-klipper|firmware-restart|restart-service|websocket-test.
    Additional kwargs: --host, --port, --api-key, --objects, --script, --service."""
    args = [sys.executable,
        str(SKILLS_DIR / "3d-printer-expert" / "scripts" / "moonraker_api.py"),
        "--action", action]
    for key, val in kwargs.items():
        args.extend([f"--{key.replace('_', '-')}", str(val)])
    return await _run(args)


async def mainsail_diagnostics(check: str = "all", host: str = "",
                               failures: str = "", **kwargs) -> str:
    """Debug the Mainsail web UI stack layer by layer — nginx frontend,
    Moonraker REST, WebSocket upgrade, CORS, component versions, and
    SSH-level service/config checks.
    Use when Mainsail shows a blank page, 'cannot connect to Moonraker',
    502 errors, or update manager problems.
    check: all|http|moonraker|websocket|versions|ssh.
    failures: pass a failure-mode key (or empty string) to print the known
    failure-mode reference instead of running live checks."""
    args = [sys.executable,
        str(SKILLS_DIR / "3d-printer-expert" / "scripts" / "mainsail_diagnostics.py")]
    if failures:
        args.extend(["--failures", failures])
    else:
        args.extend(["--check", check])
        if host:
            args.extend(["--host", host])
        for key, val in kwargs.items():
            if val:
                args.extend([f"--{key.replace('_', '-')}", str(val)])
    return await _run(args)


async def pi_system_diagnostics(check: str = "all", host: str = "",
                                failures: str = "", **kwargs) -> str:
    """Raspberry Pi health checks via SSH — undervoltage/throttling decode,
    thermals, SD card health, network, USB serial devices, CAN bus state,
    systemd services, boot config, and journal errors.
    Use EARLY when chasing random MCU disconnects, reboots, or slowness —
    undervoltage and failing SD cards mimic dozens of software bugs.
    check: all|power|thermal|storage|network|usb|can|services|boot-config|journal.
    failures: failure-mode key (or empty) for the offline reference."""
    args = [sys.executable,
        str(SKILLS_DIR / "3d-printer-expert" / "scripts" / "pi_system_diagnostics.py")]
    if failures:
        args.extend(["--failures", failures])
    else:
        args.extend(["--check", check])
        if host:
            args.extend(["--host", host])
        for key, val in kwargs.items():
            if val:
                args.extend([f"--{key.replace('_', '-')}", str(val)])
    return await _run(args)


async def display_diagnostics(check: str = "all", host: str = "",
                              failures: str = "", **kwargs) -> str:
    """Debug display boards on the printer's Pi — SPI TFT panels (fbtft
    overlays), HDMI and DSI screens, framebuffer/KMS state, touch input and
    calibration, KlipperScreen service and logs, and backlight control.
    Use for white/black screens, no HDMI signal, inverted touch, or
    KlipperScreen failures.
    check: all|boot-config|framebuffer|kms|spi|touch|hdmi|klipperscreen|backlight|dmesg.
    failures: failure-mode key (e.g. spi_white_screen, hdmi_no_signal) or
    empty string for the full offline reference."""
    args = [sys.executable,
        str(SKILLS_DIR / "3d-printer-expert" / "scripts" / "display_diagnostics.py")]
    if failures:
        args.extend(["--failures", failures])
    else:
        args.extend(["--check", check])
        if host:
            args.extend(["--host", host])
        for key, val in kwargs.items():
            if val:
                args.extend([f"--{key.replace('_', '-')}", str(val)])
    return await _run(args)


async def graphify_knowledge_graph(action: str = "check", query: str = "",
                                   explain: str = "", node_a: str = "",
                                   node_b: str = "") -> str:
    """Build and query the Graphify knowledge graph of Klipper debugging
    knowledge (scraped GitHub issues, forum threads, error DB, Klipper source).
    Requires Graphify installed (uv tool install graphifyy && graphify install)
    — 'check' verifies and prints install instructions if missing.
    Use for errors not covered by klipper_error_lookup, or to explore how
    errors, configs, and hardware relate.
    action: check|build|update|status|query|explain|path|serve.
    query: semantic question for action=query.
    explain: entity name for action=explain.
    node_a/node_b: entities for action=path."""
    script = str(SKILLS_DIR / "klipper-knowledge-graph" / "scripts" / "graphify_kb.py")
    args = [sys.executable, script]
    if action == "query" and query:
        args.extend(["--query", query])
    elif action == "explain" and explain:
        args.extend(["--explain", explain])
    elif action == "path" and node_a and node_b:
        args.extend(["--path", node_a, node_b])
    elif action in ("build", "update", "status", "check"):
        args.append(f"--{action}")
    else:
        args.append("--check")
    return await _run(args)


async def klipper_kb_scraper(query: str = "", source: str = "all",
                             max_items: int = 50, stats: bool = False) -> str:
    """Scrape Klipper debugging knowledge from GitHub issues (Klipper3d/klipper,
    Arksine/moonraker, mainsail-crew/mainsail, OctoPrint/OctoPrint) and
    Discourse forums (klipper.discourse.group, community.octoprint.org) into
    the local corpus for the knowledge graph.
    Use when the knowledge graph lacks coverage of a symptom — scrape
    targeted, then rebuild with graphify_knowledge_graph action=update.
    query: targeted search (recommended). source: all|github|discourse.
    stats: True to just report corpus statistics."""
    script = str(SKILLS_DIR / "klipper-knowledge-graph" / "scripts" / "klipper_kb_scraper.py")
    args = [sys.executable, script]
    if stats:
        args.append("--stats")
    else:
        args.extend(["--source", source, "--max", str(max_items)])
        if query:
            args.extend(["--query", query])
    return await _run(args)


async def klipper_source(action: str = "status", error: str = "",
                         pattern: str = "", repo: str = "klipper",
                         context: int = 3) -> str:
    """Manage and search local clones of the Klipper source code (official
    Klipper3d/klipper, FracktalWorks klipper_IDEX fork, Moonraker) to find
    exactly where and why an error is raised.
    Use to answer 'where does this error come from' from the actual source.
    action: status|clone|update|locate-error|grep.
    error: error message for locate-error. pattern: regex for grep.
    repo: klipper|idex|moonraker (for clone)."""
    script = str(SKILLS_DIR / "klipper-knowledge-graph" / "scripts" / "klipper_source_manager.py")
    args = [sys.executable, script]
    if action == "locate-error" and error:
        args.extend(["--locate-error", error, "--context", str(context)])
    elif action == "grep" and pattern:
        args.extend(["--grep", pattern, "--context", str(context)])
    elif action == "clone":
        args.extend(["--clone", "--repo", repo])
    elif action == "update":
        args.append("--update")
    else:
        args.append("--status")
    return await _run(args)


# ── LiteLLM provider (CommandCenter mode) ────────────────────────────────────

def _llm_provider() -> dict[str, Any]:
    base_url = os.environ.get("LITELLM_BASE_URL", "http://127.0.0.1:8080")
    api_key  = os.environ.get("LITELLM_MASTER_KEY", "sk-local")
    return {"type": "openai", "base_url": f"{base_url}/v1", "api_key": api_key}


# ── Agent factory ─────────────────────────────────────────────────────────────

def build_agent() -> "GitHubCopilotAgent":
    from agent_framework_github_copilot import GitHubCopilotAgent  # type: ignore[import]
    from copilot.types import PermissionHandler                     # type: ignore[import]

    return GitHubCopilotAgent(
        name="anil",
        description="Anil — expert 3D printer debugging agent. Full-stack Klipper diagnosis (every MCU/TMC/thermal error explained), OctoPrint + Moonraker + Mainsail tooling, Raspberry Pi and SPI/HDMI display debugging, electronics diagnostics, and a Graphify-powered knowledge graph of Klipper issues and forums.",
        instructions=SYSTEM_PROMPT,
        tools=[
            parse_klipper_log,
            octoprint_api,
            analyze_firmware_config,
            reference_controlcenter,
            ssh_manager,
            visualize_data,
            remote_config_editor,
            klipper_docs,
            live_printer_diagnostics,
            octoprint_websocket,
            print_quality_analyzer,
            klipper_error_lookup,
            peripheral_lookup,
            moonraker_api,
            mainsail_diagnostics,
            pi_system_diagnostics,
            display_diagnostics,
            graphify_knowledge_graph,
            klipper_kb_scraper,
            klipper_source,
        ],
        default_options={
            "model": "claude-sonnet-4-5",
            "max_turns": 30,
        },
        llm_provider=_llm_provider(),
        permission_handler=PermissionHandler(
            base_dir=str(AGENT_DIR),
            deny_patterns=["*.env", "*.pem", "*.key", "**/credentials.json", "**/token.json"],
        ),
    )


# ── build_agents() — CommandCenter entry point ────────────────────────────────

def build_agents() -> list:
    """Return a list of agent instances for CommandCenter to register."""
    return [build_agent()]
