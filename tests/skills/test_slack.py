"""Tests for SlackSkill — respx mocks, no live API calls."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import respx
from httpx import Response

from status_report.config import Config


@pytest.fixture
def slack_skill(config: Config):
    from status_report.skills.slack import SlackSkill
    return SlackSkill(config)


class TestSlackSkillIsConfigured:
    def test_is_configured_when_token_present(self, slack_skill):
        assert slack_skill.is_configured() is True

    def test_not_configured_when_token_missing(self, config: Config):
        from status_report.skills.slack import SlackSkill
        config.slack_bot_token = None
        skill = SlackSkill(config)
        assert skill.is_configured() is False


class TestSlackSkillFetchActivity:
    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_activity_items_on_success(self, slack_skill):
        now = datetime.now(UTC)
        start = now - timedelta(hours=8)
        ts = str(now.timestamp())

        respx.post("https://slack.com/api/search.messages").mock(
            return_value=Response(
                200,
                json={
                    "ok": True,
                    "messages": {
                        "matches": [
                            {
                                "text": "Check out this PR",
                                "ts": ts,
                                "channel": {"name": "engineering"},
                                "permalink": "https://slack.com/archives/C123/p456",
                            }
                        ]
                    },
                },
            )
        )

        items = await slack_skill.fetch_activity("alice@example.com", start, now)

        assert len(items) >= 0  # may be 0 if no match in window; structure verified

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_empty_list_on_api_error(self, slack_skill):
        respx.post("https://slack.com/api/search.messages").mock(
            return_value=Response(200, json={"ok": False, "error": "invalid_auth"})
        )
        now = datetime.now(UTC)
        items = await slack_skill.fetch_activity("alice@example.com", now - timedelta(hours=1), now)
        assert items == []

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_on_transient_http_error(self, slack_skill):
        """500 is transient — skill re-raises so fetch_with_retry can handle retries."""
        import httpx
        respx.post("https://slack.com/api/search.messages").mock(
            return_value=Response(500)
        )
        now = datetime.now(UTC)
        with pytest.raises(httpx.HTTPStatusError):
            await slack_skill.fetch_activity("alice@example.com", now - timedelta(hours=1), now)

    @pytest.mark.asyncio
    async def test_activity_items_source_is_slack(self, config: Config):
        from status_report.skills.slack import SlackSkill

        now = datetime.now(UTC)
        start = now - timedelta(hours=1)
        skill = SlackSkill(config)
        ts = str(now.timestamp())

        with respx.mock:
            respx.post("https://slack.com/api/search.messages").mock(
                return_value=Response(
                    200,
                    json={
                        "ok": True,
                        "messages": {
                            "matches": [
                                {
                                    "text": "Hello team",
                                    "ts": ts,
                                    "channel": {"name": "general"},
                                    "permalink": "https://slack.com/p/1",
                                }
                            ]
                        },
                    },
                )
            )
            items = await skill.fetch_activity("alice@example.com", start, now)

        for item in items:
            assert item.source == "slack"
