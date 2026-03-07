"""Configuration: Pydantic BaseSettings and ReportPeriod parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


@dataclass
class ReportPeriod:
    """Time window for a report run."""

    label: Optional[str]
    start: datetime  # UTC, inclusive
    end: datetime  # UTC, inclusive

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError(f"period start {self.start} must be <= end {self.end}")


def parse_period(value: str) -> ReportPeriod:
    """Parse a period string into a ReportPeriod with UTC datetimes.

    Supported formats:
      - "today"             → 00:00:00 UTC today to now()
      - "yesterday"         → full previous calendar day UTC
      - "last-24h"          → rolling 24 hours from now()
      - "YYYY-MM-DD"        → full calendar day UTC
      - "YYYY-MM-DD:YYYY-MM-DD" → inclusive date range UTC

    Raises ValueError for future dates or unrecognised formats.
    """
    now = datetime.now(UTC)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if value == "today":
        period = ReportPeriod(label="today", start=today, end=now)

    elif value == "yesterday":
        start = today - timedelta(days=1)
        end = start.replace(hour=23, minute=59, second=59, microsecond=999999)
        period = ReportPeriod(label="yesterday", start=start, end=end)

    elif value == "last-24h":
        period = ReportPeriod(label="last-24h", start=now - timedelta(hours=24), end=now)

    elif value == "last-7d":
        period = ReportPeriod(label="last-7d", start=now - timedelta(days=7), end=now)

    elif value == "last-30d":
        period = ReportPeriod(label="last-30d", start=now - timedelta(days=30), end=now)

    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            date = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError as exc:
            raise ValueError(f"Invalid date '{value}': {exc}") from exc
        start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = date.replace(hour=23, minute=59, second=59, microsecond=999999)
        period = ReportPeriod(label=None, start=start, end=end)

    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}:\d{4}-\d{2}-\d{2}", value):
        start_str, end_str = value.split(":")
        try:
            start_date = datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=UTC)
            end_date = datetime.strptime(end_str, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError as exc:
            raise ValueError(f"Invalid date range '{value}': {exc}") from exc
        start = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        period = ReportPeriod(label=None, start=start, end=end)

    else:
        raise ValueError(
            f"Unrecognised period format: '{value}'. "
            "Use: today, yesterday, last-24h, YYYY-MM-DD, or YYYY-MM-DD:YYYY-MM-DD"
        )

    # FR-014: reject future end dates
    if period.end > now:
        # Allow rolling windows whose end is now()
        if value not in ("today", "last-24h", "last-7d", "last-30d"):
            raise ValueError(
                "ERROR: --period references a future date. "
                "Reports can only be generated for past or current periods."
            )

    return period


class Config(BaseSettings):
    """Application configuration loaded from environment variables."""

    # Vertex AI (Claude is deployed here — no API key needed; uses Google ADC)
    vertex_project_id: str = Field(..., alias="VERTEX_PROJECT_ID")
    vertex_region: str = Field("us-east5", alias="VERTEX_REGION")
    claude_model: str = Field("claude-sonnet-4-6", alias="CLAUDE_MODEL")

    # Jira (optional)
    jira_base_url: Optional[str] = Field(None, alias="JIRA_BASE_URL")
    jira_user_email: Optional[str] = Field(None, alias="JIRA_USER_EMAIL")
    jira_api_token: Optional[str] = Field(None, alias="JIRA_API_TOKEN")

    # Slack (optional — browser session tokens, no admin approval needed)
    slack_mcp_xoxc_token: Optional[str] = Field(None, alias="SLACK_MCP_XOXC_TOKEN")
    slack_mcp_xoxd_token: Optional[str] = Field(None, alias="SLACK_MCP_XOXD_TOKEN")

    # GitHub (optional)
    github_token: Optional[str] = Field(None, alias="GITHUB_TOKEN")

    # Google (optional — shared across Calendar, Drive, Gmail)
    google_client_id: Optional[str] = Field(None, alias="GOOGLE_CLIENT_ID")
    google_client_secret: Optional[str] = Field(None, alias="GOOGLE_CLIENT_SECRET")
    google_project_id: Optional[str] = Field(None, alias="GOOGLE_PROJECT_ID")

    # Agent limits
    max_agent_turns: int = Field(50, alias="MAX_AGENT_TURNS")
    max_response_tokens: int = Field(8096, alias="MAX_RESPONSE_TOKENS")

    @field_validator("max_response_tokens")
    @classmethod
    def validate_max_response_tokens(cls, v: int) -> int:
        if v < 1024:
            raise ValueError("MAX_RESPONSE_TOKENS must be >= 1024")
        return v

    @field_validator("max_agent_turns")
    @classmethod
    def validate_max_turns(cls, v: int) -> int:
        if v < 1:
            raise ValueError("MAX_AGENT_TURNS must be >= 1")
        return v

    model_config = {"populate_by_name": True, "extra": "ignore", "env_file": ".env"}
