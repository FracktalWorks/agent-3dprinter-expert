"""test_agents.py — CI gate: build_agents() must return a non-empty list.

Run:
    pytest tests/test_agents.py -v
"""

import sys
from pathlib import Path

# Add agent root to path
AGENT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(AGENT_ROOT))


def test_build_agents_returns_list():
    """build_agents() must return a non-empty list."""
    from agents import build_agents

    agents = build_agents()
    assert isinstance(agents, list), f"Expected list, got {type(agents)}"
    assert len(agents) > 0, "build_agents() returned empty list"


def test_agent_has_name():
    """Each agent must have a name attribute."""
    from agents import build_agents

    for agent in build_agents():
        assert hasattr(agent, "name"), "Agent missing 'name' attribute"
        assert agent.name, "Agent name is empty"


def test_agent_has_instructions():
    """Each agent must have instructions."""
    from agents import build_agents

    for agent in build_agents():
        assert hasattr(agent, "instructions"), (
            "Agent missing 'instructions' attribute"
        )
        assert agent.instructions, "Agent instructions are empty"


def test_agent_has_tools():
    """Each agent must have at least one tool."""
    from agents import build_agents

    for agent in build_agents():
        assert hasattr(agent, "tools"), "Agent missing 'tools' attribute"
        assert len(agent.tools) > 0, "Agent has no tools registered"
        # Verify our core tools are registered
        tool_names = [t.__name__ for t in agent.tools]
        required = [
            "parse_klipper_log",
            "octoprint_api",
            "analyze_firmware_config",
            "reference_controlcenter",
            "ssh_manager",
            "visualize_data",
            "remote_config_editor",
            "klipper_docs",
            "klipper_error_lookup",
            "moonraker_api",
            "mainsail_diagnostics",
            "pi_system_diagnostics",
            "display_diagnostics",
            "graphify_knowledge_graph",
            "klipper_kb_scraper",
            "klipper_source",
        ]
        for name in required:
            assert name in tool_names, (
                f"Required tool '{name}' not found in agent tools: {tool_names}"
            )
