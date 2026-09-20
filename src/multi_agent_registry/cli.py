import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import verkit  # type: ignore[import-untyped]
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from verkit.theme import DEFAULT as theme  # type: ignore[import-untyped]

from multi_agent_registry.account import (
    inspect_agent_account,
    inspect_all_agent_accounts,
)
from multi_agent_registry.discovery import (
    discover_agent_chats,
    get_recent_agent_activity,
)
from multi_agent_registry.permissions import (
    DEFAULT_TIERS,
    TIER_NETWORK,
    diff_all_permissions,
    load_allowlist,
    render_for_agent,
    surface_exists,
)
from multi_agent_registry.registry import (
    get_agent_cli_registry,
    inspect_agent_cli,
    inspect_all_agent_clis,
)

class ThemedParser(argparse.ArgumentParser):
    """ArgumentParser whose help renders through the shared verkit theme.

    verkit publishes visual tokens (``table_box``, ``header_style``,
    ``panel_box``) but no argparse formatter -- its theme module is explicitly
    "a convention carrier, not a mandate" -- so the rendering lives here and
    the styling comes from there.

    ``add_subparsers`` defaults ``parser_class`` to ``type(self)``, so every
    subcommand's ``--help`` inherits this automatically.
    """

    def print_help(self, file=None):
        console = Console(file=file)
        if self.description:
            console.print(
                Panel(
                    self.description,
                    title=f"[bold blue]{self.prog}[/bold blue]",
                    box=theme.panel_box,
                )
            )
        console.print(f"[dim]{self.format_usage().strip()}[/dim]\n")

        actions = [
            a for a in self._actions if isinstance(a, argparse._SubParsersAction)
        ]
        if actions:
            table = Table(
                title="[bold blue]Subcommands[/bold blue]",
                box=theme.table_box,
                header_style=theme.header_style,
                padding=theme.table_padding,
            )
            table.add_column("Command", style="bold green")
            table.add_column("Description")
            for choice in actions[0]._choices_actions:
                table.add_row(choice.dest, choice.help or "")
            console.print(table)

        opts = [
            a
            for a in self._actions
            if not isinstance(a, argparse._SubParsersAction) and a.option_strings
        ]
        if opts:
            table = Table(
                title="[bold blue]Options[/bold blue]",
                box=theme.table_box,
                header_style=theme.header_style,
                padding=theme.table_padding,
            )
            table.add_column("Flag", style="cyan")
            table.add_column("Description")
            for a in opts:
                table.add_row(", ".join(a.option_strings), a.help or "")
            console.print(table)


CHECK = "[green]✓[/green]"
CROSS = "[red]✗[/red]"
DASH = "[dim]-[/dim]"


def show_registry(console: Console):
    registry = get_agent_cli_registry()
    table = Table(
        title="[bold blue]Registry -- every agent CLI this library knows about[/bold blue]",
        box=theme.table_box,
        header_style=theme.header_style,
        padding=theme.table_padding,
    )
    table.add_column("ID", style="bold green")
    table.add_column("Name")
    table.add_column("Binary", style="cyan")
    table.add_column("Chat Discovery", justify="center")
    table.add_column("MCP", justify="center")
    table.add_column("Plugin", justify="center")
    for agent_id, info in registry.items():
        table.add_row(
            agent_id,
            info.name,
            info.binary,
            CHECK if info.chat_log_patterns else DASH,
            CHECK if info.mcp_support else DASH,
            CHECK if info.plugin_support else DASH,
        )
    console.print(table)


def show_portfolio(console: Console):
    installed = [status for status in inspect_all_agent_clis() if status["installed"]]
    table = Table(
        title="[bold blue]Portfolio -- agent CLIs actually installed on this machine[/bold blue]",
        box=theme.table_box,
        header_style=theme.header_style,
        padding=theme.table_padding,
    )
    table.add_column("ID", style="bold green")
    table.add_column("Name")
    table.add_column("Binary", style="cyan")
    table.add_column("MCP Registered", justify="center")
    table.add_column("Plugin Installed", justify="center")
    for status in installed:
        table.add_row(
            status["id"],
            status["name"],
            status["binary"],
            CHECK if status["mcp_registered"] else DASH,
            CHECK if status["plugin_installed"] else DASH,
        )
    console.print(table)
    if not installed:
        console.print("[dim]No registered agent CLIs found on PATH.[/dim]")


