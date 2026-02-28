"""Tests for JiraSkill — respx mocks, no live API calls."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
import respx
from httpx import Response

from status_report.config import Config
from status_report.skills.base import ActivityItem


@pytest.fixture
def jira_skill(config: Config):
    from status_report.skills.jira import JiraSkill
    return JiraSkill(config)


@pytest.fixture
def jira_skill_no_creds(monkeypatch: pytest.MonkeyPatch, config: Config):
    from status_report.skills.jira import JiraSkill
    monkeypatch.setattr(config, "jira_api_token", None)
    return JiraSkill(config)


class TestJiraSkillIsConfigured:
    def test_is_configured_when_all_creds_present(self, jira_skill):
        assert jira_skill.is_configured() is True

    def test_not_configured_when_token_missing(self, config: Config):
        from status_report.skills.jira import JiraSkill
        config.jira_api_token = None
        skill = JiraSkill(config)
        assert skill.is_configured() is False

    def test_not_configured_when_url_missing(self, config: Config):
        from status_report.skills.jira import JiraSkill
        config.jira_base_url = None
        skill = JiraSkill(config)
        assert skill.is_configured() is False


class TestJiraSkillFetchActivity:
    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_activity_items_on_success(self, jira_skill, config: Config):
        now = datetime.now(UTC)
        start = now - timedelta(hours=8)

        issue_ts = now.isoformat()
        respx.get(f"{config.jira_base_url}/rest/api/3/search").mock(
            return_value=Response(
                200,
                json={
                    "issues": [
                        {
                            "key": "PROJ-42",
                            "fields": {
                                "summary": "Deploy pipeline fix",
                                "status": {"name": "Done"},
                                "updated": issue_ts,
                                "self": f"{config.jira_base_url}/browse/PROJ-42",
                            },
                        }
                    ],
                    "total": 1,
                },
            )
        )

        items = await jira_skill.fetch_activity("alice@example.com", start, now)

        assert len(items) == 1
        assert items[0].source == "jira"
        assert "PROJ-42" in items[0].title
        assert isinstance(items[0].timestamp, datetime)

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_permanent_error_on_404(self, jira_skill, config: Config):
        from status_report.skills.base import SkillPermanentError
        respx.get(f"{config.jira_base_url}/rest/api/3/search").mock(
            return_value=Response(404)
        )
        now = datetime.now(UTC)
        with pytest.raises(SkillPermanentError, match="credentials_missing"):
            await jira_skill.fetch_activity("alice@example.com", now - timedelta(hours=1), now)

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_permanent_error_on_401(self, jira_skill, config: Config):
        from status_report.skills.base import SkillPermanentError
        respx.get(f"{config.jira_base_url}/rest/api/3/search").mock(
            return_value=Response(401)
        )
        now = datetime.now(UTC)
        with pytest.raises(SkillPermanentError, match="credentials_missing"):
            await jira_skill.fetch_activity("alice@example.com", now - timedelta(hours=1), now)

    @pytest.mark.asyncio
    async def test_respects_skill_fetch_limit(self, config: Config):
        from status_report.skills.jira import JiraSkill

        config.skill_fetch_limit = 2
        skill = JiraSkill(config)
        now = datetime.now(UTC)
        start = now - timedelta(hours=8)

        many_issues = [
            {
                "key": f"PROJ-{i}",
                "fields": {
                    "summary": f"Issue {i}",
                    "status": {"name": "Open"},
                    "updated": now.isoformat(),
                    "self": f"https://test.atlassian.net/browse/PROJ-{i}",
                },
            }
            for i in range(10)
        ]

        with respx.mock:
            respx.get(f"{config.jira_base_url}/rest/api/3/search").mock(
                return_value=Response(200, json={"issues": many_issues, "total": 10})
            )
            items = await skill.fetch_activity("alice@example.com", start, now)

        assert len(items) <= 2

    @pytest.mark.asyncio
    async def test_activity_items_have_required_fields(self, config: Config):
        from status_report.skills.jira import JiraSkill

        now = datetime.now(UTC)
        start = now - timedelta(hours=1)
        skill = JiraSkill(config)

        with respx.mock:
            respx.get(f"{config.jira_base_url}/rest/api/3/search").mock(
                return_value=Response(
                    200,
                    json={
                        "issues": [
                            {
                                "key": "PROJ-1",
                                "fields": {
                                    "summary": "A task",
                                    "status": {"name": "In Progress"},
                                    "updated": now.isoformat(),
                                    "self": "https://test.atlassian.net/browse/PROJ-1",
                                },
                            }
                        ],
                        "total": 1,
                    },
                )
            )
            items = await skill.fetch_activity("alice@example.com", start, now)

        assert items
        item = items[0]
        assert item.source == "jira"
        assert item.action_type
        assert item.title
        assert item.timestamp
