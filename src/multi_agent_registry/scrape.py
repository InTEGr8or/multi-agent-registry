"""Stage 1 of the allowlist pipeline: scrape what every agent already allows.

The pipeline is: **scrape** (this module) -> normalize into the canonical
inter-lingua -> hand-edit -> push back out in each agent's own dialect.

Two invariants keep the stages from destroying each other:

* Scrape output is machine-written and may be overwritten on any re-scrape.
  It is never hand-edited.
* The canonical allowlist is hand-edited and is never overwritten by a scrape.
  Normalization merges into it; it does not rewrite it.

Raw scrape output therefore stays on disk as the durable record, under
``~/.local/share/multi-agent-registry/scraped/<agent>.txt`` -- deliberately
outside the repo, which is public, and outside the package, which ships to
PyPI.
"""

from dataclasses import dataclass, field
import json
from pathlib import Path
import tomllib
from typing import Dict, List, Optional

from multi_agent_registry.permissions import (
    DIALECT_ANTIGRAVITY,
    DIALECT_CLAUDE,
    DIALECT_COPILOT,
    DIALECT_GEMINI_POLICY,
    DIALECT_GROK,
    DIALECT_OPENCODE,
    get_permission_surfaces,
)

#: Directories never worth walking when looking for project configs.
PRUNE_DIRS = {
    "node_modules",
    ".venv",
    "venv",
    ".git",
    "__pycache__",
    "dist",
    "build",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
}


def scraped_dir() -> Path:
    """Where raw scrape output lives. Not the repo, not the package."""
    return Path.home() / ".local" / "share" / "multi-agent-registry" / "scraped"


@dataclass
class ScrapedEntry:
    """One native allowlist entry, with where it came from.

    ``sources`` accumulates every config that granted this same entry, so the
    ``.gwt/`` worktrees that duplicate a repo's config collapse to one line.
    """

    agent_id: str
    raw: str
    dialect: str
    sources: List[str] = field(default_factory=list)
    mode_scoped: bool = False
    per_directory: bool = False


@dataclass
class ScrapeStats:
    """What a scrape found, including what it deliberately left behind."""

    files_read: int = 0
    entries: int = 0
    skipped_non_command: int = 0
    skipped_deny_ask: int = 0


# --- per-dialect extraction ----------------------------------------------
# Each returns native allow-entry strings. `allow` only: harvesting a deny or
# ask rule into an allowlist would silently invert it.


def _extract_claude_like(path: Path) -> tuple:
    """Claude Code / Grok-compatible settings.json: ``permissions.allow``."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return [], 0
    perms = data.get("permissions", {})
    if not isinstance(perms, dict):
        return [], 0
    allow = perms.get("allow", [])
    denied = len(perms.get("deny", []) or []) + len(perms.get("ask", []) or [])
    return ([str(x) for x in allow] if isinstance(allow, list) else []), denied


def _extract_grok_toml(path: Path) -> tuple:
    """Grok config.toml: ``[permission] allow``."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return [], 0
    perm = data.get("permission", {})
    if not isinstance(perm, dict):
        return [], 0
    allow = perm.get("allow", [])
    denied = len(perm.get("deny", []) or []) + len(perm.get("ask", []) or [])
    return ([str(x) for x in allow] if isinstance(allow, list) else []), denied


