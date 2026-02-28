"""API token helpers for Jira, GitHub, and Slack."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class JiraCredentials:
    base_url: str
    user_email: str
    api_token: str


@dataclass(frozen=True)
class GitHubCredentials:
    token: str


@dataclass(frozen=True)
class SlackCredentials:
    bot_token: str


def get_jira_credentials(config: object) -> Optional[JiraCredentials]:
    """Return Jira credentials from config, or None if any field is missing."""
    if config.jira_base_url and config.jira_user_email and config.jira_api_token:
        return JiraCredentials(
            base_url=config.jira_base_url.rstrip("/"),
            user_email=config.jira_user_email,
            api_token=config.jira_api_token,
        )
    return None


def get_github_credentials(config: object) -> Optional[GitHubCredentials]:
    """Return GitHub credentials from config, or None if missing."""
    if config.github_token:
        return GitHubCredentials(token=config.github_token)
    return None


def get_slack_credentials(config: object) -> Optional[SlackCredentials]:
    """Return Slack credentials from config, or None if missing."""
    if config.slack_bot_token:
        return SlackCredentials(bot_token=config.slack_bot_token)
    return None