def show_agent_details(agent_id: str, console: Console):
    try:
        status = inspect_agent_cli(agent_id)
    except ValueError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        sys.exit(1)

    account = inspect_agent_account(agent_id)
    chats = discover_agent_chats(agent_id=agent_id)

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Property", style="bold cyan")
    table.add_column("Value")

    table.add_row("ID", status["id"])
    table.add_row("Name", status["name"])
    table.add_row("Description", status["description"])
    table.add_row("Binary", status["binary"])
    table.add_row(
        "Installation",
        f"{CHECK} [green]Installed[/green] ({status['binary_path']})"
        if status["installed"]
        else f"{CROSS} [red]Not Installed[/red]",
    )

    # Account & Authentication State
    auth_str = (
        f"{CHECK} [green]Authenticated[/green] ({account.account_type})"
        if account.authenticated
        else f"{CROSS} [red]Not Authenticated[/red]"
    )
    table.add_row("Auth Status", auth_str)
    if account.account_identifier:
        table.add_row("Account Identity", account.account_identifier)
    if account.organization:
        table.add_row("Organization", account.organization)
    if account.billing_type:
        table.add_row("Billing Tier", account.billing_type)
    if account.detected_env_vars:
        table.add_row("Active Env Vars", ", ".join(f"[yellow]{v}[/yellow]" for v in account.detected_env_vars))

    # Quota & Usage Metrics
    if account.usage_summary:
        usage_lines = []
        if "five_hour_utilization_pct" in account.usage_summary:
            usage_lines.append(f"5-Hour Utilization: [bold green]{account.usage_summary['five_hour_utilization_pct']}%[/bold green]")
        if "seven_day_utilization_pct" in account.usage_summary:
            usage_lines.append(f"7-Day Utilization: [bold green]{account.usage_summary['seven_day_utilization_pct']}%[/bold green]")
        if "configured_model" in account.usage_summary:
            usage_lines.append(f"Configured Model: [magenta]{account.usage_summary['configured_model']}[/magenta]")
        if usage_lines:
            table.add_row("Quota & Usage", "\n".join(usage_lines))

    # MCP Integration
    mcp_text = (
        f"{CHECK} Supported (Registered: {CHECK if status['mcp_registered'] else CROSS})"
        if status["mcp_support"]
        else f"{DASH} Not Supported"
    )
    table.add_row("MCP Support", mcp_text)
    if status["mcp_command_example"]:
        table.add_row("MCP Command", f"[yellow]{status['mcp_command_example']}[/yellow]")

    # Config Paths
    cfg_lines = []
    for p in status["config_paths"]:
        exists = p.is_file()
        cfg_lines.append(f"{CHECK if exists else DASH} {p}")
    table.add_row("Config Paths", "\n".join(cfg_lines) if cfg_lines else DASH)

    # Plugins & Skills
    table.add_row(
        "Plugin Support",
        f"{CHECK} Supported (Installed: {CHECK if status['plugin_installed'] else CROSS})"
        if status["plugin_support"]
        else f"{DASH} Not Supported",
    )
    if status["plugin_path"]:
        table.add_row("Plugin Directory", str(status["plugin_path"]))
    if status["skills_path"]:
        table.add_row("Skills Directory", str(status["skills_path"]))

    # Chat Log Discovery
    table.add_row("Chat Parser Type", status["chat_parser_type"])
    table.add_row(
        "Chat Log Patterns",
        "\n".join(f"- {pat}" for pat in status["chat_log_patterns"])
        if status["chat_log_patterns"]
        else DASH,
    )
    table.add_row("Discovered Chats", f"[bold green]{len(chats)}[/bold green] chat log files found")

    panel = Panel(
        table,
        title=f"[bold blue]Agent CLI Details -- {status['name']} ({status['id']})[/bold blue]",
        expand=False,
    )
    console.print(panel)


