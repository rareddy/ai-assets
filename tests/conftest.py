"""Shared fixtures for MCP-based agentic architecture tests."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from status_report.config import Config, ReportPeriod
from status_report.mcp.config import MCPServerConfig
from status_report.mcp.manager import MCPServerHandle
from status_report.mcp.registry import ToolRegistry


# ── Config fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def mock_env(monkeypatch):
    """Set minimal required environment variables for Config."""
    monkeypatch.setenv("VERTEX_PROJECT_ID", "test-project")
    monkeypatch.setenv("VERTEX_REGION", "us-east5")
    monkeypatch.setenv("CLAUDE_MODEL", "claude-sonnet-4-6")


@pytest.fixture
def config(mock_env) -> Config:
    """Minimal Config instance."""
    return Config()


@pytest.fixture
def sample_period() -> ReportPeriod:
    """A sample report period (today)."""
    now = datetime.now(UTC)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return ReportPeriod(label="today", start=start, end=now)


# ── MCP mock fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def github_mcp_config() -> MCPServerConfig:
    """GitHub MCP server config for testing."""
    return MCPServerConfig(
        name="github",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-github"],
        env={"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_test"},
        read_only_tools=[
            "search_repositories",
            "get_file_contents",
            "list_commits",
            "get_pull_request",
            "list_pull_requests",
            "search_issues",
        ],
        source_label="github",
    )


@pytest.fixture
def jira_mcp_config() -> MCPServerConfig:
    """Jira MCP server config for testing."""
    return MCPServerConfig(
        name="jira",
        command="npx",
        args=["-y", "@sooperset/mcp-atlassian"],
        env={
            "JIRA_URL": "https://test.atlassian.net",
            "JIRA_USERNAME": "test@example.com",
            "JIRA_API_TOKEN": "test-token",
        },
        read_only_tools=["jira_search", "jira_get_issue"],
        source_label="jira",
    )


@pytest.fixture
def google_mcp_config() -> MCPServerConfig:
    """Google Workspace MCP server config for testing."""
    return MCPServerConfig(
        name="google_workspace",
        command="npx",
        args=["-y", "@anthropic/google-workspace-mcp"],
        env={
            "GOOGLE_CLIENT_ID": "test-client-id",
            "GOOGLE_CLIENT_SECRET": "test-secret",
        },
        read_only_tools=[
            "calendar_list_events",
            "gmail_search_messages",
            "gmail_get_message",
            "drive_search_files",
        ],
        source_label="google",
    )


def _make_mock_session(tools: list[dict[str, Any]]) -> AsyncMock:
    """Create a mock MCP ClientSession with given tools."""
    session = AsyncMock()
    # Mock list_tools response
    tool_objects = []
    for t in tools:
        tool_obj = MagicMock()
        tool_obj.name = t["name"]
        tool_obj.description = t.get("description", "")
        tool_obj.inputSchema = t.get("input_schema", {"type": "object", "properties": {}})
        tool_objects.append(tool_obj)

    tools_result = MagicMock()
    tools_result.tools = tool_objects
    session.list_tools = AsyncMock(return_value=tools_result)
    session.initialize = AsyncMock()

    return session


def make_server_handle(
    config: MCPServerConfig,
    tools: list[dict[str, Any]] | None = None,
) -> MCPServerHandle:
    """Create a mock MCPServerHandle for testing.

    Args:
        config: MCP server config.
        tools: Tool definitions. If None, uses config's read_only_tools with
            minimal schemas.
    """
    if tools is None:
        tools = [
            {
                "name": name,
                "description": f"Test tool: {name}",
                "input_schema": {"type": "object", "properties": {}},
            }
            for name in config.read_only_tools
        ]

    session = _make_mock_session(tools)

    return MCPServerHandle(
        config=config,
        session=session,
        tools=tools,
    )


# ── Claude response factories ─────────────────────────────────────────────────


def make_tool_use_response(
    tool_calls: list[dict[str, Any]],
) -> MagicMock:
    """Create a mock Claude response with tool_use content blocks.

    Args:
        tool_calls: List of dicts with 'id', 'name', 'input' keys.
    """
    response = MagicMock()
    response.stop_reason = "tool_use"

    content_blocks = []
    for tc in tool_calls:
        block = MagicMock()
        block.type = "tool_use"
        block.id = tc.get("id", "tool_call_1")
        block.name = tc["name"]
        block.input = tc.get("input", {})
        content_blocks.append(block)

    response.content = content_blocks
    response.usage = MagicMock()
    response.usage.input_tokens = 100
    response.usage.output_tokens = 50
    return response


def make_text_response(text: str) -> MagicMock:
    """Create a mock Claude response with a text content block (end_turn)."""
    response = MagicMock()
    response.stop_reason = "end_turn"

    block = MagicMock()
    block.type = "text"
    block.text = text

    response.content = [block]
    response.usage = MagicMock()
    response.usage.input_tokens = 200
    response.usage.output_tokens = 300
    return response
