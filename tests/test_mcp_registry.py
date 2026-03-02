"""Tests for MCP tool registry and allowlist filtering."""

from __future__ import annotations

import pytest

from status_report.mcp.registry import ToolRegistry
from tests.conftest import make_server_handle


class TestToolRegistry:
    """Test tool registration and allowlist filtering."""

    def test_register_allowed_tools(self, github_mcp_config):
        """Only allowlisted tools are registered."""
        handle = make_server_handle(
            github_mcp_config,
            tools=[
                {"name": "list_commits", "description": "List commits", "input_schema": {"type": "object"}},
                {"name": "create_issue", "description": "Create issue", "input_schema": {"type": "object"}},
                {"name": "search_issues", "description": "Search issues", "input_schema": {"type": "object"}},
            ],
        )

        registry = ToolRegistry()
        count = registry.register_server(handle)

        assert count == 2  # list_commits and search_issues allowed; create_issue filtered
        assert registry.get_tool("list_commits") is not None
        assert registry.get_tool("search_issues") is not None
        assert registry.get_tool("create_issue") is None

    def test_register_no_matching_tools(self, github_mcp_config):
        """Returns 0 when no tools match the allowlist."""
        handle = make_server_handle(
            github_mcp_config,
            tools=[
                {"name": "create_issue", "description": "Create", "input_schema": {"type": "object"}},
                {"name": "delete_repo", "description": "Delete", "input_schema": {"type": "object"}},
            ],
        )

        registry = ToolRegistry()
        count = registry.register_server(handle)
        assert count == 0
        assert len(registry.tools) == 0

    def test_register_all_servers(self, github_mcp_config, jira_mcp_config):
        """Register tools from multiple servers."""
        gh_handle = make_server_handle(github_mcp_config)
        jira_handle = make_server_handle(jira_mcp_config)

        registry = ToolRegistry()
        total = registry.register_all([gh_handle, jira_handle])

        assert total == len(github_mcp_config.read_only_tools) + len(jira_mcp_config.read_only_tools)

    def test_tool_name_conflict(self, github_mcp_config, jira_mcp_config):
        """Duplicate tool names are rejected (first registration wins)."""
        # Give both servers a tool with the same name
        gh_handle = make_server_handle(
            github_mcp_config,
            tools=[{"name": "search", "description": "GH search", "input_schema": {"type": "object"}}],
        )
        # Add "search" to jira allowlist
        jira_config = jira_mcp_config.model_copy(update={"read_only_tools": ["search", "jira_get_issue"]})
        jira_handle = make_server_handle(
            jira_config,
            tools=[{"name": "search", "description": "Jira search", "input_schema": {"type": "object"}}],
        )

        # Patch: "search" is not in github's default allowlist, so add it
        gh_config = github_mcp_config.model_copy(
            update={"read_only_tools": ["search"] + list(github_mcp_config.read_only_tools)}
        )
        gh_handle = make_server_handle(
            gh_config,
            tools=[{"name": "search", "description": "GH search", "input_schema": {"type": "object"}}],
        )

        registry = ToolRegistry()
        registry.register_server(gh_handle)
        registry.register_server(jira_handle)

        # First registration (GH) wins
        entry = registry.get_tool("search")
        assert entry is not None
        assert entry.server_handle.config.name == "github"

    def test_get_tool_not_found(self):
        """get_tool returns None for unregistered tools."""
        registry = ToolRegistry()
        assert registry.get_tool("nonexistent") is None

    def test_get_anthropic_tools(self, github_mcp_config):
        """get_anthropic_tools returns tools in Anthropic API format."""
        handle = make_server_handle(github_mcp_config)
        registry = ToolRegistry()
        registry.register_server(handle)

        tools = registry.get_anthropic_tools()
        assert len(tools) == len(github_mcp_config.read_only_tools)
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool

    def test_get_source_labels(self, github_mcp_config, jira_mcp_config):
        """get_source_labels returns unique source labels."""
        gh_handle = make_server_handle(github_mcp_config)
        jira_handle = make_server_handle(jira_mcp_config)

        registry = ToolRegistry()
        registry.register_all([gh_handle, jira_handle])

        labels = registry.get_source_labels()
        assert set(labels) == {"github", "jira"}
