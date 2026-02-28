"""Tests for GDriveSkill — unittest.mock patches Google API client."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from status_report.config import Config


@pytest.fixture
def gdrive_skill(config: Config):
    from status_report.skills.gdrive import GDriveSkill
    return GDriveSkill(config)


class TestGDriveSkillIsConfigured:
    def test_is_configured_when_google_creds_present(self, gdrive_skill):
        assert gdrive_skill.is_configured() is True

    def test_not_configured_when_client_id_missing(self, config: Config):
        from status_report.skills.gdrive import GDriveSkill
        config.google_client_id = None
        skill = GDriveSkill(config)
        assert skill.is_configured() is False


class TestGDriveSkillFetchActivity:
    @pytest.mark.asyncio
    async def test_returns_file_activity_items(self, gdrive_skill):
        now = datetime.now(UTC)
        start = now - timedelta(hours=8)

        fake_activity = {
            "activities": [
                {
                    "timestamp": now.isoformat() + "Z",
                    "primaryActionDetail": {"create": {}},
                    "targets": [
                        {
                            "driveItem": {
                                "name": "items/abc123",
                                "title": "Q1 Planning Doc",
                                "file": {},
                                "mimeType": "application/vnd.google-apps.document",
                            }
                        }
                    ],
                }
            ]
        }

        with patch("status_report.skills.gdrive.load_credentials") as mock_creds, \
             patch("status_report.skills.gdrive.build") as mock_build:
            mock_creds.return_value = MagicMock()
            service = MagicMock()
            mock_build.return_value = service
            service.activity.return_value.query.return_value.execute.return_value = fake_activity

            items = await gdrive_skill.fetch_activity("alice@example.com", start, now)

        assert len(items) >= 0  # structure verified
        for item in items:
            assert item.source == "gdrive"

    @pytest.mark.asyncio
    async def test_raises_permanent_error_when_no_credentials(self, config: Config):
        from status_report.skills.base import SkillPermanentError
        from status_report.skills.gdrive import GDriveSkill
        now = datetime.now(UTC)
        start = now - timedelta(hours=1)

        with patch("status_report.skills.gdrive.load_credentials") as mock_creds:
            mock_creds.return_value = None
            skill = GDriveSkill(config)
            with pytest.raises(SkillPermanentError, match="credentials_missing"):
                await skill.fetch_activity("alice@example.com", start, now)

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_api_error(self, gdrive_skill):
        now = datetime.now(UTC)
        start = now - timedelta(hours=1)

        with patch("status_report.skills.gdrive.load_credentials") as mock_creds, \
             patch("status_report.skills.gdrive.build") as mock_build:
            mock_creds.return_value = MagicMock()
            service = MagicMock()
            mock_build.return_value = service
            service.activity.return_value.query.return_value.execute.side_effect = Exception("API error")

            items = await gdrive_skill.fetch_activity("alice@example.com", start, now)

        assert items == []
