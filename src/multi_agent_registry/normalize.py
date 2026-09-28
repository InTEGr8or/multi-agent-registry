"""Stage 2 of the allowlist pipeline: native entries -> canonical inter-lingua.

Parsing is the inverse of ``permissions.RENDERERS``; simplification is what
makes the result shorter than the input. A scrape turns up hyper-specific
entries -- ``git --no-pager log -n 10 --oneline --graph --all`` -- because
several dialects match exactly and a person had to spell each variant out.
Collapsing those to their command head is the whole point of the stage.

Simplification is deliberately conservative. Anything whose generalization
would widen a grant in a way worth a second look lands in the ``review`` tier,
which is not in ``DEFAULT_TIERS`` and so never reaches an agent config until a
person moves it into a real tier.
"""

from dataclasses import dataclass, field
import re
from typing import Dict, List, Optional, Tuple

from multi_agent_registry.permissions import (
    DIALECT_ANTIGRAVITY,
    DIALECT_CLAUDE,
    DIALECT_COPILOT,
    DIALECT_GEMINI_POLICY,
    DIALECT_GROK,
    DIALECT_OPENCODE,
    TIER_REVIEW,
    AllowedCommand,
    load_allowlist,
)
from multi_agent_registry.scrape import ScrapedEntry

# --- native -> canonical --------------------------------------------------

#: Claude/Grok rule prefixes that are not shell commands.
_NON_COMMAND_RE = re.compile(
    r"^(Edit|Read|Write|Glob|Grep|WebFetch|WebSearch|Task|Artifact|NotebookEdit"
    r"|TodoWrite|MCPTool|mcp__)"
)


def parse_native(dialect: str, raw: str) -> Tuple[Optional[str], Optional[str]]:
    """One native entry -> (command string, skip reason).

    Exactly one of the two is None. A skip reason is returned rather than
    silently dropping the entry, so a caller can report what it left behind.
    """
    raw = raw.strip()
    if not raw:
        return None, "empty"

    if dialect in (DIALECT_CLAUDE, DIALECT_GROK):
        if raw.startswith("Bash(") and raw.endswith(")"):
            inner = raw[len("Bash(") : -1].strip()
            if inner.endswith(":*"):
                inner = inner[:-2].strip()
            elif inner.endswith(" *"):
                inner = inner[:-2].strip()
            elif inner == "*":
                return None, "wildcard-all"
            return (inner or None), (None if inner else "empty")
        if _NON_COMMAND_RE.match(raw):
            return None, "non-command rule"
        return None, "unrecognized"

    if dialect == DIALECT_ANTIGRAVITY:
        for wrapper in ("unsandboxed(", "command("):
            if raw.startswith(wrapper) and raw.endswith(")"):
                inner = raw[len(wrapper) : -1].strip()
                if inner == "*":
                    return None, "wildcard-all"
                return (inner or None), (None if inner else "empty")
        if raw.startswith("mcp(") or raw.startswith("regex:"):
            return None, "non-command rule"
        return None, "unrecognized"

    if dialect == DIALECT_OPENCODE:
        inner = raw[:-2].strip() if raw.endswith(" *") else raw
        if inner == "*":
            return None, "wildcard-all"
        return (inner or None), (None if inner else "empty")

    if dialect in (DIALECT_GEMINI_POLICY, DIALECT_COPILOT):
        return (raw or None), None

    return None, f"unknown dialect {dialect}"


# --- simplification -------------------------------------------------------

#: Commands whose second word is a subcommand worth keeping (``git log``).
TWO_WORD_HEADS = {
    "git", "docker", "gh", "aws", "cargo", "kubectl", "gcloud", "systemctl",
    "apt", "apt-get", "brew", "terraform", "tailscale", "go", "pip", "pip3",
    "poetry", "uv", "npm", "pnpm", "yarn", "helm", "podman", "flatpak",
}

#: Pairs whose third word matters too (``uv run pytest``).
THREE_WORD_HEADS = {
    ("uv", "run"), ("npm", "run"), ("pnpm", "run"), ("yarn", "run"),
    ("python", "-m"), ("python3", "-m"), ("uv", "tool"), ("cargo", "run"),
}

_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
#: Shell metacharacters that mean the entry is more than one command.
_COMPOUND_RE = re.compile(r"(&&|\|\||[|;>]|\$\(|`)")


@dataclass
class Simplified:
    """A command head plus why it may need a human look."""

    head: str
    needs_review: bool = False
    reasons: List[str] = field(default_factory=list)


