"""Canonical global command allowlist and per-agent permission surfaces.

Every agent CLI expresses "this command may run without asking" in its own
dialect, in its own global config file -- none of which are the MCP
``config_paths`` the rest of the registry tracks. This module adds that missing
axis: one canonical list of broadly-safe commands, plus a pure renderer per
dialect that turns it into each agent's native syntax.

Nothing here writes to disk. ``diff_agent_permissions()`` reports what an
agent's global config is missing; applying the result is left to the caller.
"""

import importlib.resources
import json
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

# --- Canonical model ------------------------------------------------------

#: Commands whose whole job is to report state; they mutate nothing.
TIER_INSPECT = "inspect"
#: Commands that execute project-defined code (Makefiles, test runners).
TIER_BUILD = "build"
#: Commands that reach the network.
TIER_NETWORK = "network"
#: Scraped commands awaiting human triage. Deliberately NOT in DEFAULT_TIERS --
#: nothing reaches a real agent config until a person moves it into a real tier.
TIER_REVIEW = "review"

#: Tiers granted unless a caller asks for more.
DEFAULT_TIERS = (TIER_INSPECT, TIER_BUILD)


@dataclass(frozen=True)
class AllowedCommand:
    """One broadly-allowed command in dialect-neutral form.

    ``args`` carries the matching semantics that the dialects disagree about:
    ``"any"`` means the command plus any arguments, ``"none"`` means the bare
    command only. Renderers expand this per dialect rather than guessing.

    Instances come from ``load_allowlist()``, which merges the shipped tier
    files in ``allowlist/`` with the machine-local overlay in
    ``~/.config/multi-agent-registry/allowlist/``; nothing here is hardcoded.
    """

    cmd: str
    args: str = "any"
    tier: str = TIER_INSPECT


#: Tier name -> the file in ``allowlist/`` that defines it.
TIER_FILES = {
    TIER_INSPECT: "inspect.txt",
    TIER_BUILD: "build.txt",
    TIER_NETWORK: "network.txt",
    TIER_REVIEW: "review.txt",
}


def user_allowlist_dir() -> Path:
    """Machine-local canonical overlay.

    Anything carrying a hostname, IP, username, or personal path belongs here
    and never in the shipped ``allowlist/``: that directory is published to
    PyPI inside the wheel, so a machine-specific entry there would be
    permanent and public.
    """
    return Path.home() / ".config" / "multi-agent-registry" / "allowlist"


def parse_allowlist_file(text: str, tier: str) -> List[AllowedCommand]:
    """Parse one tier file: a command per line, ``#`` comments, ``=`` for exact.

    The tier is the filename, so it never has to be repeated on a line.
    """
    commands: List[AllowedCommand] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("="):
            commands.append(AllowedCommand(line[1:].strip(), args="none", tier=tier))
        else:
            commands.append(AllowedCommand(line, args="any", tier=tier))
    return commands


@lru_cache(maxsize=1)
def load_allowlist() -> tuple:
    """The canonical allowlist, read from the tier files in ``allowlist/``.

    Cached, and deliberately not evaluated at import time: a packaging slip
    that loses the data files should break ``mar permissions`` alone, not
    every import of this package.
    """
    commands: List[AllowedCommand] = []
    shipped = importlib.resources.files("multi_agent_registry") / "allowlist"
    overlay = user_allowlist_dir()

    for tier, filename in TIER_FILES.items():
        for root in (shipped, overlay):
            try:
                text = (root / filename).read_text(encoding="utf-8")
            except (FileNotFoundError, OSError, ModuleNotFoundError, NotADirectoryError):
                continue
            commands.extend(parse_allowlist_file(text, tier))

    # Same command from both layers: keep one.
    seen = set()
    unique = []
    for c in commands:
        key = (c.cmd, c.args, c.tier)
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return tuple(unique)


def select_commands(tiers=DEFAULT_TIERS) -> List[AllowedCommand]:
    """Canonical commands limited to the given tiers."""
    wanted = set(tiers)
    return [c for c in load_allowlist() if c.tier in wanted]


# --- Dialects -------------------------------------------------------------

DIALECT_CLAUDE = "claude-settings"
DIALECT_ANTIGRAVITY = "antigravity-settings"
DIALECT_OPENCODE = "opencode-json"
DIALECT_GEMINI_POLICY = "gemini-policy-toml"
DIALECT_COPILOT = "copilot-locations"
DIALECT_GROK = "grok-config-toml"

SCOPE_GLOBAL = "global"
SCOPE_PER_DIRECTORY = "per_directory"
SCOPE_UNSUPPORTED = "unsupported"


@dataclass
class PermissionSurface:
    """Where and how one agent expresses a global command allowlist."""

    agent_id: str
    path: Optional[Path]
    dialect: Optional[str]
    scope: str = SCOPE_UNSUPPORTED
    note: str = ""


