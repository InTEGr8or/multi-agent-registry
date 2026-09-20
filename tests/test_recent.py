import os
from datetime import datetime, timezone
from pathlib import Path

from multi_agent_registry.discovery import get_recent_agent_activity


def _repo(tmp_path: Path, name: str = "repo") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    return repo


def test_recent_activity_finds_project_local_chat(tmp_path: Path):
    repo = _repo(tmp_path)
    log = repo / ".aider.chat.history.md"
    log.write_text("# user request\nrun the tests\n")
    ts = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone.utc)
    os.utime(log, (ts.timestamp(), ts.timestamp()))

    results = get_recent_agent_activity(project_dir=repo, limit=5)

    assert [r.agent_id for r in results] == ["aider"]
    assert results[0].log_path == log
    assert results[0].workspace == repo
    assert results[0].last_active.tzinfo is not None
    assert abs((results[0].last_active - ts).total_seconds()) < 1


def test_recent_activity_empty_repo(tmp_path: Path):
    repo = _repo(tmp_path)
    assert get_recent_agent_activity(project_dir=repo) == []


def test_recent_activity_limit(tmp_path: Path):
    repo = _repo(tmp_path)
    newer = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
    log = repo / ".aider.chat.history.md"
    log.write_text("# user request\nhello\n")
    os.utime(log, (newer.timestamp(), newer.timestamp()))

    results = get_recent_agent_activity(project_dir=repo, limit=1)
    assert [r.agent_id for r in results] == ["aider"]

    results = get_recent_agent_activity(project_dir=repo, limit=0)
    assert results == []