"""Discovery module for scanning agent chat log files."""

from dataclasses import dataclass
import glob
from pathlib import Path
from typing import List, Optional

from agent_registry.registry import AgentCLIInfo, get_agent_cli_registry


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


def _expand_pattern(pattern: str, host_root: Path) -> List[Path]:
    if pattern.startswith("~"):
        expanded = str(Path(pattern).expanduser())
        matched = glob.glob(expanded, recursive=True)
    elif pattern.startswith("/"):
        matched = glob.glob(pattern, recursive=True)
    else:
        joined = str(host_root / pattern)
        matched = glob.glob(joined, recursive=True)

    results: List[Path] = []
    for match in matched:
        p = Path(match)
        if p.is_file():
            results.append(p)
    return results


def discover_agent_chats(
    agent_id: Optional[str] = None,
    project_dir: Optional[Path] = None,
) -> List[DiscoveredChat]:
    registry = get_agent_cli_registry()

    if agent_id is not None:
        if agent_id not in registry:
            raise ValueError(f"Unknown agent CLI: '{agent_id}'")
        agents_to_scan: List[AgentCLIInfo] = [registry[agent_id]]
    else:
        agents_to_scan = list(registry.values())

    if project_dir is None:
        project_dir = Path.cwd()

    host_root = _resolve_host_root(project_dir)

    discovered: List[DiscoveredChat] = []
    seen_paths = set()

    for agent in agents_to_scan:
        if not agent.chat_log_patterns:
            continue

        for pattern in agent.chat_log_patterns:
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
