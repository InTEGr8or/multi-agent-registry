"""Data models for agent CLI registry and discovery."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class AgentCLIInfo:
    id: str
    name: str
    binary: str
    description: str
    config_paths: List[Path] = field(default_factory=list)
    mcp_support: bool = True
    mcp_command_example: str = ""
    plugin_support: bool = False
    plugin_path: Optional[Path] = None
    skills_path: Optional[Path] = None
    plugin_template: str = ""
    chat_log_patterns: List[str] = field(default_factory=list)
    chat_parser_type: str = "json"
    # Where this agent expresses its GLOBAL command allowlist. Distinct from
    # config_paths above, which are MCP config locations. Populated from
    # permissions.get_permission_surfaces(); see that module for dialects.
    permissions_path: Optional[Path] = None
    permissions_dialect: Optional[str] = None
    permissions_scope: str = "unsupported"


@dataclass
class DiscoveredChat:
    """Represents a discovered agent chat log file."""

    agent_id: str
    path: Path
    parser_type: str