def show_agent_usage(console: Console):
    registry = get_agent_cli_registry()
    installed_map = {status["id"]: status for status in inspect_all_agent_clis()}
    accounts = inspect_all_agent_accounts()

    table = Table(
        title="[bold blue]Agent CLI Usage & Quota Portfolio[/bold blue]",
        box=theme.table_box,
        header_style=theme.header_style,
        padding=theme.table_padding,
    )
    table.add_column("ID", style="bold green")
    table.add_column("Agent Name")
    table.add_column("Installed", justify="center")
    table.add_column("Auth Status")
    table.add_column("Account / Tier")
    table.add_column("Quota & Usage Metrics")

    for agent_id, info in registry.items():
        is_installed = installed_map.get(agent_id, {}).get("installed", False)
        acc = accounts.get(agent_id)

        installed_cell = f"{CHECK} [green]Installed[/green]" if is_installed else f"{DASH} [dim]Not Installed[/dim]"
        if not acc:
            auth_cell = f"{DASH} Unknown"
            account_cell = DASH
            usage_cell = DASH
        elif acc.authenticated:
            auth_cell = f"{CHECK} [green]Authenticated[/green]"
            account_cell = f"[cyan]{acc.account_type}[/cyan]"
            if acc.account_identifier:
                account_cell += f"\n[dim]{acc.account_identifier}[/dim]"

            usage_lines = []
            if acc.usage_summary:
                if "five_hour_utilization_pct" in acc.usage_summary:
                    usage_lines.append(f"5h: [bold green]{acc.usage_summary['five_hour_utilization_pct']}%[/bold green]")
                if "seven_day_utilization_pct" in acc.usage_summary:
                    usage_lines.append(f"7d: [bold green]{acc.usage_summary['seven_day_utilization_pct']}%[/bold green]")
                if "configured_model" in acc.usage_summary:
                    usage_lines.append(f"Model: [magenta]{acc.usage_summary['configured_model']}[/magenta]")
            if acc.detected_env_vars:
                usage_lines.append(f"Env: {', '.join(acc.detected_env_vars)}")

            usage_cell = "\n".join(usage_lines) if usage_lines else "[dim]Active / Ready[/dim]"
        else:
            auth_cell = f"{CROSS} [red]Not Logged In[/red]"
            account_cell = f"[dim]{acc.account_type}[/dim]"
            usage_cell = DASH

        table.add_row(
            agent_id,
            info.name,
            installed_cell,
            auth_cell,
            account_cell,
            usage_cell,
        )

    console.print(table)


def show_recent(
    console: Console,
    path_arg: Optional[str] = None,
    limit: int = 5,
    json_format: bool = False,
) -> None:
    """Handler for 'mar recent': rank agent CLIs by recent chat activity."""
    target = Path(path_arg).resolve() if path_arg else Path.cwd()
    activities = get_recent_agent_activity(project_dir=target, limit=limit)

    if json_format:
        registry = get_agent_cli_registry()
        output = [
            {
                "agent_id": a.agent_id,
                "agent_name": registry[a.agent_id].name if a.agent_id in registry else a.agent_id,
                "last_active": a.last_active.isoformat(),
                "log_path": str(a.log_path),
                "workspace": str(a.workspace) if a.workspace else None,
            }
            for a in activities
        ]
        console.print(json.dumps(output, indent=2))
        return

    if not activities:
        console.print(
            f"[yellow]No agent chat activity found for [bold]{target}[/bold].[/yellow]"
        )
        return

    registry = get_agent_cli_registry()
    table = Table(
        title=f"[bold blue]Recent Agent Activity -- {target}[/bold blue]",
        box=theme.table_box,
        header_style=theme.header_style,
        padding=theme.table_padding,
    )
    table.add_column("#", style="dim")
    table.add_column("Agent CLI", style="bold green")
    table.add_column("Last Active (UTC)", style="green")
    table.add_column("Workspace / Log", style="dim")

    for idx, act in enumerate(activities, start=1):
        name = registry[act.agent_id].name if act.agent_id in registry else act.agent_id
        loc = str(act.workspace) if act.workspace else str(act.log_path)
        table.add_row(
            str(idx),
            name,
            act.last_active.strftime("%Y-%m-%d %H:%M:%S"),
            loc,
        )
    console.print(table)