def _extract_opencode(path: Path) -> tuple:
    """OpenCode: top-level ``permission.bash`` plus per-mode blocks.

    Returns (global_entries, mode_scoped_entries, denied_count). A mode-scoped
    grant was allowed *somewhere*, so it is scraped, but tagged -- promoting it
    to a global push would widen it without anyone noticing.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return [], [], 0

    def keys_allowed(block):
        if not isinstance(block, dict):
            return [], 0
        bash = block.get("bash", {})
        if not isinstance(bash, dict):
            return [], 0
        allowed = [k for k, v in bash.items() if v == "allow"]
        other = len([1 for v in bash.values() if v != "allow"])
        return allowed, other

    glob_entries, denied = keys_allowed(data.get("permission", {}))
    mode_entries: List[str] = []
    agents = data.get("agent", {})
    if isinstance(agents, dict):
        for cfg in agents.values():
            if isinstance(cfg, dict):
                got, d = keys_allowed(cfg.get("permission", {}))
                mode_entries.extend(got)
                denied += d
    return glob_entries, mode_entries, denied


def _extract_gemini_policy(path: Path) -> tuple:
    """gemini-cli policy TOML. Mode-scoped rules are tagged, not dropped."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return [], [], 0
    glob_entries: List[str] = []
    mode_entries: List[str] = []
    denied = 0
    for rule in data.get("rule", []):
        if not isinstance(rule, dict):
            continue
        if rule.get("decision") != "allow":
            denied += 1
            continue
        if rule.get("toolName") != "run_shell_command":
            continue
        prefixes = rule.get("commandPrefix", [])
        if isinstance(prefixes, str):
            prefixes = [prefixes]
        target = mode_entries if rule.get("modes") else glob_entries
        target.extend(str(x) for x in prefixes)
    return glob_entries, mode_entries, denied


