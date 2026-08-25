"""Agent Registry package initialization."""

from agent_registry.discovery import DiscoveredChat, discover_agent_chats
from agent_registry.registry import (
    AgentCLIInfo,
    get_agent_cli_registry,
    inspect_agent_cli,
    inspect_all_agent_clis,
)

__all__ = [
    "AgentCLIInfo",
    "DiscoveredChat",
    "get_agent_cli_registry",
    "inspect_agent_cli",
    "inspect_all_agent_clis",
    "discover_agent_chats",
]
