"""Agent CLI Detection Registry for Task Agent.

Provides a unified registry of popular agent CLIs, detection logic, global/project
MCP configuration paths, and plugin installation helpers.
"""

from dataclasses import dataclass, field
from pathlib import Path
import shutil
from typing import Dict, List, Optional


@dataclass
class AgentCLIInfo:
    id: str
    name: str
    binary: str
    description: str
    config_paths: List[Path] = field(default_factory=list)
    mcp_support: bool = True
    mcp_command_example: str = ""
    plugin_support: bool = False
    plugin_path: Optional[Path] = None
    skills_path: Optional[Path] = None
    plugin_template: str = ""
    chat_log_patterns: List[str] = field(default_factory=list)
    chat_parser_type: str = "json"


def get_agent_cli_registry() -> Dict[str, AgentCLIInfo]:
    home = Path.home()
    return {
        "claude": AgentCLIInfo(
            id="claude",
            name="Claude Code",
            binary="claude",
            description="Anthropic's agentic coding CLI tool",
            config_paths=[home / ".claude.json", home / ".claude" / "config.json"],
            mcp_support=True,
            mcp_command_example="ta init-mcp --claude",
            plugin_support=True,
            plugin_path=home / ".claude" / "plugins",
            skills_path=home / ".claude" / "commands",
            plugin_template="claude-code",
            chat_log_patterns=[
                "~/.claude/projects/**/*.jsonl",
                "~/.claude/history.jsonl",
            ],
            chat_parser_type="jsonl",
        ),
        "agy": AgentCLIInfo(
            id="agy",
            name="Antigravity CLI",
            binary="agy",
            description="Google DeepMind Antigravity CLI",
            config_paths=[home / ".gemini" / "antigravity-cli" / "mcp_config.json"],
            mcp_support=True,
            mcp_command_example="ta init-mcp --agy",
            plugin_support=True,
            plugin_path=home / ".gemini" / "antigravity-cli" / "plugins",
            skills_path=home / ".gemini" / "config" / "skills",
            plugin_template="antigravity",
            chat_log_patterns=[
                "~/.gemini/tmp/**/chats/session-*.json",
                "~/.gemini/antigravity-cli/brain/**/transcript.jsonl",
                "~/.gemini/antigravity-cli/brain/**/transcript_full.jsonl",
            ],
            chat_parser_type="json",
        ),
        "opencode": AgentCLIInfo(
            id="opencode",
            name="OpenCode",
            binary="opencode",
            description="Open-source agentic coding workspace and TUI",
            config_paths=[home / ".config" / "opencode" / "opencode.json"],
            mcp_support=True,
            mcp_command_example="ta init-mcp --opencode",
            plugin_support=True,
            plugin_path=home / ".config" / "opencode" / "plugins",
            skills_path=home / ".config" / "opencode" / "skills",
            plugin_template="opencode",
            chat_log_patterns=[
                "~/.local/share/opencode/storage/**/*.json",
                "~/.local/share/opencode/sessions/*.json",
                "~/.config/opencode/chats/*.json",
            ],
            chat_parser_type="json",
        ),
        "copilot": AgentCLIInfo(
            id="copilot",
            name="GitHub Copilot CLI",
            binary="copilot",
            description="GitHub Copilot CLI agent",
            config_paths=[home / ".config" / "github-copilot" / "config.json"],
            mcp_support=True,
            mcp_command_example="ta init-mcp --copilot",
            plugin_support=True,
            plugin_path=home / ".config" / "github-copilot" / "plugins",
            skills_path=home / ".config" / "github-copilot" / "skills",
            plugin_template="copilot",
        ),
        "grok": AgentCLIInfo(
            id="grok",
            name="Grok Build",
            binary="grok",
            description="xAI Grok coding assistant CLI",
            config_paths=[home / ".config" / "grok" / "config.json"],
            mcp_support=True,
            mcp_command_example="ta init-mcp --agent grok",
            plugin_support=True,
            plugin_path=home / ".config" / "grok" / "plugins",
            skills_path=home / ".config" / "grok" / "skills",
            plugin_template="grok",
        ),
        "cursor": AgentCLIInfo(
            id="cursor",
            name="Cursor CLI",
            binary="cursor",
            description="Cursor AI editor CLI interface",
            config_paths=[
                home / ".cursor" / "mcp.json",
                home / ".config" / "Cursor" / "mcp.json",
            ],
            mcp_support=True,
            mcp_command_example="ta init-mcp --print",
            plugin_support=True,
            plugin_path=home / ".cursor" / "plugins",
            skills_path=home / ".cursor" / "skills",
            plugin_template="cursor",
        ),
        "windsurf": AgentCLIInfo(
            id="windsurf",
            name="Windsurf",
            binary="windsurf",
            description="Codeium Windsurf AI IDE CLI",
            config_paths=[home / ".codeium" / "windsurf" / "mcp_config.json"],
            mcp_support=True,
            mcp_command_example="ta init-mcp --print",
            plugin_support=True,
            plugin_path=home / ".codeium" / "windsurf" / "plugins",
            skills_path=home / ".codeium" / "windsurf" / "skills",
            plugin_template="windsurf",
        ),
        "aider": AgentCLIInfo(
            id="aider",
            name="Aider",
            binary="aider",
            description="AI pair programming in your terminal",
            config_paths=[home / ".aider.conf.yml"],
            mcp_support=False,
            plugin_support=False,
            chat_log_patterns=[
                "**/.aider.chat.history.md",
                "~/.aider.chat.history.md",
            ],
            chat_parser_type="markdown",
        ),
        "codex": AgentCLIInfo(
            id="codex",
            name="Codex CLI / ADK Worker",
            binary="codex",
            description="OpenAI Codex CLI harness",
            config_paths=[home / ".codex" / "config.json"],
            mcp_support=True,
            plugin_support=True,
            plugin_path=home / ".codex" / "plugins",
            skills_path=home / ".codex" / "skills",
            plugin_template="codex",
        ),
        "continue": AgentCLIInfo(
            id="continue",
            name="Continue",
            binary="continue",
            description="Open-source AI code assistant",
            config_paths=[home / ".continue" / "config.json"],
            mcp_support=True,
            plugin_support=True,
            plugin_path=home / ".continue" / "plugins",
            skills_path=home / ".continue" / "skills",
            plugin_template="continue",
        ),
        "cline": AgentCLIInfo(
            id="cline",
            name="Cline",
            binary="cline",
            description="Autonomous coding agent extension & CLI",
            config_paths=[home / ".cline" / "mcp_settings.json"],
            mcp_support=True,
            plugin_support=True,
            chat_log_patterns=[
                "~/.vscode-server/data/User/globalStorage/saoudrizwan.claude-dev/tasks/*/ui_messages.json",
                "~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/tasks/*/ui_messages.json",
            ],
            chat_parser_type="json",
        ),
        "roo": AgentCLIInfo(
            id="roo",
            name="Roo Code",
            binary="roo",
            description="Roo Code AI coding assistant",
            config_paths=[home / ".roo" / "mcp_settings.json"],
            mcp_support=True,
            plugin_support=True,
            chat_log_patterns=[
                "~/.vscode-server/data/User/globalStorage/rooveterinaryinc.roo-cline/tasks/*/ui_messages.json",
                "~/.vscode-server-insiders/data/User/globalStorage/rooveterinaryinc.roo-cline/tasks/*/ui_messages.json",
                "~/.config/Code/User/globalStorage/rooveterinaryinc.roo-cline/tasks/*/ui_messages.json",
                "~/.config/Code - Insiders/User/globalStorage/rooveterinaryinc.roo-cline/tasks/*/ui_messages.json",
            ],
            chat_parser_type="json",
        ),
        "goose": AgentCLIInfo(
            id="goose",
            name="Goose",
            binary="goose",
            description="Block's open-source AI agent framework",
            config_paths=[home / ".config" / "goose" / "config.yaml"],
            mcp_support=True,
            plugin_support=False,
        ),
        "sgpt": AgentCLIInfo(
            id="sgpt",
            name="ShellGPT",
            binary="sgpt",
            description="Command-line productivity tool powered by AI",
            config_paths=[home / ".config" / "shell_gpt" / ".sgptrc"],
            mcp_support=False,
            plugin_support=False,
        ),
        "interpreter": AgentCLIInfo(
            id="interpreter",
            name="Open Interpreter",
            binary="interpreter",
            description="Natural language interface to computer capabilities",
            config_paths=[home / ".config" / "open-interpreter" / "config.yaml"],
            mcp_support=False,
            plugin_support=False,
        ),
    }


