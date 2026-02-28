"""Tests for CalendarSkill — unittest.mock patches Google API client."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from status_report.config import Config


@pytest.fixture
def calendar_skill(config: Config):
    from status_report.skills.calendar import CalendarSkill
    return CalendarSkill(config)


class TestCalendarSkillIsConfigured:
    def test_is_configured_when_google_creds_present(self, calendar_skill):
        assert calendar_skill.is_configured() is True

    def test_not_configured_when_client_id_missing(self, config: Config):
        from status_report.skills.calendar import CalendarSkill
        config.google_client_id = None
        skill = CalendarSkill(config)
        assert skill.is_configured() is False


class TestCalendarSkillFetchActivity:
    @pytest.mark.asyncio
    async def test_returns_event_items(self, calendar_skill):
        now = datetime.now(UTC)
        start = now - timedelta(hours=8)

        fake_event = {
            "summary": "Team Standup",
            "start": {"dateTime": now.isoformat()},
            "end": {"dateTime": (now + timedelta(minutes=30)).isoformat()},
            "htmlLink": "https://calendar.google.com/event?id=abc",
            "attendees": [{"email": "alice@example.com"}, {"email": "bob@example.com"}],
        }
        fake_events_response = {"items": [fake_event]}

        with patch("status_report.skills.calendar.load_credentials") as mock_creds, \
             patch("status_report.skills.calendar.build") as mock_build:
            mock_creds.return_value = MagicMock()
            service = MagicMock()
            mock_build.return_value = service
            events_resource = MagicMock()
            service.events.return_value = events_resource
            list_method = MagicMock()
            events_resource.list.return_value = list_method
            list_method.execute.return_value = fake_events_response

            items = await calendar_skill.fetch_activity("alice@example.com", start, now)

        assert len(items) == 1
        assert items[0].source == "calendar"
        assert "Team Standup" in items[0].title
        assert "body" not in items[0].metadata  # meeting notes never captured

    @pytest.mark.asyncio
    async def test_raises_permanent_error_when_no_credentials(self, config: Config):
        from status_report.skills.base import SkillPermanentError
        from status_report.skills.calendar import CalendarSkill
        now = datetime.now(UTC)
        start = now - timedelta(hours=1)

        with patch("status_report.skills.calendar.load_credentials") as mock_creds:
            mock_creds.return_value = None
            skill = CalendarSkill(config)
            with pytest.raises(SkillPermanentError, match="credentials_missing"):
                await skill.fetch_activity("alice@example.com", start, now)

    @pytest.mark.asyncio
    async def test_metadata_does_not_include_meeting_notes(self, calendar_skill):
        now = datetime.now(UTC)
        start = now - timedelta(hours=1)

        fake_event = {
            "summary": "1:1 with Bob",
            "start": {"dateTime": now.isoformat()},
            "end": {"dateTime": (now + timedelta(minutes=60)).isoformat()},
            "htmlLink": "https://calendar.google.com/event?id=xyz",
            "description": "Private meeting notes that should NOT appear",
            "attendees": [],
        }

        with patch("status_report.skills.calendar.load_credentials") as mock_creds, \
             patch("status_report.skills.calendar.build") as mock_build:
            mock_creds.return_value = MagicMock()
            service = MagicMock()
            mock_build.return_value = service
            service.events.return_value.list.return_value.execute.return_value = {
                "items": [fake_event]
            }

            items = await calendar_skill.fetch_activity("alice@example.com", start, now)

        if items:
            for item in items:
                assert "description" not in item.metadata
                assert "notes" not in item.metadata
                assert "body" not in item.metadata
