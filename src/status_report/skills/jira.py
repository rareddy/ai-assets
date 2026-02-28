"""JiraSkill: fetch user activity from Jira Cloud REST API."""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from status_report.skills.base import ActivityItem, ActivitySkill, SkillPermanentError

logger = logging.getLogger(__name__)

_JIRA_API_PATH = "/rest/api/3/search"


class JiraSkill(ActivitySkill):
    """Fetches Jira issues updated/created/transitioned by the target user."""

    def __init__(self, config: object) -> None:
        self._config = config

    def is_configured(self) -> bool:
        return bool(
            self._config.jira_base_url
            and self._config.jira_user_email
            and self._config.jira_api_token
        )

    async def fetch_activity(
        self, user: str, start: datetime, end: datetime
    ) -> list[ActivityItem]:
        try:
            return await self._fetch_via_api(user, start, end)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403, 404):
                logger.warning(
                    "[jira] Auth/not-found error (HTTP %d). Raising permanent failure.",
                    exc.response.status_code,
                )
                raise SkillPermanentError(reason="credentials_missing") from exc
            raise  # transient (5xx/429) — let fetch_with_retry handle

    async def _fetch_via_api(
        self, user: str, start: datetime, end: datetime
    ) -> list[ActivityItem]:
        base_url = self._config.jira_base_url.rstrip("/")
        limit = self._config.skill_fetch_limit

        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")
        jql = (
            f"updatedBy = \"{user}\" AND updated >= \"{start_str}\" AND updated <= \"{end_str}\""
            f" ORDER BY updated DESC"
        )

        auth = (self._config.jira_user_email, self._config.jira_api_token)
        url = f"{base_url}{_JIRA_API_PATH}"
        params = {
            "jql": jql,
            "maxResults": limit,
            "fields": "summary,status,updated,self",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                url,
                params=params,
                auth=auth,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            data = response.json()

        issues = data.get("issues", [])
        items: list[ActivityItem] = []

        for issue in issues[:limit]:
            fields = issue.get("fields", {})
            updated_str = fields.get("updated", "")
            try:
                ts = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                ts = start

            # Filter to requested window
            if not (start <= ts <= end):
                continue

            status_name = fields.get("status", {}).get("name", "")
            items.append(
                ActivityItem(
                    source="jira",
                    action_type="updated",
                    title=f"{issue.get('key', '')} {fields.get('summary', '')}".strip(),
                    timestamp=ts,
                    url=f"{base_url}/browse/{issue.get('key', '')}",
                    metadata={"status": status_name} if status_name else {},
                )
            )

        return items[:limit]
