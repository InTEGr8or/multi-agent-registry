"""Stage 4 of the allowlist pipeline: push canonical rules out per dialect.

Every write is read -> merge -> write, unioning into the existing ``allow``
list rather than replacing it. Hand-added entries survive: the Antigravity
config alone holds bespoke ssh/docker grants no canonical list will ever
contain, and clobbering them would be a silent regression.

A timestamped backup is taken before any file is modified, and ``dry_run`` is
the default -- callers opt in to writing.
"""

from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
import shutil
from typing import List, Optional

from multi_agent_registry.permissions import (
    DEFAULT_TIERS,
    DIALECT_ANTIGRAVITY,
    DIALECT_CLAUDE,
    DIALECT_COPILOT,
    DIALECT_GEMINI_POLICY,
    DIALECT_GROK,
    DIALECT_OPENCODE,
    RENDERERS,
    get_permission_surfaces,
    select_commands,
)

#: Dialects this module can write, and why the others are excluded.
UNPUSHABLE = {
    DIALECT_COPILOT: (
        "no global form exists -- permissions are keyed by absolute directory. "
        "Use --allow-tool or COPILOT_ALLOW_ALL instead."
    ),
    DIALECT_GROK: (
        "covered by the claude push: Grok merges ~/.claude/settings.json rules "
        "into its own rule set, so writing config.toml would duplicate them."
    ),
    DIALECT_ANTIGRAVITY: (
        "matching semantics unconfirmed. If Antigravity matches allow rules by "
        "exact full-string equality (as docs/antigravity.md reports), every "
        "command(x) rendered here is inert and the dialect needs regex: rules "
        "instead. Pushing on the current prefix assumption would add entries "
        "that look applied but grant nothing -- see docs/antigravity.md."
    ),
}


@dataclass
class PushPlan:
    """What a push would change for one agent."""

    agent_id: str
    path: Optional[Path]
    dialect: Optional[str]
    additions: List[str] = field(default_factory=list)
    existing_kept: int = 0
    skipped_reason: str = ""
    written: bool = False
    backup: Optional[Path] = None

    @property
    def pushable(self) -> bool:
        return not self.skipped_reason


def _backup(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = path.with_name(f"{path.name}.mar-backup-{stamp}")
    shutil.copy2(path, dest)
    return dest


def plan_push(agent_id: str, tiers=DEFAULT_TIERS) -> PushPlan:
    """Compute what pushing the canonical allowlist to one agent would add."""
    surfaces = get_permission_surfaces()
    if agent_id not in surfaces:
        raise ValueError(f"No known permission surface for agent: '{agent_id}'")
    surface = surfaces[agent_id]
    plan = PushPlan(agent_id=agent_id, path=surface.path, dialect=surface.dialect)

    if surface.dialect in UNPUSHABLE:
        plan.skipped_reason = UNPUSHABLE[surface.dialect]
        return plan
    if surface.dialect not in RENDERERS:
        plan.skipped_reason = "no renderer for this dialect"
        return plan

    rendered = RENDERERS[surface.dialect](select_commands(tiers))
    desired = sorted(rendered.keys()) if isinstance(rendered, dict) else list(rendered)

    current = _read_allow(surface)
    plan.existing_kept = len(current)
    plan.additions = [e for e in desired if e not in current]
    return plan


def _read_allow(surface) -> List[str]:
    """Current allow entries, in the exact native spelling a merge must match."""
    from multi_agent_registry.permissions import read_current_entries

    return read_current_entries(surface)


def apply_push(agent_id: str, tiers=DEFAULT_TIERS, dry_run: bool = True) -> PushPlan:
    """Merge the canonical allowlist into one agent's global config.

    With ``dry_run`` (the default) nothing is written and the plan is returned
    for inspection.
    """
    plan = plan_push(agent_id, tiers)
    if dry_run or not plan.pushable or not plan.additions:
        return plan

    surface = get_permission_surfaces()[agent_id]
    path = surface.path

    if surface.dialect == DIALECT_GEMINI_POLICY:
        _write_gemini_policy(path, plan)
        return plan

    if not path.is_file():
        plan.skipped_reason = f"no config file at {path}"
        return plan

    plan.backup = _backup(path)
    data = json.loads(path.read_text(encoding="utf-8"))

    if surface.dialect in (DIALECT_CLAUDE, DIALECT_ANTIGRAVITY):
        perms = data.setdefault("permissions", {})
        allow = perms.setdefault("allow", [])
        for entry in plan.additions:
            if entry not in allow:
                allow.append(entry)
    elif surface.dialect == DIALECT_OPENCODE:
        bash = data.setdefault("permission", {}).setdefault("bash", {})
        for entry in plan.additions:
            bash.setdefault(entry, "allow")
    else:  # pragma: no cover - guarded by plan_push
        plan.skipped_reason = "unsupported dialect for write"
        return plan

    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    plan.written = True
    return plan


def _write_gemini_policy(root: Path, plan: PushPlan) -> None:
    """Author a dedicated policy file rather than editing the user's rules.

    gemini-cli reads every ``*.toml`` in the policies directory, so a generated
    file of our own avoids rewriting hand-written rules -- and avoids needing a
    TOML writer, since we author the whole file.
    """
    root.mkdir(parents=True, exist_ok=True)
    dest = root / "mar-canonical.toml"
    if dest.is_file():
        plan.backup = _backup(dest)

    prefixes = ",\n".join(f'    "{p}"' for p in plan.additions)
    dest.write_text(
        "# Generated by `mar permissions push`. Edits here are overwritten.\n"
        "# Hand-written rules belong in a different *.toml in this directory.\n"
        "\n"
        "[[rule]]\n"
        'toolName = "run_shell_command"\n'
        f"commandPrefix = [\n{prefixes}\n]\n"
        'decision = "allow"\n'
        "priority = 50\n",
        encoding="utf-8",
    )
    plan.written = True


def plan_all(tiers=DEFAULT_TIERS) -> List[PushPlan]:
    """Push plans for every agent with a known permission surface."""
    return [plan_push(a, tiers) for a in get_permission_surfaces()]
