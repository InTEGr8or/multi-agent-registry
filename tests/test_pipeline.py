"""Tests for the scrape -> normalize -> push allowlist pipeline."""

import json

import pytest

from multi_agent_registry.normalize import (
    merge_into_review,
    normalize_entries,
    parse_native,
    simplify_command,
)
from multi_agent_registry.permissions import (
    DEFAULT_TIERS,
    DIALECT_ANTIGRAVITY,
    DIALECT_CLAUDE,
    DIALECT_GROK,
    RENDERERS,
    TIER_REVIEW,
    get_permission_surfaces,
    select_commands,
    user_allowlist_dir,
)
from multi_agent_registry.push import UNPUSHABLE, apply_push, plan_push
from multi_agent_registry.scrape import (
    ScrapedEntry,
    _collapse_source,
    _extract_claude_like,
    _extract_gemini_policy,
    _extract_opencode,
    scrape_agent,
    scraped_dir,
)


# --- storage safety -------------------------------------------------------


def test_scrape_output_never_lands_in_the_repo_or_package():
    """Scraped data is machine-specific; the repo is public and the package
    ships to PyPI, so neither may ever hold it."""
    d = str(scraped_dir())
    assert "multi-agent-registry/src" not in d
    assert "repos/multi-agent-registry" not in d
    assert d.endswith("share/multi-agent-registry/scraped")


def test_machine_local_overlay_is_outside_the_package():
    assert "site-packages" not in str(user_allowlist_dir())
    assert str(user_allowlist_dir()).startswith(str(__import__("pathlib").Path.home()))


def test_review_tier_is_never_granted_by_default():
    assert TIER_REVIEW not in DEFAULT_TIERS
    assert TIER_REVIEW not in {c.tier for c in select_commands(DEFAULT_TIERS)}


# --- parsers: the inverse of the renderers --------------------------------


@pytest.mark.parametrize("dialect", list(RENDERERS))
def test_render_then_parse_round_trips(dialect):
    """Every canonical command survives render -> parse for every dialect."""
    commands = select_commands(DEFAULT_TIERS)
    rendered = RENDERERS[dialect](commands)
    entries = list(rendered.keys()) if isinstance(rendered, dict) else rendered

    recovered = set()
    for entry in entries:
        cmd, _ = parse_native(dialect, entry)
        if cmd:
            recovered.add(cmd)

    for c in commands:
        assert c.cmd in recovered, f"{dialect} lost {c.cmd}"


def test_claude_parser_strips_both_prefix_spellings():
    assert parse_native(DIALECT_CLAUDE, "Bash(git log:*)")[0] == "git log"
    assert parse_native(DIALECT_CLAUDE, "Bash(aws lambda *)")[0] == "aws lambda"
    assert parse_native(DIALECT_CLAUDE, "Bash(pwd)")[0] == "pwd"


def test_claude_parser_reports_non_command_rules_rather_than_dropping():
    for rule in ("Edit(**/x)", "Read", "WebFetch", "mcp__linear__get", "Artifact"):
        cmd, reason = parse_native(DIALECT_CLAUDE, rule)
        assert cmd is None
        assert reason == "non-command rule"


def test_antigravity_parser_handles_both_wrappers():
    assert parse_native(DIALECT_ANTIGRAVITY, "command(ls)")[0] == "ls"
    assert parse_native(DIALECT_ANTIGRAVITY, "unsandboxed(git log)")[0] == "git log"
    assert parse_native(DIALECT_ANTIGRAVITY, "mcp(ta/list)")[1] == "non-command rule"


def test_wildcard_all_is_not_treated_as_a_command():
    assert parse_native(DIALECT_ANTIGRAVITY, "command(*)")[1] == "wildcard-all"
    assert parse_native(DIALECT_CLAUDE, "Bash(*)")[1] == "wildcard-all"


def test_grok_parses_with_the_claude_dialect():
    assert parse_native(DIALECT_GROK, "Bash(cargo test *)")[0] == "cargo test"


# --- simplification -------------------------------------------------------