def inspect_agent_cli(agent_id: str) -> dict:
    """Inspect local installation and MCP registration status for an agent CLI."""
    registry = get_agent_cli_registry()
    if agent_id not in registry:
        raise ValueError(f"Unknown agent CLI: '{agent_id}'")

    info = registry[agent_id]
    installed = shutil.which(info.binary) is not None
    mcp_registered = False

    for config_path in info.config_paths:
        if config_path.is_file():
            try:
                content = config_path.read_text(encoding="utf-8")
                if "task_agent" in content or "task-agent" in content:
                    mcp_registered = True
                    break
            except Exception:
                pass

    plugin_installed = False
    if info.plugin_path and info.plugin_path.exists():
        try:
            if any("task-agent" in p.name for p in info.plugin_path.iterdir()):
                plugin_installed = True
        except Exception:
            pass

    return {
        "id": info.id,
        "name": info.name,
        "binary": info.binary,
        "description": info.description,
        "installed": installed,
        "mcp_support": info.mcp_support,
        "mcp_registered": mcp_registered,
        "plugin_support": info.plugin_support,
        "plugin_installed": plugin_installed,
        "mcp_command_example": info.mcp_command_example,
        "chat_log_patterns": info.chat_log_patterns,
        "chat_parser_type": info.chat_parser_type,
    }