def get_permission_surfaces() -> Dict[str, PermissionSurface]:
    """Global permission surfaces, keyed by agent id.

    These are deliberately separate from ``AgentCLIInfo.config_paths``, which
    holds MCP config locations -- for several agents the two are different
    files entirely.
    """
    home = Path.home()
    return {
        "claude": PermissionSurface(
            agent_id="claude",
            path=home / ".claude" / "settings.json",
            dialect=DIALECT_CLAUDE,
            scope=SCOPE_GLOBAL,
            note="permissions.allow; note this is settings.json, not .claude.json",
        ),
        "agy": PermissionSurface(
            agent_id="agy",
            path=home / ".gemini" / "antigravity-cli" / "settings.json",
            dialect=DIALECT_ANTIGRAVITY,
            scope=SCOPE_GLOBAL,
            note="permissions.allow; command(x) grants without escaping the sandbox",
        ),
        "opencode": PermissionSurface(
            agent_id="opencode",
            path=home / ".config" / "opencode" / "opencode.json",
            dialect=DIALECT_OPENCODE,
            scope=SCOPE_GLOBAL,
            note="top-level permission.bash applies to all modes; agent.<mode>.permission does not",
        ),
        "gemini": PermissionSurface(
            agent_id="gemini",
            path=home / ".gemini" / "policies",
            dialect=DIALECT_GEMINI_POLICY,
            scope=SCOPE_GLOBAL,
            note=(
                "gemini-cli policy engine (a directory of *.toml rule files); distinct "
                "from agy despite the shared ~/.gemini root. Rules carrying modes=[...] "
                "are mode-scoped, not global, and are not counted as grants."
            ),
        ),
        "grok": PermissionSurface(
            agent_id="grok",
            path=home / ".grok" / "config.toml",
            dialect=DIALECT_GROK,
            scope=SCOPE_GLOBAL,
            note=(
                "[permission] allow in config.toml. Grok also merges "
                "~/.claude/settings.json rules, so the claude surface already "
                "covers it -- `grok inspect` shows which source is loaded."
            ),
        ),
        "copilot": PermissionSurface(
            agent_id="copilot",
            path=home / ".copilot" / "permissions-config.json",
            dialect=DIALECT_COPILOT,
            scope=SCOPE_PER_DIRECTORY,
            note="keyed by absolute directory; no global form exists. Use --allow-tool or COPILOT_ALLOW_ALL instead",
        ),
    }


# --- Renderers ------------------------------------------------------------
# Pure: canonical commands in, native entries out. No filesystem access.


def render_claude(commands: List[AllowedCommand]) -> List[str]:
    """Claude Code: ``Bash(git log:*)`` -- the ``:*`` is what makes it a prefix."""
    out = []
    for c in commands:
        out.append(f"Bash({c.cmd}:*)" if c.args == "any" else f"Bash({c.cmd})")
    return out


def render_antigravity(commands: List[AllowedCommand]) -> List[str]:
    """Antigravity: ``command(x)`` matches by prefix and keeps the sandbox.

    ``unsandboxed(x)`` is a strictly wider grant -- a sandbox escape -- so it is
    never emitted here even though hand-added entries commonly use it.
    """
    return [f"command({c.cmd})" for c in commands]


def render_opencode(commands: List[AllowedCommand]) -> Dict[str, str]:
    """OpenCode: pattern -> "allow". ``"git log *"`` alone misses bare ``git log``."""
    out: Dict[str, str] = {}
    for c in commands:
        out[c.cmd] = "allow"
        if c.args == "any":
            out[f"{c.cmd} *"] = "allow"
    return out


def render_gemini_policy(commands: List[AllowedCommand]) -> List[str]:
    """gemini-cli policy TOML: a ``commandPrefix`` array, prefix by definition."""
    return [c.cmd for c in commands]


def render_grok(commands: List[AllowedCommand]) -> List[str]:
    """Grok: the same rule strings as Claude Code.

    Grok's docs define ``Bash(git commit:*)`` as prefix matching and
    ``Bash(npm run build)`` as exact, matching Claude's spelling, and it reads
    ``~/.claude/settings.json`` directly -- so one dialect serves both.
    """
    return render_claude(commands)


RENDERERS = {
    DIALECT_CLAUDE: render_claude,
    DIALECT_ANTIGRAVITY: render_antigravity,
    DIALECT_OPENCODE: render_opencode,
    DIALECT_GEMINI_POLICY: render_gemini_policy,
    DIALECT_GROK: render_grok,
}


def render_for_agent(agent_id: str, tiers=DEFAULT_TIERS):
    """Canonical allowlist in one agent's native form, or None if inexpressible."""
    surface = get_permission_surfaces().get(agent_id)
    if surface is None or surface.dialect not in RENDERERS:
        return None
    return RENDERERS[surface.dialect](select_commands(tiers))