def test_hyperspecific_git_command_collapses_to_its_head():
    r = simplify_command("git --no-pager log -n 10 --oneline --graph --all")
    assert r.head == "git log"
    assert not r.needs_review


def test_meaningful_flag_is_kept_in_a_three_word_head():
    assert simplify_command("python3 -m pytest tests/ -x -q").head == "python3 -m pytest"


def test_env_assignments_are_stripped_before_the_head():
    assert simplify_command("AWS_PROFILE=x uv run cocli campaign").head == "uv run cocli"


def test_ssh_with_a_remote_command_always_needs_review():
    """Collapsing this would grant arbitrary remote execution."""
    r = simplify_command('ssh nuc01 "rm -rf /"')
    assert r.needs_review
    assert any("remote execution" in x for x in r.reasons)


def test_scp_and_rsync_also_need_review():
    assert simplify_command("scp a b:/c").needs_review
    assert simplify_command("rsync -a x host:/y").needs_review


def test_path_qualified_binary_needs_review():
    r = simplify_command(".venv/bin/python3 -m cocli.main render")
    assert r.needs_review
    assert "path-qualified binary" in r.reasons


def test_compound_command_needs_review():
    assert simplify_command("make test && rm -rf build").needs_review
    assert simplify_command("cat x | sh").needs_review


def test_two_word_head_keeps_the_subcommand():
    assert simplify_command("aws logs describe-log-streams").head == "aws logs"
    assert simplify_command("docker compose up -d").head == "docker compose"


def test_unknown_single_command_keeps_just_the_binary():
    assert simplify_command("make test").head == "make"


# --- scrape extraction ----------------------------------------------------


def test_deny_and_ask_rules_are_never_harvested(tmp_path):
    """Harvesting a deny rule into an allowlist would invert it."""
    cfg = tmp_path / "settings.json"
    cfg.write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": ["Bash(ls:*)"],
                    "deny": ["Bash(rm -rf *)"],
                    "ask": ["Bash(git push:*)"],
                }
            }
        )
    )
    entries, denied = _extract_claude_like(cfg)
    assert entries == ["Bash(ls:*)"]
    assert denied == 2


def test_opencode_mode_scoped_grants_are_tagged_not_merged(tmp_path):
    cfg = tmp_path / "opencode.json"
    cfg.write_text(
        json.dumps(
            {
                "permission": {"bash": {"ls *": "allow"}},
                "agent": {"plan": {"permission": {"bash": {"git log *": "allow"}}}},
            }
        )
    )
    glob_e, mode_e, _ = _extract_opencode(cfg)
    assert glob_e == ["ls *"]
    assert mode_e == ["git log *"]


def test_opencode_non_allow_values_are_counted_not_harvested(tmp_path):
    cfg = tmp_path / "opencode.json"
    cfg.write_text(json.dumps({"permission": {"bash": {"rm *": "deny"}}}))
    glob_e, _, denied = _extract_opencode(cfg)
    assert glob_e == []
    assert denied == 1


def test_gemini_mode_scoped_rules_are_separated(tmp_path):
    cfg = tmp_path / "p.toml"
    cfg.write_text(
        '[[rule]]\ntoolName = "run_shell_command"\ncommandPrefix = ["ls"]\n'
        'decision = "allow"\n\n'
        '[[rule]]\ntoolName = "run_shell_command"\ncommandPrefix = ["git log"]\n'
        'decision = "allow"\nmodes = ["plan"]\n'
    )
    glob_e, mode_e, _ = _extract_gemini_policy(cfg)
    assert glob_e == ["ls"]
    assert mode_e == ["git log"]


def test_worktree_sources_collapse():
    """Eight .gwt worktrees must not contribute eight identical sources."""
    from pathlib import Path

    a = _collapse_source(Path.home() / "repos/x/.gwt/main/opencode.json")
    b = _collapse_source(Path.home() / "repos/x/.gwt/feat/opencode.json")
    assert a == b == "~/repos/x/.gwt/*/opencode.json"


