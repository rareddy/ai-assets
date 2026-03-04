"""MCP server configuration models and built-in server definitions."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server subprocess."""

    name: str = Field(..., description="Human-readable source name (e.g. 'github')")
    command: str = Field(..., description="Executable to run (e.g. 'npx')")
    args: list[str] = Field(default_factory=list, description="Command arguments")
    env: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables passed to the subprocess",
    )
    read_only_tools: list[str] = Field(
        ...,
        description="Allowlisted tool names (only these are exposed to Claude)",
    )
    source_label: str = Field(
        ...,
        description="Source label for reporting (e.g. 'github', 'jira')",
    )

    model_config = {"frozen": True}


class MCPConfig(BaseModel):
    """Top-level MCP configuration: all server definitions."""

    servers: list[MCPServerConfig] = Field(default_factory=list)
    max_agent_turns: int = Field(50, description="Max agent loop iterations")


def _env_or_none(key: str, env: dict[str, Optional[str]]) -> Optional[str]:
    """Return env value if present and non-empty, else None."""
    val = env.get(key)
    return val if val else None


def build_mcp_configs(env: dict[str, Optional[str]]) -> list[MCPServerConfig]:
    """Build MCP server configs from environment variables.

    Only returns configs for servers whose required credentials are present.
    """
    configs: list[MCPServerConfig] = []

    # GitHub — official Go-based MCP server (ghcr.io/github/github-mcp-server)
    github_token = _env_or_none("GITHUB_TOKEN", env)
    if github_token:
        configs.append(
            MCPServerConfig(
                name="github",
                command="docker",
                args=[
                    "run", "-i", "--rm",
                    "-e", "GITHUB_PERSONAL_ACCESS_TOKEN",
                    "-e", "GITHUB_READ_ONLY",
                    "ghcr.io/github/github-mcp-server",
                ],
                env={"GITHUB_PERSONAL_ACCESS_TOKEN": github_token, "GITHUB_READ_ONLY": "1"},
                read_only_tools=[
                    "search_repositories",
                    "get_file_contents",
                    "search_code",
                    "list_commits",
                    "get_pull_request",
                    "list_pull_requests",
                    "get_pull_request_diff",
                    "get_pull_request_comments",
                    "get_pull_request_reviews",
                    "list_issues",
                    "get_issue",
                    "get_issue_comments",
                    "search_issues",
                ],
                source_label="github",
            )
        )

    # Jira
    jira_url = _env_or_none("JIRA_BASE_URL", env)
    jira_email = _env_or_none("JIRA_USER_EMAIL", env)
    jira_token = _env_or_none("JIRA_API_TOKEN", env)
    if jira_url and jira_email and jira_token:
        configs.append(
            MCPServerConfig(
                name="jira",
                command="npx",
                args=["-y", "@sooperset/mcp-atlassian", "--jira-url", jira_url],
                env={
                    "JIRA_URL": jira_url,
                    "JIRA_USERNAME": jira_email,
                    "JIRA_API_TOKEN": jira_token,
                },
                read_only_tools=[
                    "jira_search",
                    "jira_get_issue",
                    "jira_get_issue_comments",
                    "jira_get_transitions",
                    "jira_get_worklog",
                    "jira_get_board_issues",
                ],
                source_label="jira",
            )
        )

    # Slack primary — korotovsky/slack-mcp-server with browser session tokens
    # No workspace admin approval required; tokens extracted from Slack web app.
    # See: docs/user-guide.md#slack-setup or run: python -m status_report.auth.slack --extract
    xoxc_token = _env_or_none("SLACK_MCP_XOXC_TOKEN", env)
    xoxd_token = _env_or_none("SLACK_MCP_XOXD_TOKEN", env)
    if xoxc_token and xoxd_token:
        configs.append(
            MCPServerConfig(
                name="slack",
                command="docker",
                args=[
                    "run", "-i", "--rm",
                    "-e", "SLACK_MCP_XOXC_TOKEN",
                    "-e", "SLACK_MCP_XOXD_TOKEN",
                    "ghcr.io/korotovsky/slack-mcp-server:latest",
                ],
                env={"SLACK_MCP_XOXC_TOKEN": xoxc_token, "SLACK_MCP_XOXD_TOKEN": xoxd_token},
                read_only_tools=[
                    "conversations_history",
                    "conversations_replies",
                    "conversations_search_messages",
                    "channels_list",
                    "users_search",
                    "usergroups_list",
                    "usergroups_me",
                    "conversations_unreads",
                ],
                source_label="slack",
            )
        )

    # Slack fallback — Playwright MCP with persisted browser session
    # Active when ~/.status-report/playwright-state.json exists (created by --login or --extract).
    _slack_state = Path.home() / ".status-report" / "playwright-state.json"
    if _slack_state.exists():
        configs.append(
            MCPServerConfig(
                name="slack_browser",
                command="npx",
                args=["-y", "@playwright/mcp@latest", "--storage-state", str(_slack_state)],
                env={},
                read_only_tools=[
                    "browser_navigate",
                    "browser_snapshot",
                    "browser_click",
                    "browser_type",
                    "browser_wait",
                ],
                source_label="slack",
            )
        )

    # Google Workspace (Calendar, Drive, Gmail) — taylorwilsdon/google_workspace_mcp
    # Run via uvx (no install step needed; fetched on first use).
    google_client_id = _env_or_none("GOOGLE_CLIENT_ID", env)
    google_client_secret = _env_or_none("GOOGLE_CLIENT_SECRET", env)
    if google_client_id and google_client_secret:
        # Map user-facing env var names to the names workspace-mcp expects
        google_env: dict[str, str] = {
            "GOOGLE_OAUTH_CLIENT_ID": google_client_id,
            "GOOGLE_OAUTH_CLIENT_SECRET": google_client_secret,
        }
        if google_project_id := _env_or_none("GOOGLE_PROJECT_ID", env):
            google_env["GOOGLE_CLOUD_PROJECT"] = google_project_id
        configs.append(
            MCPServerConfig(
                name="google_workspace",
                command="uvx",
                args=["workspace-mcp", "--read-only"],
                env=google_env,
                read_only_tools=[
                    "calendar_list_events",
                    "calendar_get_event",
                    "drive_search_files",
                    "drive_get_file_metadata",
                    "gmail_search_messages",
                    "gmail_get_message",
                ],
                source_label="google",
            )
        )

    # Playwright (browser fallback — always available)
    configs.append(
        MCPServerConfig(
            name="playwright",
            command="npx",
            args=["-y", "@playwright/mcp@latest"],
            env={},
            read_only_tools=[
                "browser_navigate",
                "browser_snapshot",
                "browser_click",
                "browser_type",
                "browser_wait",
                "browser_tab_list",
                "browser_tab_new",
                "browser_tab_select",
                "browser_tab_close",
            ],
            source_label="browser",
        )
    )

    return configs


def filter_configs_by_sources(
    configs: list[MCPServerConfig],
    requested_sources: list[str] | None,
) -> tuple[list[MCPServerConfig], list[str]]:
    """Filter MCP server configs to requested sources.

    Args:
        configs: All available MCP server configs.
        requested_sources: If provided, restrict to these source labels.
            None means all configured servers.

    Returns:
        Tuple of (filtered configs, names of requested but unavailable sources).
    """
    if requested_sources is None:
        return configs, []

    available_labels = {c.source_label for c in configs}
    filtered = [c for c in configs if c.source_label in requested_sources]
    not_found = [s for s in requested_sources if s not in available_labels]

    return filtered, not_found
