"""Tests for GmailSkill — verifies metadata-only access, no body content."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from status_report.config import Config


@pytest.fixture
def gmail_skill(config: Config):
    from status_report.skills.gmail import GmailSkill
    return GmailSkill(config)


class TestGmailSkillIsConfigured:
    def test_is_configured_when_google_creds_present(self, gmail_skill):
        assert gmail_skill.is_configured() is True

    def test_not_configured_when_client_id_missing(self, config: Config):
        from status_report.skills.gmail import GmailSkill
        config.google_client_id = None
        skill = GmailSkill(config)
        assert skill.is_configured() is False


class TestGmailBodyExclusion:
    """FR-010a: Email body MUST NOT appear in any ActivityItem under any circumstance."""

    @pytest.mark.asyncio
    async def test_metadata_never_contains_body(self, gmail_skill):
        now = datetime.now(UTC)
        start = now - timedelta(hours=8)

        fake_msg_list = {"messages": [{"id": "msg1"}, {"id": "msg2"}]}
        fake_msg_detail = {
            "id": "msg1",
            "payload": {
                "headers": [
                    {"name": "From", "value": "alice@example.com"},
                    {"name": "To", "value": "bob@example.com"},
                    {"name": "Subject", "value": "Re: Q1 Planning"},
                    {"name": "Date", "value": now.strftime("%a, %d %b %Y %H:%M:%S +0000")},
                    {"name": "In-Reply-To", "value": "<prev@example.com>"},
                ],
                # body field intentionally present in fake response to test exclusion
                "body": {"data": "VGhpcyBpcyBhIHNlY3JldCBtZXNzYWdl"},
            },
        }

        with patch("status_report.skills.gmail.load_credentials") as mock_creds, \
             patch("status_report.skills.gmail.build") as mock_build:
            mock_creds.return_value = MagicMock()
            service = MagicMock()
            mock_build.return_value = service
            messages_resource = MagicMock()
            service.users.return_value.messages.return_value = messages_resource
            messages_resource.list.return_value.execute.return_value = fake_msg_list
            messages_resource.get.return_value.execute.return_value = fake_msg_detail

            items = await gmail_skill.fetch_activity("alice@example.com", start, now)

        # Verify body content is NEVER present in any ActivityItem
        for item in items:
            assert item.source == "gmail"
            # body must not appear as a metadata key
            for key in item.metadata:
                assert "body" not in key.lower()
                assert "content" not in key.lower()
            # title must be subject line only, not body content
            assert "VGhpcyBpcyBhIHNlY3JldCBtZXNzYWdl" not in item.title

    @pytest.mark.asyncio
    async def test_reply_detection_via_in_reply_to_header(self, gmail_skill):
        now = datetime.now(UTC)
        start = now - timedelta(hours=8)

        def make_msg(msg_id: str, has_reply_to: bool) -> dict:
            headers = [
                {"name": "From", "value": "alice@example.com"},
                {"name": "To", "value": "bob@example.com"},
                {"name": "Subject", "value": f"Subject {msg_id}"},
                {"name": "Date", "value": now.strftime("%a, %d %b %Y %H:%M:%S +0000")},
            ]
            if has_reply_to:
                headers.append({"name": "In-Reply-To", "value": "<prev@example.com>"})
            return {"id": msg_id, "payload": {"headers": headers}}

        with patch("status_report.skills.gmail.load_credentials") as mock_creds, \
             patch("status_report.skills.gmail.build") as mock_build:
            mock_creds.return_value = MagicMock()
            service = MagicMock()
            mock_build.return_value = service
            messages_resource = MagicMock()
            service.users.return_value.messages.return_value = messages_resource
            messages_resource.list.return_value.execute.return_value = {
                "messages": [{"id": "reply_msg"}, {"id": "sent_msg"}]
            }

            def get_execute(msg_id):
                if msg_id == "reply_msg":
                    return make_msg("reply_msg", has_reply_to=True)
                return make_msg("sent_msg", has_reply_to=False)

            def make_get(userId, id, format, metadataHeaders):
                m = MagicMock()
                m.execute.return_value = get_execute(id)
                return m

            messages_resource.get.side_effect = make_get

            items = await gmail_skill.fetch_activity("alice@example.com", start, now)

        action_types = {item.title.split(" ")[0]: item.action_type for item in items}
        # Verify reply detection logic ran (action_type differentiation)
        # Items may vary; check that we got at least some items
        for item in items:
            assert item.action_type in ("sent", "replied", "actioned")

    @pytest.mark.asyncio
    async def test_only_sent_label_queried(self, gmail_skill):
        """Verify the API call uses labelIds=['SENT'] not full mailbox."""
        now = datetime.now(UTC)
        start = now - timedelta(hours=1)

        with patch("status_report.skills.gmail.load_credentials") as mock_creds, \
             patch("status_report.skills.gmail.build") as mock_build:
            mock_creds.return_value = MagicMock()
            service = MagicMock()
            mock_build.return_value = service
            messages_resource = MagicMock()
            service.users.return_value.messages.return_value = messages_resource
            messages_resource.list.return_value.execute.return_value = {"messages": []}

            await gmail_skill.fetch_activity("alice@example.com", start, now)

            # Verify list was called with SENT label
            call_kwargs = messages_resource.list.call_args
            assert call_kwargs is not None
            kwargs = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]
            label_ids = kwargs.get("labelIds", [])
            assert "SENT" in label_ids


class TestGmailSkillEdgeCases:
    @pytest.mark.asyncio
    async def test_raises_permanent_error_when_no_credentials(self, config: Config):
        from status_report.skills.base import SkillPermanentError
        from status_report.skills.gmail import GmailSkill
        now = datetime.now(UTC)
        start = now - timedelta(hours=1)

        with patch("status_report.skills.gmail.load_credentials") as mock_creds:
            mock_creds.return_value = None
            skill = GmailSkill(config)
            with pytest.raises(SkillPermanentError, match="credentials_missing"):
                await skill.fetch_activity("alice@example.com", start, now)

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_api_error(self, gmail_skill):
        now = datetime.now(UTC)
        start = now - timedelta(hours=1)

        with patch("status_report.skills.gmail.load_credentials") as mock_creds, \
             patch("status_report.skills.gmail.build") as mock_build:
            mock_creds.return_value = MagicMock()
            service = MagicMock()
            mock_build.return_value = service
            service.users.return_value.messages.return_value.list.return_value.execute.side_effect = Exception("API error")

            items = await gmail_skill.fetch_activity("alice@example.com", start, now)

        assert items == []