def test_scrape_rejects_unknown_agent():
    with pytest.raises(ValueError):
        scrape_agent("nope")


# --- normalize ------------------------------------------------------------


def test_normalize_dedupes_variants_to_one_head():
    entries = [
        ScrapedEntry("agy", "unsandboxed(git --no-pager log -n 5)", DIALECT_ANTIGRAVITY, ["a"]),
        ScrapedEntry("agy", "unsandboxed(git log --oneline)", DIALECT_ANTIGRAVITY, ["b"]),
    ]
    r = normalize_entries(entries)
    heads = [c.cmd for c in r.simplified + r.review]
    assert heads.count("git log") <= 1


def test_review_taint_wins_over_a_clean_variant():
    """If any variant of a head needs review, the head needs review."""
    entries = [
        ScrapedEntry("agy", "command(ssh)", DIALECT_ANTIGRAVITY, ["a"]),
        ScrapedEntry("agy", 'command(ssh h "rm -rf /")', DIALECT_ANTIGRAVITY, ["b"]),
    ]
    r = normalize_entries(entries)
    assert "ssh" in [c.cmd for c in r.review]
    assert "ssh" not in [c.cmd for c in r.simplified]


def test_everything_new_lands_in_the_review_tier():
    entries = [ScrapedEntry("agy", "command(zzznovel)", DIALECT_ANTIGRAVITY, ["a"])]
    r = normalize_entries(entries)
    assert all(c.tier == TIER_REVIEW for c in r.simplified + r.review)


def test_already_canonical_commands_are_counted_not_re_added():
    entries = [ScrapedEntry("claude", "Bash(git log:*)", DIALECT_CLAUDE, ["a"])]
    r = normalize_entries(entries)
    assert r.already_canonical == 1
    assert "git log" not in [c.cmd for c in r.simplified + r.review]


def test_provenance_is_retained_for_every_head():
    entries = [ScrapedEntry("agy", "command(zzznovel)", DIALECT_ANTIGRAVITY, ["~/x.json"])]
    r = normalize_entries(entries)
    assert r.provenance["zzznovel"] == ["agy:~/x.json"]


# --- merge into canonical -------------------------------------------------


def test_merge_appends_and_never_rewrites_existing_lines(tmp_path):
    """The canonical files are hand-edited; a re-scrape must not clobber them."""
    dest = tmp_path / "allowlist"
    dest.mkdir()
    review = dest / "review.txt"
    review.write_text("# my own note\nhandedited\n")

    entries = [ScrapedEntry("agy", "command(zzznovel)", DIALECT_ANTIGRAVITY, ["a"])]
    added, path = merge_into_review(normalize_entries(entries), dest)

    text = path.read_text()
    assert added == 1
    assert "# my own note" in text
    assert "handedited" in text
    assert "zzznovel" in text


def test_merge_is_idempotent(tmp_path):
    dest = tmp_path / "allowlist"
    entries = [ScrapedEntry("agy", "command(zzznovel)", DIALECT_ANTIGRAVITY, ["a"])]
    result = normalize_entries(entries)
    first, _ = merge_into_review(result, dest)
    second, _ = merge_into_review(result, dest)
    assert first == 1
    assert second == 0


# --- push -----------------------------------------------------------------


def test_copilot_and_grok_are_excluded_from_push_with_reasons():
    from multi_agent_registry.permissions import DIALECT_COPILOT

    assert DIALECT_COPILOT in UNPUSHABLE
    assert DIALECT_GROK in UNPUSHABLE
    assert not plan_push("copilot").pushable
    assert not plan_push("grok").pushable


def test_grok_skip_reason_names_the_claude_file():
    """Grok merges Claude's settings, so pushing there would duplicate."""
    assert "claude" in plan_push("grok").skipped_reason.lower()


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    cfg = tmp_path / "settings.json"
    original = json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}})
    cfg.write_text(original)

    surfaces = get_permission_surfaces()
    surfaces["claude"].path = cfg
    monkeypatch.setattr(
        "multi_agent_registry.permissions.get_permission_surfaces", lambda: surfaces
    )
    monkeypatch.setattr("multi_agent_registry.push.get_permission_surfaces", lambda: surfaces)

    plan = apply_push("claude", dry_run=True)
    assert plan.additions
    assert not plan.written
    assert cfg.read_text() == original