def simplify_command(cmd: str) -> Simplified:
    """Reduce a fully-specified command to the head worth allowlisting.

    ``git --no-pager log -n 10 --oneline --graph --all`` -> ``git log``.
    """
    reasons: List[str] = []
    original = cmd.strip()

    # Leading VAR=value assignments are environment, not the command.
    tokens = original.split()
    while tokens and _ENV_ASSIGN_RE.match(tokens[0]):
        tokens.pop(0)
    if not tokens:
        return Simplified(original, True, ["no command after environment"])

    if _COMPOUND_RE.search(original):
        reasons.append("compound command")
    if '"' in original or "'" in original:
        reasons.append("quoted argument")

    # ssh carries a remote command; collapsing it grants arbitrary remote
    # execution, so it never generalizes silently.
    base = tokens[0].split("/")[-1]
    if base in ("ssh", "scp", "rsync"):
        reasons.append(f"{base}: remote execution")

    if "/" in tokens[0] or tokens[0].startswith("."):
        reasons.append("path-qualified binary")

    words = [tok for tok in tokens if not tok.startswith("-")]
    if not words:
        return Simplified(tokens[0], True, reasons + ["flags only"])

    # A three-word head may include a meaningful flag (``python3 -m pytest``),
    # so match it against the raw tokens before flags are filtered out.
    if tuple(tokens[:2]) in THREE_WORD_HEADS:
        rest = [tok for tok in tokens[2:] if not tok.startswith("-")]
        head = " ".join(tokens[:2] + rest[:1])
    elif words[0] in TWO_WORD_HEADS and len(words) >= 2:
        head = " ".join(words[:2])
    else:
        head = words[0]

    return Simplified(head, bool(reasons), reasons)


# --- the normalize step ---------------------------------------------------


@dataclass
class NormalizeResult:
    """Counts at every stage, plus what came out and what was set aside."""

    raw: int = 0
    parsed: int = 0
    skipped: Dict[str, int] = field(default_factory=dict)
    simplified: List[AllowedCommand] = field(default_factory=list)
    review: List[AllowedCommand] = field(default_factory=list)
    already_canonical: int = 0
    provenance: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def new_count(self) -> int:
        return len(self.simplified) + len(self.review)


def normalize_entries(entries: List[ScrapedEntry]) -> NormalizeResult:
    """Scraped native entries -> deduplicated canonical commands.

    Everything new lands in the ``review`` tier: a scrape cannot know whether
    a command is inspection, build, or network, and guessing would put an
    unreviewed command into a tier that gets pushed.
    """
    result = NormalizeResult(raw=len(entries))
    known = {c.cmd for c in load_allowlist()}
    seen: Dict[str, Simplified] = {}

    for entry in entries:
        cmd, reason = parse_native(entry.dialect, entry.raw)
        if cmd is None:
            result.skipped[reason or "unknown"] = (
                result.skipped.get(reason or "unknown", 0) + 1
            )
            continue
        result.parsed += 1

        simple = simplify_command(cmd)
        if not simple.head:
            continue

        prov = result.provenance.setdefault(simple.head, [])
        for src in entry.sources:
            tag = f"{entry.agent_id}:{src}"
            if tag not in prov:
                prov.append(tag)

        if simple.head in known:
            result.already_canonical += 1
            continue

        prior = seen.get(simple.head)
        if prior is None:
            seen[simple.head] = simple
        elif simple.needs_review and not prior.needs_review:
            # Any variant needing review taints the head.
            seen[simple.head] = simple

    for head, simple in sorted(seen.items()):
        cmd = AllowedCommand(head, args="any", tier=TIER_REVIEW)
        (result.review if simple.needs_review else result.simplified).append(cmd)

    return result


def merge_into_review(result: NormalizeResult, dest_dir) -> Tuple[int, object]:
    """Append new canonical entries to the machine-local ``review.txt``.

    Appends only. The canonical files are hand-edited, so normalization never
    rewrites a line it did not add -- a re-scrape cannot clobber an edit.
    """
    from pathlib import Path

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / "review.txt"

    existing_text = path.read_text(encoding="utf-8") if path.is_file() else ""
    existing = {
        line.split("#", 1)[0].strip().lstrip("=").strip()
        for line in existing_text.splitlines()
        if line.split("#", 1)[0].strip()
    }

    additions: List[str] = []
    for cmd in result.simplified + result.review:
        if cmd.cmd in existing:
            continue
        prov = result.provenance.get(cmd.cmd, [])
        note = f"  # {prov[0]}" if prov else ""
        extra = len(prov) - 1
        if extra > 0:
            note += f" (+{extra} more)"
        additions.append(f"{cmd.cmd}{note}")

    if not additions:
        return 0, path

    header = ""
    if not existing_text:
        header = (
            "# Scraped commands awaiting triage. NOT granted to any agent --\n"
            "# the 'review' tier is excluded from DEFAULT_TIERS on purpose.\n"
            "# Move a line into inspect.txt / build.txt / network.txt to grant it.\n"
            "# Regenerate candidates with: mar permissions normalize\n\n"
        )
    with path.open("a", encoding="utf-8") as f:
        if header:
            f.write(header)
        f.write("\n".join(additions) + "\n")
    return len(additions), path
