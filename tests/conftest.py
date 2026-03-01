"""Shared pytest fixtures for the status-report test suite."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from status_report.config import Config, ReportPeriod
from status_report.run_log import RunTrace
from status_report.skills.base import ActivityItem


# ── Config fixture ────────────────────────────────────────────────────────────


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Set all required environment variables for Config instantiation."""
    env = {
        "VERTEX_PROJECT_ID": "test-gcp-project",
        "VERTEX_REGION": "us-east5",
        "CLAUDE_MODEL": "claude-sonnet-4-6",
        "JIRA_BASE_URL": "https://test.atlassian.net",
        "JIRA_USER_EMAIL": "alice@example.com",
        "JIRA_API_TOKEN": "jira-token",
        "SLACK_BOT_TOKEN": "xoxb-test",
        "GITHUB_TOKEN": "ghp_test",
        "GOOGLE_CLIENT_ID": "google-client-id",
        "GOOGLE_CLIENT_SECRET": "google-client-secret",
        "GOOGLE_PROJECT_ID": "test-project",
        "SKILL_FETCH_LIMIT": "100",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


@pytest.fixture
def config(mock_env: dict[str, str]) -> Config:
    """Config instance with all credentials present."""
    return Config()


@pytest.fixture
def minimal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment with only required fields (no skill credentials)."""
    for key in [
        "JIRA_BASE_URL",
        "JIRA_USER_EMAIL",
        "JIRA_API_TOKEN",
        "SLACK_BOT_TOKEN",
        "GITHUB_TOKEN",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_PROJECT_ID",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("VERTEX_PROJECT_ID", "test-gcp-project")
    monkeypatch.setenv("VERTEX_REGION", "us-east5")


# ── Time fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def now() -> datetime:
    return datetime.now(UTC)


@pytest.fixture
def today_period(now: datetime) -> ReportPeriod:
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return ReportPeriod(label="today", start=start, end=now)


# ── ActivityItem factory ───────────────────────────────────────────────────────


def make_activity_item(
    source: str = "jira",
    action_type: str = "updated",
    title: str = "Test Issue",
    timestamp: datetime | None = None,
    url: str | None = "https://example.com/item/1",
    metadata: dict[str, str] | None = None,
) -> ActivityItem:
    return ActivityItem(
        source=source,
        action_type=action_type,
        title=title,
        timestamp=timestamp or datetime.now(UTC),
        url=url,
        metadata=metadata or {},
    )


@pytest.fixture
def sample_item() -> ActivityItem:
    return make_activity_item()


@pytest.fixture
def sample_items() -> list[ActivityItem]:
    return [
        make_activity_item(source="jira", title="JIRA-100 Deploy fix"),
        make_activity_item(source="github", action_type="merged", title="PR #42"),
        make_activity_item(source="slack", action_type="sent", title="Team standup thread"),
    ]


# ── Log directory fixture ─────────────────────────────────────────────────────


@pytest.fixture
def tmp_log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect RunLogger to a temporary directory (never touches ~/.status-report)."""
    log_dir = tmp_path / ".status-report"
    log_dir.mkdir()
    return log_dir


# ── Anthropic / Vertex AI mock ────────────────────────────────────────────────


@pytest.fixture
def mock_anthropic():
    """Patch the AnthropicVertex client to return a canned Claude response."""
    fake_text = (
        "## Key Accomplishments\n- Merged PR #42\n\n## Suggested Follow-ups\n- Review JIRA-100"
    )
    fake_response = MagicMock()
    fake_response.content = [MagicMock(text=fake_text)]

    with patch("status_report.agent.anthropic.AnthropicVertex") as mock_cls:
        client = MagicMock()
        client.messages.create.return_value = fake_response
        mock_cls.return_value = client
        yield client


# ── RunTrace factory ──────────────────────────────────────────────────────────


def make_run_trace(**kwargs: Any) -> RunTrace:
    defaults = dict(
        timestamp="2026-02-28T09:45:30.123456Z",
        user="alice@example.com",
        period="today",
        format="text",
        sources_attempted=["jira", "github"],
        counts={"jira": 5, "github": 3},
        outcome="success",
        skipped=[],
        retries={},
        duration_seconds=12.5,
    )
    defaults.update(kwargs)
    return RunTrace(**defaults)
