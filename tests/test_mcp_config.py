"""Tests for MCP server configuration and env-based config building."""

from __future__ import annotations

import pytest

from status_report.mcp.config import (
    MCPServerConfig,
    build_mcp_configs,
    filter_configs_by_sources,
)


class TestBuildMCPConfigs:
    """Test config building from environment variables."""

    def test_github_config_when_token_present(self):
        """GitHub config is created when GITHUB_TOKEN is set."""
        configs = build_mcp_configs({"GITHUB_TOKEN": "ghp_test123"})

        github = [c for c in configs if c.name == "github"]
        assert len(github) == 1
        assert github[0].source_label == "github"
        assert "GITHUB_PERSONAL_ACCESS_TOKEN" in github[0].env
        assert len(github[0].read_only_tools) > 0

    def test_github_config_skipped_when_no_token(self):
        """GitHub config is NOT created when GITHUB_TOKEN is missing."""
        configs = build_mcp_configs({})

        github = [c for c in configs if c.name == "github"]
        assert len(github) == 0

    def test_jira_config_requires_all_three_vars(self):
        """Jira config requires URL, email, and token."""
        # Missing token
        configs = build_mcp_configs({
            "JIRA_BASE_URL": "https://test.atlassian.net",
            "JIRA_USER_EMAIL": "test@example.com",
        })
        jira = [c for c in configs if c.name == "jira"]
        assert len(jira) == 0

        # All present
        configs = build_mcp_configs({
            "JIRA_BASE_URL": "https://test.atlassian.net",
            "JIRA_USER_EMAIL": "test@example.com",
            "JIRA_API_TOKEN": "tok_123",
        })
        jira = [c for c in configs if c.name == "jira"]
        assert len(jira) == 1

    def test_slack_config(self):
        """Slack config is created when both SLACK_MCP_XOXC_TOKEN and SLACK_MCP_XOXD_TOKEN are set."""
        configs = build_mcp_configs({
            "SLACK_MCP_XOXC_TOKEN": "xoxc-test",
            "SLACK_MCP_XOXD_TOKEN": "xoxd-test",
        })

        slack = [c for c in configs if c.name == "slack"]
        assert len(slack) == 1
        assert slack[0].source_label == "slack"
        assert "SLACK_MCP_XOXC_TOKEN" in slack[0].env
        assert "SLACK_MCP_XOXD_TOKEN" in slack[0].env

    def test_slack_config_requires_both_tokens(self):
        """Slack config requires both xoxc and xoxd tokens."""
        configs = build_mcp_configs({"SLACK_MCP_XOXC_TOKEN": "xoxc-test"})
        slack = [c for c in configs if c.name == "slack"]
        assert len(slack) == 0

        configs = build_mcp_configs({"SLACK_MCP_XOXD_TOKEN": "xoxd-test"})
        slack = [c for c in configs if c.name == "slack"]
        assert len(slack) == 0

    def test_google_workspace_config(self):
        """Google Workspace config requires client ID and secret."""
        configs = build_mcp_configs({
            "GOOGLE_CLIENT_ID": "client-id",
            "GOOGLE_CLIENT_SECRET": "secret",
            "GOOGLE_PROJECT_ID": "proj-123",
        })

        google = [c for c in configs if c.name == "google_workspace"]
        assert len(google) == 1
        assert "gmail_get_message" in google[0].read_only_tools
        # Env vars are remapped to names that workspace-mcp expects
        assert "GOOGLE_OAUTH_CLIENT_ID" in google[0].env
        assert "GOOGLE_OAUTH_CLIENT_SECRET" in google[0].env
        assert "GOOGLE_CLOUD_PROJECT" in google[0].env

    def test_google_workspace_without_project_id(self):
        """Google Workspace config works without GOOGLE_PROJECT_ID."""
        configs = build_mcp_configs({
            "GOOGLE_CLIENT_ID": "client-id",
            "GOOGLE_CLIENT_SECRET": "secret",
        })

        google = [c for c in configs if c.name == "google_workspace"]
        assert len(google) == 1
        assert "GOOGLE_CLOUD_PROJECT" not in google[0].env

    def test_playwright_always_included(self):
        """Playwright browser fallback is always included."""
        configs = build_mcp_configs({})

        pw = [c for c in configs if c.name == "playwright"]
        assert len(pw) == 1
        assert pw[0].source_label == "browser"

    def test_all_configs_present(self):
        """All servers created when all credentials present."""
        configs = build_mcp_configs({
            "GITHUB_TOKEN": "ghp_test",
            "JIRA_BASE_URL": "https://test.atlassian.net",
            "JIRA_USER_EMAIL": "test@example.com",
            "JIRA_API_TOKEN": "tok_123",
            "SLACK_MCP_XOXC_TOKEN": "xoxc-test",
            "SLACK_MCP_XOXD_TOKEN": "xoxd-test",
            "GOOGLE_CLIENT_ID": "client-id",
            "GOOGLE_CLIENT_SECRET": "secret",
        })

        names = {c.name for c in configs}
        assert names == {"github", "jira", "slack", "google_workspace", "playwright"}

    def test_empty_string_treated_as_missing(self):
        """Empty string env vars are treated as missing."""
        configs = build_mcp_configs({"GITHUB_TOKEN": ""})

        github = [c for c in configs if c.name == "github"]
        assert len(github) == 0


class TestFilterConfigsBySources:
    """Test source-based config filtering."""

    def test_filter_none_returns_all(self):
        """None requested_sources returns all configs."""
        configs = build_mcp_configs({
            "GITHUB_TOKEN": "ghp_test",
            "SLACK_MCP_XOXC_TOKEN": "xoxc-test",
            "SLACK_MCP_XOXD_TOKEN": "xoxd-test",
        })
        filtered, not_found = filter_configs_by_sources(configs, None)

        assert len(filtered) == len(configs)
        assert not_found == []

    def test_filter_to_specific_sources(self):
        """Only configs matching requested source labels are returned."""
        configs = build_mcp_configs({
            "GITHUB_TOKEN": "ghp_test",
            "SLACK_MCP_XOXC_TOKEN": "xoxc-test",
            "SLACK_MCP_XOXD_TOKEN": "xoxd-test",
        })
        filtered, not_found = filter_configs_by_sources(configs, ["github"])

        source_labels = [c.source_label for c in filtered]
        assert "github" in source_labels
        assert "slack" not in source_labels
        assert not_found == []

    def test_filter_reports_unavailable_sources(self):
        """Requested sources without configs are reported as not found."""
        configs = build_mcp_configs({"GITHUB_TOKEN": "ghp_test"})
        filtered, not_found = filter_configs_by_sources(configs, ["github", "jira"])

        assert "jira" in not_found

    def test_filter_empty_request_returns_empty(self):
        """Empty requested_sources list returns no configs."""
        configs = build_mcp_configs({"GITHUB_TOKEN": "ghp_test"})
        filtered, not_found = filter_configs_by_sources(configs, [])

        assert len(filtered) == 0
        assert not_found == []
