"""Tests for agent account and usage inspection module."""

import json
from pathlib import Path
import pytest

from multi_agent_registry.account import (
    AgentAccountDetails,
    inspect_agent_account,
    inspect_agy_account,
    inspect_claude_account,
    inspect_copilot_account,
    inspect_opencode_account,
)


def test_inspect_claude_account_authenticated(tmp_path: Path):
    claude_cfg = tmp_path / ".claude.json"
    claude_cfg.write_text(
        json.dumps({
            "oauthAccount": {
                "emailAddress": "test@example.com",
                "organizationName": "Test Org",
                "organizationType": "claude_pro",
                "billingType": "stripe_subscription",
            },
            "cachedUsageUtilization": {
                "utilization": {
                    "five_hour": {"utilization": 15},
                    "seven_day": {"utilization": 45},
                }
            },
        }),
        encoding="utf-8",
    )

    acc = inspect_claude_account(tmp_path)
    assert acc.agent_id == "claude"
    assert acc.authenticated is True
    assert "Claude Pro" in acc.account_type
    assert acc.account_identifier == "test@example.com"
    assert acc.organization == "Test Org"
    assert acc.billing_type == "Stripe Subscription"
    assert acc.usage_summary is not None
    assert acc.usage_summary["five_hour_utilization_pct"] == 15
    assert acc.usage_summary["seven_day_utilization_pct"] == 45


def test_inspect_agy_account_authenticated(tmp_path: Path):
    gemini_dir = tmp_path / ".gemini" / "antigravity-cli"
    gemini_dir.mkdir(parents=True)
    token_file = gemini_dir / "antigravity-oauth-token"
    token_file.write_text(
        json.dumps({"token": "fake_token_123", "auth_method": "consumer"}),
        encoding="utf-8",
    )
    settings_file = gemini_dir / "settings.json"
    settings_file.write_text(
        json.dumps({"model": "gemini-3.8-flash-high"}),
        encoding="utf-8",
    )

    acc = inspect_agy_account(tmp_path)
    assert acc.agent_id == "agy"
    assert acc.authenticated is True
    assert acc.account_type == "OAuth (Consumer)"
    assert acc.usage_summary == {"configured_model": "gemini-3.8-flash-high"}


def test_inspect_copilot_account_authenticated(tmp_path: Path):
    copilot_dir = tmp_path / ".config" / "github-copilot"
    copilot_dir.mkdir(parents=True)
    hosts_file = copilot_dir / "hosts.json"
    hosts_file.write_text(
        json.dumps({"github.com": {"user": "testdeveloper"}}),
        encoding="utf-8",
    )

    acc = inspect_copilot_account(tmp_path)
    assert acc.agent_id == "copilot"
    assert acc.authenticated is True
    assert acc.account_identifier == "testdeveloper"


def test_inspect_agent_account_dispatcher(tmp_path: Path):
    acc = inspect_agent_account("claude", home=tmp_path)
    assert isinstance(acc, AgentAccountDetails)
    assert acc.agent_id == "claude"
