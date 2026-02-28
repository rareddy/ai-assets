"""SlackSkill: fetch user-sent messages via Slack Web API."""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from status_report.skills.base import ActivityItem, ActivitySkill, SkillPermanentError

logger = logging.getLogger(__name__)

_SLACK_SEARCH_URL = "https://slack.com/api/search.messages"


class SlackSkill(ActivitySkill):
    """Fetches Slack messages sent by the target user."""

    def __init__(self, config: object) -> None:
        self._config = config

    def is_configured(self) -> bool:
        return bool(self._config.slack_bot_token)

    async def fetch_activity(
        self, user: str, start: datetime, end: datetime
    ) -> list[ActivityItem]:
        try:
            return await self._fetch_via_api(user, start, end)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                logger.warning(
                    "[slack] Auth error (HTTP %d). Raising permanent failure.",
                    exc.response.status_code,
                )
                raise SkillPermanentError(reason="credentials_missing") from exc
            raise  # transient (5xx/429) — let fetch_with_retry handle
        except SkillPermanentError:
            raise
        except Exception as exc:
            logger.warning("[slack] Unexpected error: %s. Returning empty.", exc)
            return []

    async def _fetch_via_api(
        self, user: str, start: datetime, end: datetime
    ) -> list[ActivityItem]:
        limit = self._config.skill_fetch_limit
        token = self._config.slack_bot_token

        # Build date range query for from: (user search)
        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")
        query = f"from:{user} after:{start_str} before:{end_str}"

        headers = {"Authorization": f"Bearer {token}"}
        payload = {"query": query, "count": limit}

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                _SLACK_SEARCH_URL,
                headers=headers,
                data=payload,
            )
            response.raise_for_status()
            data = response.json()

        if not data.get("ok"):
            error = data.get("error", "unknown")
            logger.warning("[slack] API returned ok=False: %s", error)
            return []

        matches = data.get("messages", {}).get("matches", [])
        items: list[ActivityItem] = []

        for match in matches[:limit]:
            try:
                ts_float = float(match.get("ts", "0"))
                ts = datetime.fromtimestamp(ts_float, tz=start.tzinfo)
            except (ValueError, TypeError):
                continue

            if not (start <= ts <= end):
                continue

            channel_name = match.get("channel", {}).get("name", "unknown-channel")
            text = match.get("text", "")[:200]  # truncate long messages

            items.append(
                ActivityItem(
                    source="slack",
                    action_type="sent",
                    title=text or "(no text)",
                    timestamp=ts,
                    url=match.get("permalink"),
                    metadata={"channel": channel_name},
                )
            )

        return items[:limit]