def test_apply_unions_and_keeps_hand_added_entries(tmp_path, monkeypatch):
    """Bespoke hand-added grants must survive a push."""
    cfg = tmp_path / "settings.json"
    cfg.write_text(
        json.dumps(
            {
                "permissions": {"allow": ["Bash(my-bespoke-thing:*)"], "deny": ["Edit(x)"]},
                "hooks": {"PreToolUse": [{"matcher": "Bash"}]},
                "model": "opus",
            }
        )
    )
    surfaces = get_permission_surfaces()
    surfaces["claude"].path = cfg
    monkeypatch.setattr(
        "multi_agent_registry.permissions.get_permission_surfaces", lambda: surfaces
    )
    monkeypatch.setattr("multi_agent_registry.push.get_permission_surfaces", lambda: surfaces)

    plan = apply_push("claude", dry_run=False)
    data = json.loads(cfg.read_text())

    assert plan.written
    assert "Bash(my-bespoke-thing:*)" in data["permissions"]["allow"]
    assert "Bash(git log:*)" in data["permissions"]["allow"]
    assert data["permissions"]["deny"] == ["Edit(x)"]
    assert data["hooks"]["PreToolUse"] == [{"matcher": "Bash"}]
    assert data["model"] == "opus"
    assert plan.backup is not None and plan.backup.is_file()


def test_push_does_not_grant_the_review_tier(tmp_path, monkeypatch):
    cfg = tmp_path / "settings.json"
    cfg.write_text(json.dumps({"permissions": {"allow": []}}))
    surfaces = get_permission_surfaces()
    surfaces["claude"].path = cfg
    monkeypatch.setattr(
        "multi_agent_registry.permissions.get_permission_surfaces", lambda: surfaces
    )
    monkeypatch.setattr("multi_agent_registry.push.get_permission_surfaces", lambda: surfaces)

    plan = plan_push("claude")
    for entry in plan.additions:
        cmd, _ = parse_native(DIALECT_CLAUDE, entry)
        tiers = {c.tier for c in select_commands(DEFAULT_TIERS) if c.cmd == cmd}
        assert TIER_REVIEW not in tiers


def test_gemini_push_authors_its_own_policy_file(tmp_path, monkeypatch):
    """Never edit the user's hand-written rule files."""
    policies = tmp_path / "policies"
    policies.mkdir()
    (policies / "mine.toml").write_text("# hand written\n")

    surfaces = get_permission_surfaces()
    surfaces["gemini"].path = policies
    monkeypatch.setattr(
        "multi_agent_registry.permissions.get_permission_surfaces", lambda: surfaces
    )
    monkeypatch.setattr("multi_agent_registry.push.get_permission_surfaces", lambda: surfaces)

    plan = apply_push("gemini", dry_run=False)
    assert plan.written
    assert (policies / "mar-canonical.toml").is_file()
    assert (policies / "mine.toml").read_text() == "# hand written\n"


def test_opencode_push_targets_the_global_permission_block(tmp_path, monkeypatch):
    cfg = tmp_path / "opencode.json"
    cfg.write_text(json.dumps({"mcp": {"task_agent": {"type": "local"}}}))
    surfaces = get_permission_surfaces()
    surfaces["opencode"].path = cfg
    monkeypatch.setattr(
        "multi_agent_registry.permissions.get_permission_surfaces", lambda: surfaces
    )
    monkeypatch.setattr("multi_agent_registry.push.get_permission_surfaces", lambda: surfaces)

    apply_push("opencode", dry_run=False)
    data = json.loads(cfg.read_text())
    assert data["permission"]["bash"]["git log *"] == "allow"
    assert data["mcp"]["task_agent"] == {"type": "local"}
