"""Tests for GitHubSkill — respx mocks, no live API calls."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import respx
from httpx import Response

from status_report.config import Config


@pytest.fixture
def github_skill(config: Config):
    from status_report.skills.github import GitHubSkill
    return GitHubSkill(config)


class TestGitHubSkillIsConfigured:
    def test_is_configured_when_token_present(self, github_skill):
        assert github_skill.is_configured() is True

    def test_not_configured_when_token_missing(self, config: Config):
        from status_report.skills.github import GitHubSkill
        config.github_token = None
        skill = GitHubSkill(config)
        assert skill.is_configured() is False


class TestGitHubSkillFetchActivity:
    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_pr_activity(self, github_skill):
        now = datetime.now(UTC)
        start = now - timedelta(hours=8)

        respx.get("https://api.github.com/search/issues").mock(
            return_value=Response(
                200,
                json={
                    "items": [
                        {
                            "title": "Fix auth bug",
                            "number": 412,
                            "state": "closed",
                            "updated_at": now.isoformat(),
                            "html_url": "https://github.com/org/repo/pull/412",
                            "pull_request": {"merged_at": now.isoformat()},
                        }
                    ],
                    "total_count": 1,
                },
            )
        )
        respx.get("https://api.github.com/users/alice/events").mock(
            return_value=Response(200, json=[])
        )

        items = await github_skill.fetch_activity("alice", start, now)

        assert any(item.source == "github" for item in items)

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_permanent_error_on_401(self, github_skill):
        from status_report.skills.base import SkillPermanentError
        respx.get("https://api.github.com/search/issues").mock(return_value=Response(401))
        respx.get("https://api.github.com/users/alice/events").mock(return_value=Response(401))
        now = datetime.now(UTC)
        with pytest.raises(SkillPermanentError, match="credentials_missing"):
            await github_skill.fetch_activity("alice", now - timedelta(hours=1), now)

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_empty_list_on_no_results(self, github_skill):
        respx.get("https://api.github.com/search/issues").mock(
            return_value=Response(200, json={"items": [], "total_count": 0})
        )
        respx.get("https://api.github.com/users/alice/events").mock(
            return_value=Response(200, json=[])
        )
        now = datetime.now(UTC)
        items = await github_skill.fetch_activity("alice", now - timedelta(hours=1), now)
        assert items == []

    @pytest.mark.asyncio
    async def test_activity_items_source_is_github(self, config: Config):
        from status_report.skills.github import GitHubSkill

        now = datetime.now(UTC)
        start = now - timedelta(hours=1)
        skill = GitHubSkill(config)

        with respx.mock:
            respx.get("https://api.github.com/search/issues").mock(
                return_value=Response(
                    200,
                    json={
                        "items": [
                            {
                                "title": "Add feature",
                                "number": 5,
                                "state": "open",
                                "updated_at": now.isoformat(),
                                "html_url": "https://github.com/org/repo/pull/5",
                                "pull_request": {"merged_at": None},
                            }
                        ],
                        "total_count": 1,
                    },
                )
            )
            respx.get("https://api.github.com/users/alice/events").mock(
                return_value=Response(200, json=[])
            )
            items = await skill.fetch_activity("alice", start, now)

        for item in items:
            assert item.source == "github"
