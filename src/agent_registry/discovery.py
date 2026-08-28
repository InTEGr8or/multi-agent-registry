"""Discovery module for scanning agent chat log files."""

from dataclasses import dataclass
from datetime import datetime
import fnmatch
import glob
import json
import os
import re
import subprocess
from pathlib import Path
from typing import List, Optional

from agent_registry.registry import AgentCLIInfo, get_agent_cli_registry

EXCLUDED_DIR_NAMES = {"node_modules", ".venv", ".git", ".gwt"}


def _resolve_host_root(project_dir: Path) -> Path:
    """Resolve project directory host root, unwrapping .gwt/<slug> worktrees if present."""
    try:
        from taskagent.store_registry import project_host_root

        return project_host_root(project_dir)
    except ImportError:
        resolved = project_dir.resolve()
        if ".gwt" in resolved.parts:
            try:
                idx = list(resolved.parts).index(".gwt")
                return Path(*resolved.parts[:idx])
            except ValueError:
                pass
        return resolved


@dataclass
class DiscoveredChat:
    """Represents a discovered agent chat log file."""

    agent_id: str
    path: Path
    parser_type: str


def _is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_DIR_NAMES for part in path.parts)


def _find_recursive(host_root: Path, filename: str) -> List[str]:
    prune_expr = []
    for name in EXCLUDED_DIR_NAMES:
        if prune_expr:
            prune_expr.append("-o")
        prune_expr += ["-name", name]

    cmd = (
        ["find", str(host_root), "("] + prune_expr + [")", "-prune", "-o"]
        + ["-type", "f", "-name", filename, "-print"]
    )
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return [line for line in result.stdout.splitlines() if line.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        matched = []
        for root, dirnames, filenames in os.walk(host_root):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIR_NAMES]
            for name in filenames:
                if fnmatch.fnmatch(name, filename):
                    matched.append(os.path.join(root, name))
        return matched


def _expand_pattern(pattern: str, host_root: Path) -> List[Path]:
    if pattern.startswith("~"):
        expanded = str(Path(pattern).expanduser())
        matched = glob.glob(expanded, recursive=True)
    elif pattern.startswith("/"):
        matched = glob.glob(pattern, recursive=True)
    else:
        if not host_root.exists():
            return []
        if pattern.startswith("**/") and "/" not in pattern[3:]:
            # A bare recursive filename match (e.g. Aider's
            # "**/.aider.chat.history.md"). glob.glob(recursive=True) must
            # fully traverse every directory -- including huge
            # node_modules/.venv trees -- before results can be filtered
            # out, and even a pruning os.walk is too slow in pure Python
            # over large repo trees (seconds -> minutes). Shell out to
            # `find`, which prunes natively and is ~1000x faster in
            # practice; fall back to a pruning walk if `find` is missing.
            filename = pattern[3:]
            matched = _find_recursive(host_root, filename)
        else:
            joined = str(host_root / pattern)
            matched = glob.glob(joined, recursive=True)

    results: List[Path] = []
    for match in matched:
        p = Path(match)
        if p.is_file() and not _is_excluded(p):
            results.append(p)
    return results


def discover_agent_chats(
    agent_id: Optional[str] = None,
    project_dir: Optional[Path] = None,
    search_roots: Optional[List[Path]] = None,
) -> List[DiscoveredChat]:
    """Discover chat log files for one or all registered agent CLIs.

    Absolute/home-relative patterns (e.g. ``~/.claude/projects/**/*.jsonl``)
    are scanned once, independent of any root. Patterns relative to a
    project (e.g. Aider's ``**/.aider.chat.history.md``) are joined against
    each of ``search_roots`` when given, or a single resolved
    ``project_dir``/cwd otherwise. Recursive scans skip noise directories
    (``node_modules``, ``.venv``, ``.git``, ``.gwt``).
    """
    registry = get_agent_cli_registry()

    if agent_id is not None:
        if agent_id not in registry:
            raise ValueError(f"Unknown agent CLI: '{agent_id}'")
        agents_to_scan: List[AgentCLIInfo] = [registry[agent_id]]
    else:
        agents_to_scan = list(registry.values())

    if search_roots:
        host_roots = [_resolve_host_root(r) for r in search_roots]
    else:
        if project_dir is None:
            project_dir = Path.cwd()
        host_roots = [_resolve_host_root(project_dir)]

    discovered: List[DiscoveredChat] = []
    seen_paths = set()

    for agent in agents_to_scan:
        if not agent.chat_log_patterns:
            continue

        for pattern in agent.chat_log_patterns:
            is_rooted = pattern.startswith("~") or pattern.startswith("/")
            roots_to_try = [host_roots[0]] if is_rooted else host_roots

            for host_root in roots_to_try:
                found_paths = _expand_pattern(pattern, host_root)
                for path in found_paths:
                    resolved = path.resolve()
                    if resolved not in seen_paths:
                        seen_paths.add(resolved)
                        discovered.append(
                            DiscoveredChat(
                                agent_id=agent.id,
                                path=path,
                                parser_type=agent.chat_parser_type,
                            )
                        )

    discovered.sort(key=lambda item: item.path)
    return discovered


def get_chat_workspace(chat: DiscoveredChat) -> Optional[Path]:
    """Best-effort resolution of which project/repo a discovered chat belongs to.

    Reads the on-disk structure each agent uses to record its working
    directory, rather than relying on the chat file's own location.
    """
    try:
        if chat.parser_type == "jsonl":
            # Leading lines are often session metadata (mode, snapshots) with
            # no `cwd` field; scan forward (capped) for the first one that
            # has it rather than assuming line 1.
            with open(chat.path, "r") as f:
                for _, line in zip(range(200), f):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    cwd = data.get("cwd")
                    if cwd:
                        return Path(cwd)
        elif chat.parser_type == "markdown":
            return chat.path.parent
        elif chat.parser_type == "json":
            with open(chat.path, "r") as f:
                content = f.read(10000)
            match = re.search(r"Current Workspace Directory \((.*?)\)", content)
            if match:
                return Path(match.group(1))
    except Exception:
        pass
    return None


def get_chat_last_active(chat: DiscoveredChat) -> Optional[datetime]:
    """Best-effort true last-active timestamp for a chat log.

    Scans per-message timestamps rather than trusting file mtime, which can
    be misleading (e.g. a metadata-only stub rewritten without new
    messages). Returns None when the format isn't understood yet, in which
    case callers should fall back to file mtime.
    """
    try:
        if chat.parser_type == "jsonl":
            last_ts = None
            with open(chat.path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = data.get("timestamp")
                    if not ts:
                        continue
                    try:
                        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    if last_ts is None or parsed > last_ts:
                        last_ts = parsed
            return last_ts
    except Exception:
        pass
    return None
