"""Tests for the canonical global command allowlist and its dialect renderers."""

import json

import pytest

from multi_agent_registry.permissions import (
    DEFAULT_TIERS,
    DIALECT_ANTIGRAVITY,
    SCOPE_GLOBAL,
    SCOPE_PER_DIRECTORY,
    TIER_NETWORK,
    AllowedCommand,
    _satisfies,
    diff_agent_permissions,
    get_permission_surfaces,
    load_allowlist,
    parse_allowlist_file,
    read_current_entries,
    render_antigravity,
    render_claude,
    render_gemini_policy,
    render_opencode,
    select_commands,
)
from multi_agent_registry.registry import get_agent_cli_registry

# --- canonical list -------------------------------------------------------


def test_network_tier_is_not_granted_by_default():
    """curl reaches the network; it must be opt-in, not part of the defaults."""
    default_cmds = {c.cmd for c in select_commands(DEFAULT_TIERS)}
    assert "curl" not in default_cmds
    assert "curl" in {c.cmd for c in select_commands(DEFAULT_TIERS + (TIER_NETWORK,))}


def test_no_state_mutating_git_subcommands_in_allowlist():
    """The git entries are interrogation only -- nothing that rewrites history."""
    banned = ("git push", "git commit", "git reset", "git rebase", "git clean")
    cmds = {c.cmd for c in load_allowlist()}
    assert not [b for b in banned if b in cmds]


def test_every_command_declares_a_known_tier_and_arg_mode():
    for c in load_allowlist():
        assert c.tier in ("inspect", "build", "network"), c
        assert c.args in ("any", "none"), c


# --- renderers: matching semantics, not just syntax -----------------------


def test_claude_prefix_suffix_distinguishes_arg_modes():
    rendered = render_claude(
        [AllowedCommand("git log", args="any"), AllowedCommand("pwd", args="none")]
    )
    assert rendered == ["Bash(git log:*)", "Bash(pwd)"]


def test_opencode_emits_bare_and_wildcard_patterns():
    """"git log *" alone would not match a bare `git log`."""
    rendered = render_opencode([AllowedCommand("git log", args="any")])
    assert rendered == {"git log": "allow", "git log *": "allow"}


def test_opencode_arg_less_command_gets_no_wildcard():
    assert render_opencode([AllowedCommand("pwd", args="none")]) == {"pwd": "allow"}


def test_antigravity_never_emits_unsandboxed():
    """unsandboxed() escapes the sandbox; the renderer must use the minimal grant."""
    rendered = render_antigravity(select_commands(DEFAULT_TIERS))
    assert rendered
    assert not [e for e in rendered if "unsandboxed" in e]
    assert all(e.startswith("command(") for e in rendered)


def test_gemini_policy_renders_bare_prefixes():
    assert render_gemini_policy([AllowedCommand("git log")]) == ["git log"]


# --- coverage semantics ---------------------------------------------------


def test_unsandboxed_entry_satisfies_a_command_grant():
    assert _satisfies(DIALECT_ANTIGRAVITY, "command(ls)", ["unsandboxed(ls)"])


def test_unrelated_unsandboxed_entry_does_not_satisfy():
    assert not _satisfies(DIALECT_ANTIGRAVITY, "command(ls)", ["unsandboxed(rm)"])


# --- surfaces -------------------------------------------------------------


def test_copilot_is_reported_as_per_directory_not_global():
    """Copilot keys permissions by absolute path; there is no global form."""
    surface = get_permission_surfaces()["copilot"]
    assert surface.scope == SCOPE_PER_DIRECTORY
    assert not diff_agent_permissions("copilot").expressible


def test_claude_permission_path_is_settings_not_config():
    """The allowlist lives in settings.json; .claude.json is the MCP config."""
    surface = get_permission_surfaces()["claude"]
    assert surface.path.name == "settings.json"
    assert surface.scope == SCOPE_GLOBAL

    info = get_agent_cli_registry()["claude"]
    assert info.permissions_path == surface.path
    assert surface.path not in info.config_paths


def test_registry_entries_carry_permission_metadata():
    registry = get_agent_cli_registry()
    for agent_id, surface in get_permission_surfaces().items():
        if agent_id not in registry:
            continue
        assert registry[agent_id].permissions_scope == surface.scope
        assert registry[agent_id].permissions_dialect == surface.dialect


def test_unknown_agent_raises():
    with pytest.raises(ValueError):
        diff_agent_permissions("nope")


# --- reading on-disk state ------------------------------------------------


def test_reads_claude_allow_list(tmp_path):
    cfg = tmp_path / "settings.json"
    cfg.write_text(json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}}))
    surface = get_permission_surfaces()["claude"]
    surface.path = cfg
    assert read_current_entries(surface) == ["Bash(ls:*)"]


def test_reads_opencode_top_level_permission_block(tmp_path):
    """Top-level permission.bash is the global surface; agent.<mode> is not."""
    cfg = tmp_path / "opencode.json"
    cfg.write_text(
        json.dumps(
            {
                "permission": {"bash": {"ls *": "allow"}},
                "agent": {"plan": {"permission": {"bash": {"git log *": "allow"}}}},
            }
        )
    )
    surface = get_permission_surfaces()["opencode"]
    surface.path = cfg
    assert read_current_entries(surface) == ["ls *"]


def test_reads_gemini_policy_command_prefixes(tmp_path):
    cfg = tmp_path / "policy.toml"
    cfg.write_text(
        '[[rule]]\ntoolName = "run_shell_command"\n'
        'commandPrefix = [\n    "git status",\n    "make test",\n]\n'
        'decision = "allow"\n'
    )
    surface = get_permission_surfaces()["gemini"]
    surface.path = cfg
    assert read_current_entries(surface) == ["git status", "make test"]


