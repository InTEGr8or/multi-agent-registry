import argparse

import verkit  # type: ignore[import-untyped]
from rich.console import Console
from rich.table import Table

from multi_agent_registry.registry import get_agent_cli_registry, inspect_all_agent_clis
from multi_agent_registry.theme import DEFAULT as theme

CHECK = "[green]✓[/green]"
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


def main():
    parser = argparse.ArgumentParser(description="Inspect the multi-agent-registry catalog.")
    parser.add_argument("-V", "--version", action="store_true", help="Show version info and exit.")
    args = parser.parse_args()

    console = Console()
    if args.version:
        verkit.display_version_info(
            console, "multi-agent-registry", upgrade_cmd="uv tool upgrade multi-agent-registry"
        )
        return

    show_registry(console)
    console.print()
    show_portfolio(console)


if __name__ == "__main__":
    main()
