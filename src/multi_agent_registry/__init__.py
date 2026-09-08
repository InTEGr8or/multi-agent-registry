"""Agent Registry package initialization."""

from multi_agent_registry.account import (
    AgentAccountDetails,
    inspect_agent_account,
)
from multi_agent_registry.discovery import (
    DiscoveredChat,
    discover_agent_chats,
    get_chat_last_active,
    get_chat_workspace,
)
from multi_agent_registry.registry import (
    AgentCLIInfo,
    get_agent_cli_registry,
    inspect_agent_cli,
    inspect_all_agent_clis,
)

__all__ = [
    "AgentCLIInfo",
    "AgentAccountDetails",
    "DiscoveredChat",
    "get_agent_cli_registry",
    "inspect_agent_cli",
    "inspect_all_agent_clis",
    "inspect_agent_account",
    "discover_agent_chats",
    "get_chat_workspace",
    "get_chat_last_active",
]