def test_missing_config_file_reads_as_empty(tmp_path):
    surface = get_permission_surfaces()["claude"]
    surface.path = tmp_path / "does-not-exist.json"
    assert read_current_entries(surface) == []


def test_malformed_config_does_not_raise(tmp_path):
    cfg = tmp_path / "settings.json"
    cfg.write_text("{not json")
    surface = get_permission_surfaces()["claude"]
    surface.path = cfg
    assert read_current_entries(surface) == []


def test_diff_reports_missing_against_a_partial_config(tmp_path):
    cfg = tmp_path / "settings.json"
    cfg.write_text(json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}}))
    surfaces = get_permission_surfaces()
    surfaces["claude"].path = cfg

    import multi_agent_registry.permissions as perms

    original = perms.get_permission_surfaces
    perms.get_permission_surfaces = lambda: surfaces
    try:
        d = perms.diff_agent_permissions("claude")
    finally:
        perms.get_permission_surfaces = original

    assert "Bash(ls:*)" not in d.missing
    assert "Bash(git log:*)" in d.missing


def test_mode_scoped_gemini_rule_is_not_a_global_grant(tmp_path):
    """modes = ["plan"] means plan mode only -- it must not count as global."""
    cfg = tmp_path / "policy.toml"
    cfg.write_text(
        '[[rule]]\ntoolName = "run_shell_command"\n'
        'commandPrefix = ["git status"]\ndecision = "allow"\n'
        'modes = ["plan"]\n'
    )
    surface = get_permission_surfaces()["gemini"]
    surface.path = cfg
    assert read_current_entries(surface) == []


def test_gemini_deny_rule_is_not_read_as_a_grant(tmp_path):
    cfg = tmp_path / "policy.toml"
    cfg.write_text(
        '[[rule]]\ntoolName = "run_shell_command"\n'
        'commandPrefix = ["rm"]\ndecision = "deny"\n'
    )
    surface = get_permission_surfaces()["gemini"]
    surface.path = cfg
    assert read_current_entries(surface) == []


def test_gemini_non_shell_rule_is_ignored(tmp_path):
    """An mcp allow rule grants no shell commands."""
    cfg = tmp_path / "policy.toml"
    cfg.write_text(
        '[[rule]]\ntoolName = "*"\nmcpName = "task-agent"\ndecision = "allow"\n'
    )
    surface = get_permission_surfaces()["gemini"]
    surface.path = cfg
    assert read_current_entries(surface) == []


def test_gemini_policies_read_across_multiple_toml_files(tmp_path):
    (tmp_path / "a.toml").write_text(
        '[[rule]]\ntoolName = "run_shell_command"\n'
        'commandPrefix = ["ls"]\ndecision = "allow"\n'
    )
    (tmp_path / "b.toml").write_text(
        '[[rule]]\ntoolName = "run_shell_command"\n'
        'commandPrefix = ["pwd"]\ndecision = "allow"\n'
    )
    surface = get_permission_surfaces()["gemini"]
    surface.path = tmp_path
    assert sorted(read_current_entries(surface)) == ["ls", "pwd"]


# --- allowlist file format ------------------------------------------------


def test_parser_ignores_blank_and_comment_only_lines():
    text = "\n# a comment\n\n   \nls\n\n"
    assert [c.cmd for c in parse_allowlist_file(text, "inspect")] == ["ls"]


def test_parser_strips_trailing_inline_comments():
    cmds = parse_allowlist_file("make   # runs arbitrary recipes\n", "build")
    assert cmds[0].cmd == "make"
    assert cmds[0].tier == "build"


def test_equals_sigil_marks_a_bare_command():
    cmds = parse_allowlist_file("=pwd\nls\n", "inspect")
    assert (cmds[0].cmd, cmds[0].args) == ("pwd", "none")
    assert (cmds[1].cmd, cmds[1].args) == ("ls", "any")


def test_equals_sigil_tolerates_space_after_it():
    assert parse_allowlist_file("= pwd\n", "inspect")[0].cmd == "pwd"


def test_parser_preserves_multi_word_commands():
    assert parse_allowlist_file("uv run pytest\n", "build")[0].cmd == "uv run pytest"


def test_empty_tier_file_yields_nothing():
    assert parse_allowlist_file("# only comments\n", "network") == []


def test_tier_files_load_and_cover_every_tier():
    """Reads the source tree under pythonpath=src, so this is not a packaging
    gate -- verify the built wheel separately before releasing."""
    al = load_allowlist()
    tiers = {c.tier for c in al}
    assert tiers == {"inspect", "build", "network"}
    assert "git log" in {c.cmd for c in al}


def test_load_allowlist_is_cached():
    assert load_allowlist() is load_allowlist()


# --- themed help ----------------------------------------------------------


def test_help_renders_through_the_themed_parser(capsys):
    """Subcommands must appear in the themed table, not argparse's default."""
    import sys

    from multi_agent_registry.cli import main

    argv = sys.argv
    sys.argv = ["mar"]
    try:
        main()
    finally:
        sys.argv = argv

    out = capsys.readouterr().out
    assert "Subcommands" in out
    assert "permissions" in out


def test_subcommand_help_inherits_the_theme(capsys):
    import sys

    from multi_agent_registry.cli import main

    argv = sys.argv
    sys.argv = ["mar", "permissions", "--help"]
    try:
        main()
    except SystemExit:
        pass
    finally:
        sys.argv = argv

    assert "Options" in capsys.readouterr().out
