"""Agent Registry package initialization."""

from multi_agent_registry.account import (
    AgentAccountDetails,
    inspect_agent_account,
    inspect_all_agent_accounts,
)
from multi_agent_registry.discovery import (
    DiscoveredChat,
    RecentAgentActivity,
    discover_agent_chats,
    get_chat_last_active,
    get_chat_workspace,
    get_recent_agent_activity,
)
from multi_agent_registry.normalize import (
    normalize_entries,
    parse_native,
    simplify_command,
)
from multi_agent_registry.permissions import (
    AllowedCommand,
    PermissionDiff,
    PermissionSurface,
    diff_agent_permissions,
    diff_all_permissions,
    get_permission_surfaces,
    load_allowlist,
    render_for_agent,
    select_commands,
)
from multi_agent_registry.push import apply_push, plan_push
from multi_agent_registry.registry import (
    AgentCLIInfo,
    get_agent_cli_registry,
    inspect_agent_cli,
    inspect_all_agent_clis,
)

from multi_agent_registry.scrape import scrape_agent, write_scraped

__all__ = [
    "AgentCLIInfo",
    "AgentAccountDetails",
    "DiscoveredChat",
    "RecentAgentActivity",
    "get_agent_cli_registry",
    "inspect_agent_cli",
    "inspect_all_agent_clis",
    "inspect_agent_account",
    "inspect_all_agent_accounts",
    "discover_agent_chats",
    "get_chat_workspace",
    "get_chat_last_active",
    "get_recent_agent_activity",
    "AllowedCommand",
    "PermissionSurface",
    "PermissionDiff",
    "load_allowlist",
    "parse_native",
    "simplify_command",
    "normalize_entries",
    "scrape_agent",
    "write_scraped",
    "plan_push",
    "apply_push",
    "select_commands",
    "get_permission_surfaces",
    "render_for_agent",
    "diff_agent_permissions",
    "diff_all_permissions",
]