def show_permissions(console: Console, tiers, agent_id=None, render=False):
    """Report how the canonical global allowlist compares to what is on disk."""
    if render and agent_id:
        rendered = render_for_agent(agent_id, tiers)
        if rendered is None:
            console.print(
                f"[bold red]Error:[/bold red] no expressible global permission "
                f"surface for '{agent_id}'."
            )
            sys.exit(1)
        console.print(json.dumps(rendered, indent=2))
        return

    diffs = diff_all_permissions(tiers)
    if agent_id:
        diffs = [d for d in diffs if d.agent_id == agent_id]
        if not diffs:
            console.print(f"[bold red]Error:[/bold red] unknown agent '{agent_id}'.")
            sys.exit(1)

    granted = sorted({c.tier for c in load_allowlist() if c.tier in tiers})
    table = Table(
        title=f"[bold blue]Global command allowlist -- tiers: {', '.join(granted)}[/bold blue]",
        box=theme.table_box,
        header_style=theme.header_style,
        padding=theme.table_padding,
    )
    table.add_column("Agent", style="bold green")
    table.add_column("Scope")
    table.add_column("Dialect", style="cyan")
    table.add_column("On disk", justify="right")
    table.add_column("Missing", justify="right")

    for d in diffs:
        if not d.expressible:
            table.add_row(
                d.agent_id,
                f"[yellow]{d.surface.scope}[/yellow]",
                d.surface.dialect or DASH,
                DASH,
                "[yellow]n/a[/yellow]",
            )
            continue
        missing = len(d.missing)
        table.add_row(
            d.agent_id,
            d.surface.scope,
            d.surface.dialect or DASH,
            str(len(d.current)),
            f"[red]{missing}[/red]" if missing else CHECK,
        )
    console.print(table)

    for d in diffs:
        if not d.expressible:
            console.print(f"\n[yellow]{d.agent_id}[/yellow]: {d.surface.note}")
            continue

        if not surface_exists(d.surface):
            console.print(f"\n[dim]{d.agent_id}: no config at {d.surface.path}[/dim]")
            continue

        if d.missing or d.extra:
            console.print(f"\n[bold]{d.agent_id}[/bold] [dim]{d.surface.path}[/dim]")

        # A zero count against a non-empty file almost always means the grants
        # live somewhere that isn't the global surface -- say so, or the number
        # reads as a bug.
        if not d.current and d.surface.note:
            console.print(f"  [yellow]note:[/yellow] {d.surface.note}")

        for entry in d.missing:
            console.print(f"  [red]+[/red] {entry}")

        if d.extra and agent_id:
            console.print(
                f"  [dim]{len(d.extra)} entries present but not in the canonical "
                f"list (left alone):[/dim]"
            )
            for entry in d.extra:
                console.print(f"  [dim]  ~ {entry}[/dim]")
        elif d.extra:
            console.print(
                f"  [dim]+ {len(d.extra)} entries not in the canonical list "
                f"(--agent {d.agent_id} to list)[/dim]"
            )

    console.print(
        "\n[dim]Read-only: nothing was written. "
        "Use 'mar permissions --agent <id> --render' to emit one agent's block.[/dim]"
    )


def main():
    parser = ThemedParser(
        description="Inspect and manage the multi-agent-registry catalog.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-V", "--version", action="store_true", help="Show version info and exit.")

    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # Command: list
    subparsers.add_parser("list", help="List all registered and locally installed agent CLIs.")

    # Command: usage
    subparsers.add_parser("usage", help="Show unified usage, quota, and authentication comparison across all agent CLIs.")

    # Command: recent
    recent_parser = subparsers.add_parser(
        "recent",
        help="Rank agent CLIs by their most recent chat activity in a repository.",
    )
    recent_parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Target repository directory (defaults to cwd)",
    )
    recent_parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of active agents to return (default: 5)",
    )
    recent_parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON",
    )

    # Command: permissions
    perms_parser = subparsers.add_parser(
        "permissions",
        help="Compare each agent's global command allowlist to the canonical registry.",
    )
    perms_parser.add_argument(
        "--agent", default=None, help="Limit output to a single agent CLI."
    )
    perms_parser.add_argument(
        "--render",
        action="store_true",
        help="Emit the allowlist in one agent's native syntax (requires --agent).",
    )
    perms_parser.add_argument(
        "--network",
        action="store_true",
        help="Include the network tier (curl), which is opt-in by default.",
    )

    # Command: show <agent_id>
    show_parser = subparsers.add_parser("show", help="Show detailed inspection for a specific agent CLI.")
    show_parser.add_argument("agent_id", help="Agent CLI identifier (e.g. claude, agy, opencode, grok).")

    args = parser.parse_args()

    console = Console()
    if args.version:
        verkit.display_version_info(
            console, "multi-agent-registry", upgrade_cmd="uv tool upgrade multi-agent-registry"
        )
        return

    if args.subcommand == "list":
        show_registry(console)
        console.print()
        show_portfolio(console)
    elif args.subcommand == "usage":
        show_agent_usage(console)
    elif args.subcommand == "recent":
        show_recent(console, args.path, limit=args.limit, json_format=args.json)
    elif args.subcommand == "permissions":
        tiers = tuple(DEFAULT_TIERS) + ((TIER_NETWORK,) if args.network else ())
        show_permissions(console, tiers, agent_id=args.agent, render=args.render)
    elif args.subcommand == "show":
        show_agent_details(args.agent_id, console)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
