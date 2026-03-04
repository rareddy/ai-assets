"""Tests for MCP tool executor: dispatch routing, Gmail body scrubbing, safety."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from status_report.mcp.executor import (
    ToolExecutor,
    _apply_gmail_scrub,
    _scrub_gmail_body,
)
from status_report.mcp.registry import ToolRegistry
from tests.conftest import make_server_handle


class TestToolExecutor:
    """Test tool dispatch routing and safety validation."""

    @pytest.fixture
    def registry_with_tools(self, github_mcp_config):
        """Registry with GitHub tools registered."""
        handle = make_server_handle(github_mcp_config)
        registry = ToolRegistry()
        registry.register_server(handle)
        return registry, handle

    @pytest.mark.asyncio
    async def test_execute_allowed_tool(self, registry_with_tools):
        """Executing an allowlisted tool dispatches to MCP session."""
        registry, handle = registry_with_tools
        executor = ToolExecutor(registry)

        # Mock the session.call_tool response
        mock_result = MagicMock()
        mock_content = MagicMock()
        mock_content.text = '{"commits": [{"sha": "abc123"}]}'
        mock_result.content = [mock_content]
        handle.session.call_tool = AsyncMock(return_value=mock_result)

        result = await executor.execute("list_commits", {"repo": "test/repo"})

        handle.session.call_tool.assert_called_once_with(
            "list_commits", {"repo": "test/repo"}
        )
        assert "abc123" in result
        assert executor.call_count == 1

    @pytest.mark.asyncio
    async def test_execute_rejected_tool(self, registry_with_tools):
        """Executing a tool not in the allowlist raises ValueError."""
        registry, _ = registry_with_tools
        executor = ToolExecutor(registry)

        with pytest.raises(ValueError, match="not in the read-only allowlist"):
            await executor.execute("create_issue", {"title": "test"})

        assert executor.call_count == 0

    @pytest.mark.asyncio
    async def test_execute_increments_call_count(self, registry_with_tools):
        """Each successful execution increments the call counter."""
        registry, handle = registry_with_tools
        executor = ToolExecutor(registry)

        mock_result = MagicMock()
        mock_content = MagicMock()
        mock_content.text = "{}"
        mock_result.content = [mock_content]
        handle.session.call_tool = AsyncMock(return_value=mock_result)

        await executor.execute("list_commits", {})
        await executor.execute("search_issues", {})

        assert executor.call_count == 2

    @pytest.mark.asyncio
    async def test_execute_tool_error_returns_json_error(self, registry_with_tools):
        """Tool call errors are returned as JSON error objects."""
        registry, handle = registry_with_tools
        executor = ToolExecutor(registry)

        handle.session.call_tool = AsyncMock(side_effect=Exception("connection lost"))

        result = await executor.execute("list_commits", {})

        parsed = json.loads(result)
        assert "error" in parsed
        assert "connection lost" in parsed["error"]
        assert executor.call_count == 1  # Error still counts


class TestGmailBodyScrubbing:
    """Test Gmail body content scrubbing (FR-010a)."""

    @pytest.fixture
    def gmail_registry(self, google_mcp_config):
        """Registry with Google Workspace tools."""
        handle = make_server_handle(google_mcp_config)
        registry = ToolRegistry()
        registry.register_server(handle)
        return registry, handle

    def test_scrub_gmail_body_dict(self):
        """Body fields are scrubbed from dict data."""
        data = {
            "id": "msg123",
            "subject": "Test email",
            "body": "This is the email body content",
            "snippet": "This is a snippet",
            "from": "sender@example.com",
        }
        result = _scrub_gmail_body(data)

        assert result["id"] == "msg123"
        assert result["subject"] == "Test email"
        assert result["from"] == "sender@example.com"
        assert "SCRUBBED" in result["body"]
        assert "SCRUBBED" in result["snippet"]

    def test_scrub_gmail_body_nested(self):
        """Body fields are scrubbed from nested structures."""
        data = {
            "messages": [
                {
                    "id": "msg1",
                    "body": "secret content",
                    "subject": "Hello",
                },
                {
                    "id": "msg2",
                    "htmlBody": "<p>html content</p>",
                    "subject": "World",
                },
            ]
        }
        result = _scrub_gmail_body(data)

        assert "SCRUBBED" in result["messages"][0]["body"]
        assert result["messages"][0]["subject"] == "Hello"
        assert "SCRUBBED" in result["messages"][1]["htmlBody"]
        assert result["messages"][1]["subject"] == "World"

    def test_scrub_gmail_payload(self):
        """Payload is scrubbed but headers preserved."""
        data = {
            "id": "msg1",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Test"},
                    {"name": "From", "value": "a@b.com"},
                    {"name": "X-Custom", "value": "custom"},
                ],
                "body": {"data": "base64encodedcontent"},
                "parts": [{"body": {"data": "part1"}}],
                "mimeType": "multipart/mixed",
            },
        }
        result = _scrub_gmail_body(data)

        # Subject and From headers kept, X-Custom dropped
        payload = result["payload"]
        header_names = [h["name"].lower() for h in payload["headers"]]
        assert "subject" in header_names
        assert "from" in header_names
        assert "x-custom" not in header_names
        assert "body" not in payload  # Body removed
        assert "parts" not in payload  # Parts removed
        assert payload["mimeType"] == "multipart/mixed"

    def test_apply_gmail_scrub_json(self):
        """JSON string scrubbing works end-to-end."""
        data = json.dumps({
            "id": "msg1",
            "body": "secret email content",
            "subject": "Hello",
        })
        result = _apply_gmail_scrub(data)
        parsed = json.loads(result)

        assert "SCRUBBED" in parsed["body"]
        assert parsed["subject"] == "Hello"

    def test_apply_gmail_scrub_invalid_json(self):
        """Non-JSON content gets regex-based scrubbing."""
        text = '"body": "secret content", "subject": "hello"'
        result = _apply_gmail_scrub(text)

        assert "secret content" not in result
        assert "SCRUBBED" in result

    @pytest.mark.asyncio
    async def test_executor_scrubs_gmail_results(self, gmail_registry):
        """gmail_get_message results are scrubbed before returning."""
        registry, handle = gmail_registry
        executor = ToolExecutor(registry)

        # Mock gmail_get_message result with body content
        mock_result = MagicMock()
        mock_content = MagicMock()
        mock_content.text = json.dumps({
            "id": "msg123",
            "subject": "Important email",
            "body": "This is secret email body content that must be scrubbed",
            "from": "sender@example.com",
        })
        mock_result.content = [mock_content]
        handle.session.call_tool = AsyncMock(return_value=mock_result)

        result = await executor.execute("gmail_get_message", {"id": "msg123"})
        parsed = json.loads(result)

        assert parsed["subject"] == "Important email"
        assert parsed["from"] == "sender@example.com"
        assert "secret email body" not in result
        assert "SCRUBBED" in parsed["body"]

    @pytest.mark.asyncio
    async def test_executor_does_not_scrub_non_gmail(self, gmail_registry):
        """Non-Gmail tools do NOT get body scrubbing."""
        registry, handle = gmail_registry
        executor = ToolExecutor(registry)

        mock_result = MagicMock()
        mock_content = MagicMock()
        mock_content.text = json.dumps({
            "body": "This body should NOT be scrubbed for calendar",
        })
        mock_result.content = [mock_content]
        handle.session.call_tool = AsyncMock(return_value=mock_result)

        result = await executor.execute("calendar_list_events", {})
        parsed = json.loads(result)

        assert parsed["body"] == "This body should NOT be scrubbed for calendar"
