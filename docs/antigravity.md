# Antigravity CLI (`agy`) & Agent Permissions Guide

This document details the configuration, security architecture, and rules for Google Antigravity CLI (`agy`), registered agents, and subagents.

---

## 1. Permission Architecture Overview

When the Antigravity agent executes shell tools (e.g., `run_command`), the action is evaluated against the granted permission policies before execution:

* **Evaluation Order**: `Deny` &rarr; `Ask` &rarr; `Allow`.
* **Execution Target Format**: The permission engine wraps terminal commands as `command(<command_string>)`.
* **Policy Cache**: In-memory policy cache is loaded when the `agy` session starts. Modifying configuration files directly requires refreshing the cache (via `/permissions` in the CLI) or restarting the session.

---

## 2. Command Matching Mechanics: Strict vs. Regex

Antigravity CLI uses a strict-by-default execution policy:

### A. Non-Regex Matching (Strict Byte-for-Byte Equality)
* Rules that do not start with `regex:` are matched with **exact full-string equality** (`runtime.memequal`).
* Wildcards (`*`) inside non-regex rules (e.g. `command(ssh nuc02 *)`) are treated as **literal asterisks**, not glob patterns, and will fail to match commands with arguments.
* Global wildcard `command(*)` is the only exception that permits all commands unconditionally.

### B. Regex Matching (`regex:`)
* To enable regular expression matching, the **rule string must explicitly start with `regex:`**.
* **Correct**: `regex:(?s)command\(ssh\s+nuc02.*\)`
* **Incorrect**: `command(regex:ssh\s+nuc02.*)` *(evaluated as literal string matching because it starts with `command(`)*.

### C. Multi-line & Newline Handling (`(?s)`)
* Many agent commands span multiple lines or contain embedded newlines (`\n`, `&&`, scripts).
* In regular expressions, the dot `.` matches any character *except* newlines.
* To match multiline commands or scripts, prefix the pattern with the dot-all flag **`(?s)`** (e.g. `regex:(?s)command\(ssh\s+nuc02.*\)`).

---

## 3. Global Execution Policy (`settings.json`)

Global CLI permissions apply machine-wide to all workspaces and sessions launched via `agy`.

* **Config Location**: `~/.gemini/antigravity-cli/settings.json` (on Windows: `%USERPROFILE%\.gemini\antigravity-cli\settings.json`)

### Standard Global Allowlist

```json
{
  "allowNonWorkspaceAccess": true,
  "permissions": {
    "allow": [
      "command(Get-ChildItem)",
      "command(Get-Item windows-tts.exe | Select-Object Name, Length)",
      "command(go build -o windows-tts.exe .)",
      "regex:(?s)command\\(ssh\\s+nuc02.*\\)",
      "regex:(?s).*ssh\\s+nuc02.*",
      "regex:(?s)command\\(git(\\s+--no-pager)?\\s+(add|status|diff|log|show|branch|tag|remote|rev-parse|ls-files|ls-remote|blame|describe|shortlog|cat-file|merge-base).*\\)"
    ]
  }
}
```

#### What is Pre-Approved:
1. **SSH Operations (`ssh nuc02`)**:
   * Matches any command targeting `nuc02`, including piped commands, quoted bash scripts, and multiline statements.
2. **Git Operations**:
   * **Staging**: `git add`
   * **Inspection & Read-Only**: `status`, `diff`, `log`, `show`, `branch`, `tag`, `remote`, `rev-parse`, `ls-files`, `ls-remote`, `blame`, `describe`, `shortlog`, `cat-file`, `merge-base`.
   * **Pager Flags**: Handles invocations with or without `--no-pager`.

---

## 4. Multi-Agent & Agent Registry Governance

Rules for registered agents operate across two distinct layers:

### A. Execution Permissions (Tool Execution Auto-Approval)
* **CLI Subagents (`agy`)**: Any subagent spawned dynamically via `invoke_subagent` or orchestrated by the primary agent inherits the parent CLI session's execution permissions and allowlist from `~/.gemini/antigravity-cli/settings.json`.
* **Registered Manifest Agents**: Custom agents registered in the Agent Registry or defined via manifests can declare their own `commandExecutionPolicy` or allowed tools within their YAML/JSON manifest.
* **Antigravity IDE / Desktop**: Shares global platform permissions managed via `~/.gemini/settings.json`.

### B. Behavioral Guardrails (`AGENTS.md`)
To enforce policy instructions (what agents *should* or *should not* do) across all agents:
* **Global Scope**: `~/.gemini/config/AGENTS.md` (loaded automatically by every orchestrator and subagent across all repositories).
* **Workspace Scope**: `AGENTS.md` or `.agents/rules/*.md` at the project repository root.

#### Example Policy:
```markdown
# Git Execution Policy

- **Authorized**: `git add`, `git status`, and all read-only inspection operations (`git diff`, `git log`, `git show`, `git branch`, `git remote`, `git rev-parse`).
- **Restricted**: Mutating or publishing actions (`git commit`, `git push`, `git reset`, `git rebase`) require explicit confirmation before execution.
```

---

## 5. Management Workflows

### Interactive Permissions Manager (TUI)
You can manage and audit rules at any time within an active `agy` session:
```text
/permissions
```
1. Select **Global** or **Workspace** scope.
2. Navigate between **Allow**, **Ask**, and **Deny** tabs.
3. Press <kbd>A</kbd> to add a new rule.
4. Press <kbd>D</kbd> to remove a rule.

### Reloading After Manual Edits
If you edit `~/.gemini/antigravity-cli/settings.json` manually while `agy` is running:
* Run `/permissions` in the CLI prompt, or
* Restart the CLI session.

---

## 6. Hoover & Ingestion Workflow (Cross-Agent Permission Consolidation)

To prevent fragmented and hyper-specific rules (such as one-off `ssh mstouffer@nuc02 "nohup ..."` commands), commands across all local coding agents (Claude Code, Antigravity CLI, OpenCode, and shell histories) can be swept into an ingestion manifest:

* **Ingestion Manifest**: [`docs/allowlist-ingestion.json`](file:///C:/Users/xgenx/.config/docs/allowlist-ingestion.json) (can be regenerated or overwritten at will).
* **Automation Script**: [`scripts/hoover_allowlist.py`](file:///C:/Users/xgenx/.config/scripts/hoover_allowlist.py)

### Usage

1. **Sweep & Re-generate Ingestion Manifest**:
   ```bash
   python scripts/hoover_allowlist.py
   ```
2. **Review & Bake into Global Allowlist**:
   ```bash
   python scripts/hoover_allowlist.py --apply
   ```

### Generalization Strategy
* **SSH Targets**: Targets known reproducible hosts from `~/.ssh/config` (e.g., `nuc01`, `nuc02`, Tailscale IPs) with a generalized regex:
  ```json
  "regex:(?s)command\\((wsl(\\.exe)?\\s+.*)?ssh\\s+.*(100\\.88\\.63\\.109|100\\.99\\.32\\.117|nuc01|nuc02)\\b.*\\)"
  ```
* **Git Operations**: Generalizes inspect and staging commands across all repositories and subdirectories.
* **Toolchains**: Pre-approves language toolchains (`go`, `cargo`, `uv`, `python`) without allowing unchecked destructive commands.

