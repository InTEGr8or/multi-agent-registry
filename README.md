# Multi-Agent Registry 🤖

Unified detection, configuration, plugin, and chat history discovery registry for AI coding agent CLIs.

`multi_agent_registry` gives any tool a single place to ask "which AI coding agents are installed on this machine, where do they keep their config/plugins, and where did they leave their chat history?" — instead of every consumer re-implementing per-agent path guessing.

---

## Installation

```bash
pip install multi-agent-registry
# or using uv
uv add multi-agent-registry
```

The PyPI **distribution** name is `multi-agent-registry`; the importable **module** name is `multi_agent_registry`:

```python
import multi_agent_registry
```

## Features

- **Multi-Agent CLI Detection**: A registry of 15 agent CLIs — Claude Code, Antigravity (`agy`), OpenCode, GitHub Copilot, Grok Build, Cursor, Windsurf, Aider, Codex, Continue, Cline, Roo Code, Goose, ShellGPT, and Open Interpreter — with binary name, description, and config paths for each.
- **Installation & MCP Inspection**: `inspect_agent_cli()`/`inspect_all_agent_clis()` check whether each agent's binary is on `PATH`, whether it's registered as an MCP server, and whether a plugin is installed for it.
- **Chat Log Discovery**: `discover_agent_chats()` scans the on-disk chat log locations for agents that expose them (currently Claude Code, Antigravity, OpenCode, Aider, Cline, and Roo Code), with recursive-glob patterns pruned to skip `node_modules`/`.venv`/`.git`/`.gwt` for speed.
- **Chat Inspection Helpers**: `get_chat_workspace()` and `get_chat_last_active()` read each agent's own on-disk format to resolve which project a chat belongs to and when it was truly last active (not just file mtime).
- **Plugin Enable/Disable State**: Per-agent plugin opt-out, persisted to `~/.config/task-agent/config.json`, for tools that install agent-specific plugins/skills.

## Quickstart

```python
from multi_agent_registry import get_agent_cli_registry, discover_agent_chats, get_chat_workspace

# What agents does this machine have?
for agent_id, info in get_agent_cli_registry().items():
    print(agent_id, info.name, info.binary)

# Where has Claude Code been chatting, and about which projects?
for chat in discover_agent_chats(agent_id="claude"):
    workspace = get_chat_workspace(chat)
    print(chat.path, "->", workspace)
```

## API Reference

### Registry & detection

```python
from multi_agent_registry import AgentCLIInfo, get_agent_cli_registry, inspect_agent_cli, inspect_all_agent_clis

registry: dict[str, AgentCLIInfo] = get_agent_cli_registry()
info = registry["claude"]
info.id, info.name, info.binary, info.description
info.config_paths        # list[Path] of possible config file locations
info.mcp_support, info.mcp_command_example
info.plugin_support, info.plugin_path, info.skills_path, info.plugin_template
info.chat_log_patterns   # list[str] glob patterns, [] if not yet supported
info.chat_parser_type    # "json" | "jsonl" | "markdown"

status = inspect_agent_cli("claude")   # dict: installed, mcp_registered, plugin_installed, ...
all_status = inspect_all_agent_clis()  # same, for every registered agent
```

### Chat discovery

```python
from multi_agent_registry import DiscoveredChat, discover_agent_chats
from pathlib import Path

# All chats for one agent, scanned globally (patterns rooted at ~ or /)
# or within specific project roots (patterns relative to a project).
chats: list[DiscoveredChat] = discover_agent_chats(
    agent_id="aider",                                   # omit to scan every agent
    search_roots=[Path.home() / "repos"],                # only used for project-relative patterns
)
# chat.agent_id, chat.path, chat.parser_type
```

Agents currently wired up for chat discovery: `claude`, `agy` (Antigravity), `opencode`, `aider`, `cline`, `roo`. The rest are registered for detection/config/plugin purposes but don't yet have `chat_log_patterns` populated — contributions welcome.

### Chat inspection

```python
from multi_agent_registry import get_chat_workspace, get_chat_last_active

get_chat_workspace(chat)     # -> Path | None, the project dir the chat belongs to
get_chat_last_active(chat)   # -> datetime | None, true last-message time (jsonl only for now);
                              #    callers should fall back to file mtime when None
```

## Notes for tools built on this library

- Absolute/home-relative `chat_log_patterns` (e.g. `~/.claude/projects/**/*.jsonl`) are scanned once, globally — `search_roots`/`project_dir` only affects patterns relative to a project (e.g. Aider's `**/.aider.chat.history.md`).
- `discover_agent_chats()` shells out to `find` for bare recursive-filename patterns (pruning noise directories natively) rather than `glob.glob(recursive=True)`, which must fully traverse a tree before filtering — orders of magnitude faster on large repo trees.
- `get_chat_workspace()`/`get_chat_last_active()` read each agent's actual on-disk message format (e.g. scanning forward past Claude Code's leading metadata-only jsonl lines for the first `cwd`/`timestamp`) rather than assuming a fixed line/file layout.