def _extract_copilot(path: Path) -> tuple:
    """Copilot: ``locations.<abspath>.tool_approvals`` command identifiers.

    Always per-directory -- Copilot has no global form, so these scrape fine
    but push nowhere.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return [], 0
    out: List[str] = []
    other = 0
    for loc in (data.get("locations") or {}).values():
        for approval in (loc or {}).get("tool_approvals", []) or []:
            if approval.get("kind") == "commands":
                out.extend(str(c) for c in approval.get("commandIdentifiers", []))
            else:
                other += 1
    return out, other


# --- project-level discovery ---------------------------------------------

#: Project config filenames that carry allow rules, by dialect.
PROJECT_PATTERNS = {
    DIALECT_CLAUDE: [".claude/settings.json", ".claude/settings.local.json"],
    DIALECT_GROK: [".grok/config.toml"],
    DIALECT_OPENCODE: ["opencode.json", ".opencode/opencode.json"],
}


def find_project_configs(
    dialect: str, search_roots: Optional[List[Path]] = None, max_depth: int = 4
) -> List[Path]:
    """Project-level configs for a dialect, under the given roots.

    "Any repo" in the pipeline description: a command allowed in one project
    is evidence for the canonical list even though the push target is global.
    """
    if search_roots is None:
        search_roots = [Path.home() / "repos"]
    found: List[Path] = []
    for pattern in PROJECT_PATTERNS.get(dialect, []):
        for root in search_roots:
            if not root.is_dir():
                continue
            for candidate in _walk_for(root, pattern, max_depth):
                found.append(candidate)
    return sorted(set(found))


def _walk_for(root: Path, rel_pattern: str, max_depth: int) -> List[Path]:
    """Find ``rel_pattern`` under ``root``, pruning noise directories."""
    hits: List[Path] = []
    root_depth = len(root.parts)

    def walk(d: Path):
        if len(d.parts) - root_depth > max_depth:
            return
        candidate = d / rel_pattern
        if candidate.is_file():
            hits.append(candidate)
        try:
            for child in d.iterdir():
                if child.is_dir() and not child.is_symlink():
                    if child.name in PRUNE_DIRS:
                        continue
                    walk(child)
        except (PermissionError, OSError):
            return

    walk(root)
    return hits


# --- the scrape ----------------------------------------------------------


def scrape_agent(
    agent_id: str, search_roots: Optional[List[Path]] = None
) -> tuple:
    """Every allow entry for one agent, global and project-level.

    Returns ``(entries, stats)``. Entries are deduplicated by raw string, with
    every granting config recorded in ``sources``.
    """
    surfaces = get_permission_surfaces()
    if agent_id not in surfaces:
        raise ValueError(f"No known permission surface for agent: '{agent_id}'")
    surface = surfaces[agent_id]
    dialect = surface.dialect
    stats = ScrapeStats()
    by_raw: Dict[str, ScrapedEntry] = {}

    def record(raw: str, source: Path, mode_scoped=False, per_directory=False):
        raw = raw.strip()
        if not raw:
            return
        entry = by_raw.get(raw)
        if entry is None:
            entry = ScrapedEntry(
                agent_id=agent_id,
                raw=raw,
                dialect=dialect,
                mode_scoped=mode_scoped,
                per_directory=per_directory,
            )
            by_raw[raw] = entry
        src = _collapse_source(source)
        if src not in entry.sources:
            entry.sources.append(src)

    paths = []
    if surface.path is not None:
        if dialect == DIALECT_GEMINI_POLICY and surface.path.is_dir():
            paths.extend(sorted(surface.path.glob("*.toml")))
        elif surface.path.is_file():
            paths.append(surface.path)
    paths.extend(find_project_configs(dialect, search_roots))

    for path in paths:
        stats.files_read += 1
        if dialect in (DIALECT_CLAUDE, DIALECT_ANTIGRAVITY):
            entries, denied = _extract_claude_like(path)
            stats.skipped_deny_ask += denied
            for e in entries:
                record(e, path)
        elif dialect == DIALECT_GROK:
            if path.suffix == ".toml":
                entries, denied = _extract_grok_toml(path)
            else:
                entries, denied = _extract_claude_like(path)
            stats.skipped_deny_ask += denied
            for e in entries:
                record(e, path)
        elif dialect == DIALECT_OPENCODE:
            glob_e, mode_e, denied = _extract_opencode(path)
            stats.skipped_deny_ask += denied
            for e in glob_e:
                record(e, path)
            for e in mode_e:
                record(e, path, mode_scoped=True)
        elif dialect == DIALECT_GEMINI_POLICY:
            glob_e, mode_e, denied = _extract_gemini_policy(path)
            stats.skipped_deny_ask += denied
            for e in glob_e:
                record(e, path)
            for e in mode_e:
                record(e, path, mode_scoped=True)
        elif dialect == DIALECT_COPILOT:
            entries, other = _extract_copilot(path)
            stats.skipped_non_command += other
            for e in entries:
                record(e, path, per_directory=True)

    stats.entries = len(by_raw)
    return sorted(by_raw.values(), key=lambda e: e.raw), stats


def _collapse_source(path: Path) -> str:
    """Home-relative path, with ``.gwt/<branch>`` worktrees collapsed.

    A repo with eight worktrees otherwise contributes eight identical sources.
    """
    try:
        rel = f"~/{path.relative_to(Path.home())}"
    except ValueError:
        rel = str(path)
    parts = rel.split("/")
    if ".gwt" in parts:
        i = parts.index(".gwt")
        parts = parts[:i] + [".gwt/*"] + parts[i + 2 :]
        rel = "/".join(parts)
    return rel


def write_scraped(agent_id: str, entries: List[ScrapedEntry], stats: ScrapeStats) -> Path:
    """Write the raw scrape for one agent. Overwrites any previous scrape.

    This file is the durable record of what was found; normalization reads it
    and never deletes it.
    """
    out_dir = scraped_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{agent_id}.txt"

    lines = [
        f"# Raw allowlist scrape for '{agent_id}' -- machine-written, do not hand-edit.",
        "# Regenerate with: mar permissions scrape",
        f"# {stats.files_read} config file(s) read, {stats.entries} distinct entries.",
        "#",
        "# Format: <native entry><TAB># sources",
        "",
    ]
    for e in entries:
        tags = []
        if e.mode_scoped:
            tags.append("mode-scoped")
        if e.per_directory:
            tags.append("per-directory")
        tag = f" [{', '.join(tags)}]" if tags else ""
        lines.append(f"{e.raw}\t# {', '.join(e.sources)}{tag}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def read_scraped(agent_id: str) -> List[str]:
    """Native entries from a previous scrape, or [] if never scraped."""
    path = scraped_dir() / f"{agent_id}.txt"
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        entries.append(line.split("\t", 1)[0].strip())
    return entries
