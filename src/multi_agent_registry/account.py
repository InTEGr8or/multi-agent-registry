"""Agent Account, Authentication State, and Quota/Usage Inspection Module."""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class AgentAccountDetails:
    agent_id: str
    authenticated: bool
    account_type: str = "Unknown"
    account_identifier: Optional[str] = None
    organization: Optional[str] = None
    billing_type: Optional[str] = None
    detected_env_vars: List[str] = field(default_factory=list)
    usage_summary: Optional[Dict[str, Any]] = None


COMMON_ENV_VARS: Dict[str, List[str]] = {
    "claude": ["ANTHROPIC_API_KEY"],
    "agy": ["GEMINI_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS"],
    "opencode": [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "OPENROUTER_API_KEY",
        "TOGETHER_API_KEY",
    ],
    "copilot": ["GITHUB_TOKEN", "COPILOT_API_KEY", "GH_TOKEN"],
    "grok": ["XAI_API_KEY", "GROK_API_KEY"],
    "cursor": ["CURSOR_API_KEY"],
    "windsurf": ["CODEIUM_API_KEY"],
    "aider": [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "DEEPSEEK_API_KEY",
        "GROQ_API_KEY",
    ],
    "codex": ["OPENAI_API_KEY"],
    "continue": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
    "cline": ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"],
    "roo": ["ROO_CODE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"],
    "goose": ["GOOSE_PROVIDER", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
    "sgpt": ["OPENAI_API_KEY"],
    "interpreter": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
}


def _detect_env_vars(agent_id: str) -> List[str]:
    target_vars = COMMON_ENV_VARS.get(agent_id, ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"])
    return [v for v in target_vars if os.environ.get(v)]


def inspect_claude_account(home: Path) -> AgentAccountDetails:
    env_vars = _detect_env_vars("claude")
    claude_cfg = home / ".claude.json"
    if not claude_cfg.exists():
        return AgentAccountDetails(
            agent_id="claude",
            authenticated=bool(env_vars),
            account_type="API Key (Env)" if env_vars else "Not Authenticated",
            detected_env_vars=env_vars,
        )

    try:
        data = json.loads(claude_cfg.read_text(encoding="utf-8"))
        oauth_acc = data.get("oauthAccount")
        usage_data = data.get("cachedUsageUtilization")

        if isinstance(oauth_acc, dict):
            identifier = oauth_acc.get("emailAddress") or oauth_acc.get("displayName")
            org_name = oauth_acc.get("organizationName")
            org_type = oauth_acc.get("organizationType", "").replace("_", " ").title()
            billing = oauth_acc.get("billingType", "").replace("_", " ").title()

            usage_summary = {}
            if isinstance(usage_data, dict):
                util = usage_data.get("utilization", {})
                if isinstance(util, dict):
                    five_hr = util.get("five_hour")
                    seven_day = util.get("seven_day")
                    if isinstance(five_hr, dict) and "utilization" in five_hr:
                        usage_summary["five_hour_utilization_pct"] = five_hr["utilization"]
                        if five_hr.get("resets_at"):
                            usage_summary["five_hour_resets_at"] = five_hr["resets_at"]
                    if isinstance(seven_day, dict) and "utilization" in seven_day:
                        usage_summary["seven_day_utilization_pct"] = seven_day["utilization"]
                        if seven_day.get("resets_at"):
                            usage_summary["seven_day_resets_at"] = seven_day["resets_at"]

            return AgentAccountDetails(
                agent_id="claude",
                authenticated=True,
                account_type=f"OAuth ({org_type})" if org_type else "OAuth",
                account_identifier=identifier,
                organization=org_name,
                billing_type=billing,
                detected_env_vars=env_vars,
                usage_summary=usage_summary or None,
            )
    except Exception:
        pass

    return AgentAccountDetails(
        agent_id="claude",
        authenticated=bool(env_vars),
        account_type="API Key (Env)" if env_vars else "Not Authenticated",
        detected_env_vars=env_vars,
    )


def inspect_agy_account(home: Path) -> AgentAccountDetails:
    env_vars = _detect_env_vars("agy")
    token_file = home / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
    settings_file = home / ".gemini" / "antigravity-cli" / "settings.json"

    authenticated = False
    account_type = "Not Authenticated"
    identifier = None

    if token_file.is_file():
        try:
            data = json.loads(token_file.read_text(encoding="utf-8"))
            if data.get("token"):
                authenticated = True
                auth_method = data.get("auth_method", "oauth")
                account_type = f"OAuth ({auth_method.capitalize()})"
        except Exception:
            pass

    if not authenticated and env_vars:
        authenticated = True
        account_type = "API Key / ADC"

    usage_summary = None
    if settings_file.is_file():
        try:
            sdata = json.loads(settings_file.read_text(encoding="utf-8"))
            model = sdata.get("model")
            if model:
                usage_summary = {"configured_model": model}
        except Exception:
            pass

    return AgentAccountDetails(
        agent_id="agy",
        authenticated=authenticated,
        account_type=account_type,
        account_identifier=identifier,
        detected_env_vars=env_vars,
        usage_summary=usage_summary,
    )


def inspect_opencode_account(home: Path) -> AgentAccountDetails:
    env_vars = _detect_env_vars("opencode")
    cfg_file = home / ".config" / "opencode" / "opencode.json"

    authenticated = bool(env_vars)
    account_type = "API Keys (Env)" if env_vars else "Not Authenticated"

    if cfg_file.is_file():
        try:
            data = json.loads(cfg_file.read_text(encoding="utf-8"))
            if data:
                authenticated = True
                account_type = "Config File / Env" if env_vars else "Config File"
        except Exception:
            pass

    return AgentAccountDetails(
        agent_id="opencode",
        authenticated=authenticated,
        account_type=account_type,
        detected_env_vars=env_vars,
    )


def inspect_copilot_account(home: Path) -> AgentAccountDetails:
    env_vars = _detect_env_vars("copilot")
    hosts_file = home / ".config" / "github-copilot" / "hosts.json"
    config_file = home / ".config" / "github-copilot" / "config.json"

    authenticated = bool(env_vars)
    account_type = "GitHub Token (Env)" if env_vars else "Not Authenticated"
    identifier = None

    for fpath in (hosts_file, config_file):
        if fpath.is_file():
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                if data:
                    authenticated = True
                    account_type = "GitHub SSO / Config"
                    if "github.com" in data and isinstance(data["github.com"], dict):
                        identifier = data["github.com"].get("user")
            except Exception:
                pass

    return AgentAccountDetails(
        agent_id="copilot",
        authenticated=authenticated,
        account_type=account_type,
        account_identifier=identifier,
        detected_env_vars=env_vars,
    )


def inspect_grok_account(home: Path) -> AgentAccountDetails:
    env_vars = _detect_env_vars("grok")
    cfg_file = home / ".config" / "grok" / "config.json"
    grok_dir = home / ".grok"

    authenticated = bool(env_vars) or cfg_file.is_file() or grok_dir.is_dir()
    account_type = (
        "API Key (Env)"
        if env_vars
        else ("Configured" if (cfg_file.is_file() or grok_dir.is_dir()) else "Not Authenticated")
    )

    return AgentAccountDetails(
        agent_id="grok",
        authenticated=authenticated,
        account_type=account_type,
        detected_env_vars=env_vars,
    )


def inspect_generic_account(agent_id: str, home: Path) -> AgentAccountDetails:
    env_vars = _detect_env_vars(agent_id)
    authenticated = bool(env_vars)
    account_type = "API Key (Env)" if env_vars else "Not Authenticated"
    return AgentAccountDetails(
        agent_id=agent_id,
        authenticated=authenticated,
        account_type=account_type,
        detected_env_vars=env_vars,
    )


def inspect_agent_account(agent_id: str, home: Optional[Path] = None) -> AgentAccountDetails:
    """Inspect account tier, authentication status, and usage for an agent CLI."""
    if home is None:
        home = Path.home()

    inspectors = {
        "claude": inspect_claude_account,
        "agy": inspect_agy_account,
        "opencode": inspect_opencode_account,
        "copilot": inspect_copilot_account,
        "grok": inspect_grok_account,
    }

    inspector = inspectors.get(agent_id)
    if inspector:
        return inspector(home)

    return inspect_generic_account(agent_id, home)


def inspect_all_agent_accounts(home: Optional[Path] = None) -> Dict[str, AgentAccountDetails]:
    """Inspect account and quota details for all registered agent CLIs."""
    from multi_agent_registry.registry import get_agent_cli_registry

    if home is None:
        home = Path.home()

    registry = get_agent_cli_registry()
    return {agent_id: inspect_agent_account(agent_id, home=home) for agent_id in registry}
