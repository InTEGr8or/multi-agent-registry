import argparse
import sys

import verkit  # type: ignore[import-untyped]
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from multi_agent_registry.account import inspect_agent_account
from multi_agent_registry.discovery import discover_agent_chats
from multi_agent_registry.registry import (
    get_agent_cli_registry,
    inspect_agent_cli,
    inspect_all_agent_clis,
)
from multi_agent_registry.theme import DEFAULT as theme

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


def main():
    parser = argparse.ArgumentParser(
        description="Inspect and manage the multi-agent-registry catalog.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-V", "--version", action="store_true", help="Show version info and exit.")

    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # Command: list
    subparsers.add_parser("list", help="List all registered and locally installed agent CLIs.")

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
    elif args.subcommand == "show":
        show_agent_details(args.agent_id, console)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
