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

### Global command allowlist

Every agent expresses "run this without asking" in its own dialect, in a global
config file that is *not* the MCP `config_paths` entry. `permissions.py` holds one
canonical list plus a renderer per dialect.

The list itself is plain text, one command per line, in
`src/multi_agent_registry/allowlist/` — one file per tier. Edit them in any editor;
there are no CRUD commands to learn.

```
src/multi_agent_registry/allowlist/
  inspect.txt    # read-only; mutates nothing
  build.txt      # runs project-defined code (make, pytest)
  network.txt    # network egress (curl) -- opt-in
```

```
# inspect.txt
=pwd           # leading "=" means the bare command only
=date
ls             # no sigil: the command plus any arguments
git log
```

The tier is the filename, so it never repeats on a line. `#` starts a comment,
blank lines are ignored. Only `inspect` and `build` are granted by default.

That `=` is the one piece of syntax, and it exists because the dialects disagree
about matching semantics rather than just spelling: `args="any"` becomes Claude's
`Bash(git log:*)`, OpenCode's `{"git log": "allow", "git log *": "allow"}` pair,
and Gemini's `commandPrefix` entry. Without it every renderer would have to guess
prefix-vs-exact, and they would guess differently.

```python
from multi_agent_registry import (
    load_allowlist, render_for_agent, diff_all_permissions,
)

render_for_agent("claude")   # ['Bash(pwd)', 'Bash(ls:*)', 'Bash(git log:*)', ...]
render_for_agent("agy")      # ['command(pwd)', 'command(ls)', ...]

for d in diff_all_permissions():
    print(d.agent_id, d.surface.scope, len(d.missing))
```

| Agent | Global surface | Dialect |
|---|---|---|
| `claude` | `~/.claude/settings.json` → `permissions.allow` | `Bash(git log:*)` |
| `agy` | `~/.gemini/antigravity-cli/settings.json` → `permissions.allow` | `command(git log)` |
| `opencode` | `~/.config/opencode/opencode.json` → top-level `permission.bash` | `{"git log *": "allow"}` |
| `gemini` | `~/.gemini/policies/*.toml` → `commandPrefix` | `["git log"]` |
| `copilot` | `~/.copilot/permissions-config.json` — **per-directory only** | no global form |

Inspect and diff from the CLI:

```bash
mar permissions                      # every agent, what's missing vs. canonical
mar permissions --agent claude       # one agent
mar permissions --agent agy --render # emit that agent's native block
mar permissions --network            # include the opt-in network tier
```

`mar permissions` is read-only — it never writes to an agent's config.

## Notes for tools built on this library

- Absolute/home-relative `chat_log_patterns` (e.g. `~/.claude/projects/**/*.jsonl`) are scanned once, globally — `search_roots`/`project_dir` only affects patterns relative to a project (e.g. Aider's `**/.aider.chat.history.md`).
- `discover_agent_chats()` shells out to `find` for bare recursive-filename patterns (pruning noise directories natively) rather than `glob.glob(recursive=True)`, which must fully traverse a tree before filtering — orders of magnitude faster on large repo trees.
- Permission surfaces are tracked separately from `config_paths`: for Claude Code the allowlist is in `~/.claude/settings.json` while `config_paths` points at `~/.claude.json`, and Copilot's real config root is `~/.copilot/`, not `~/.config/github-copilot/`.
- Antigravity's `unsandboxed(x)` is a strictly wider grant than `command(x)` — it escapes the terminal sandbox. Renderers emit only `command(x)`, but the diff treats an existing `unsandboxed(x)` as already covering it rather than pushing a redundant grant.
- `get_chat_workspace()`/`get_chat_last_active()` read each agent's actual on-disk message format (e.g. scanning forward past Claude Code's leading metadata-only jsonl lines for the first `cwd`/`timestamp`) rather than assuming a fixed line/file layout.