def inspect_all_agent_clis() -> List[dict]:
    """Inspect local installation status for all registered agent CLIs."""
    registry = get_agent_cli_registry()
    return [inspect_agent_cli(agent_id) for agent_id in registry]


def get_disabled_agent_plugins() -> List[str]:
    """Load list of explicitly disabled agent plugins from task-agent user config."""
    import json

    config_file = Path.home() / ".config" / "task-agent" / "config.json"
    if config_file.is_file():
        try:
            data = json.loads(config_file.read_text(encoding="utf-8"))
            disabled = data.get("plugins", {}).get("disabled_agents", [])
            if isinstance(disabled, list):
                return [str(item) for item in disabled]
        except Exception:
            pass
    return []


def set_agent_plugin_enabled(agent_id: str, enabled: bool) -> None:
    """Enable or disable a specific agent plugin in task-agent user config."""
    import json

    config_dir = Path.home() / ".config" / "task-agent"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.json"

    data: dict = {}
    if config_file.is_file():
        try:
            data = json.loads(config_file.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    plugins_cfg = data.setdefault("plugins", {})
    disabled = plugins_cfg.setdefault("disabled_agents", [])

    if enabled and agent_id in disabled:
        disabled.remove(agent_id)
    elif not enabled and agent_id not in disabled:
        disabled.append(agent_id)

    config_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def is_agent_plugin_enabled(
    agent_id: str, disabled_list: Optional[List[str]] = None
) -> bool:
    """Check if an agent plugin is enabled (enabled by default unless explicitly disabled)."""
    if disabled_list is None:
        disabled_list = get_disabled_agent_plugins()
    return agent_id not in disabled_list