# --- Reading what is already on disk --------------------------------------


def surface_exists(surface: PermissionSurface) -> bool:
    """Whether an agent's permission config is present on disk.

    The gemini surface is a directory of rule files; the rest are single files.
    """
    if surface.path is None:
        return False
    if surface.dialect == DIALECT_GEMINI_POLICY:
        if surface.path.is_dir():
            return any(surface.path.glob("*.toml"))
        return surface.path.is_file()
    return surface.path.is_file()


def _read_gemini_policies(root: Path) -> List[str]:
    """Shell-command prefixes granted unconditionally by gemini-cli policy rules.

    Only ``decision = "allow"`` rules for ``run_shell_command`` count, and a rule
    carrying ``modes`` applies in those modes only -- so it is not a global grant.
    """
    files = [root] if root.is_file() else sorted(root.glob("*.toml"))
    entries: List[str] = []
    for f in files:
        try:
            data = tomllib.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for rule in data.get("rule", []):
            if not isinstance(rule, dict):
                continue
            if rule.get("decision") != "allow":
                continue
            if rule.get("toolName") != "run_shell_command":
                continue
            if rule.get("modes"):
                continue  # mode-scoped, therefore not a global grant
            prefixes = rule.get("commandPrefix", [])
            if isinstance(prefixes, str):
                prefixes = [prefixes]
            entries.extend(str(x) for x in prefixes)
    return entries


def read_current_entries(surface: PermissionSurface) -> List[str]:
    """Native allowlist entries currently present in an agent's global config."""
    if not surface_exists(surface):
        return []

    if surface.dialect == DIALECT_GEMINI_POLICY:
        return _read_gemini_policies(surface.path)

    try:
        text = surface.path.read_text(encoding="utf-8")
    except Exception:
        return []

    if surface.dialect == DIALECT_GROK:
        try:
            data = tomllib.loads(text)
        except Exception:
            return []
        allow = data.get("permission", {}).get("allow", [])
        return [str(item) for item in allow] if isinstance(allow, list) else []

    if surface.dialect in (DIALECT_CLAUDE, DIALECT_ANTIGRAVITY):
        try:
            data = json.loads(text)
        except Exception:
            return []
        allow = data.get("permissions", {}).get("allow", [])
        return [str(item) for item in allow] if isinstance(allow, list) else []

    if surface.dialect == DIALECT_OPENCODE:
        try:
            data = json.loads(text)
        except Exception:
            return []
        bash = data.get("permission", {}).get("bash", {})
        return sorted(bash.keys()) if isinstance(bash, dict) else []

    return []


def _satisfies(dialect: str, desired: str, current: List[str]) -> bool:
    """Whether an entry already on disk grants at least what ``desired`` asks.

    Dialects have entries that are strictly wider than the one we render. In
    Antigravity, ``unsandboxed(x)`` grants everything ``command(x)`` does and
    then escapes the sandbox, so it already covers us -- reporting it missing
    would push a redundant second grant into the file.
    """
    if desired in current:
        return True
    if dialect == DIALECT_ANTIGRAVITY and desired.startswith("command("):
        return f"unsandboxed({desired[len('command('):-1]})" in current
    return False


@dataclass
class PermissionDiff:
    """What one agent's global config is missing relative to the canonical list."""

    agent_id: str
    surface: PermissionSurface
    desired: List[str] = field(default_factory=list)
    current: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    extra: List[str] = field(default_factory=list)
    expressible: bool = True


def diff_agent_permissions(agent_id: str, tiers=DEFAULT_TIERS) -> PermissionDiff:
    """Compare an agent's on-disk global allowlist against the canonical list."""
    surfaces = get_permission_surfaces()
    if agent_id not in surfaces:
        raise ValueError(f"No known permission surface for agent: '{agent_id}'")

    surface = surfaces[agent_id]
    if surface.dialect not in RENDERERS or surface.scope != SCOPE_GLOBAL:
        return PermissionDiff(
            agent_id=agent_id, surface=surface, expressible=False
        )

    rendered = RENDERERS[surface.dialect](select_commands(tiers))
    desired = sorted(rendered.keys()) if isinstance(rendered, dict) else list(rendered)
    current = read_current_entries(surface)

    return PermissionDiff(
        agent_id=agent_id,
        surface=surface,
        desired=desired,
        current=current,
        missing=[
            e for e in desired if not _satisfies(surface.dialect, e, current)
        ],
        extra=[e for e in current if e not in desired],
    )


def diff_all_permissions(tiers=DEFAULT_TIERS) -> List[PermissionDiff]:
    """Permission diffs for every agent with a known permission surface."""
    return [diff_agent_permissions(a, tiers) for a in get_permission_surfaces()]
