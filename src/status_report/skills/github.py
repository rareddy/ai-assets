"""GitHubSkill: fetch user PRs and push events via GitHub REST API."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

from status_report.skills.base import ActivityItem, ActivitySkill, SkillPermanentError

logger = logging.getLogger(__name__)

_GITHUB_API_BASE = "https://api.github.com"


class GitHubSkill(ActivitySkill):
    """Fetches GitHub PRs authored and push events for the target user."""

    def __init__(self, config: object) -> None:
        self._config = config

    def is_configured(self) -> bool:
        return bool(self._config.github_token)

    async def fetch_activity(
        self, user: str, start: datetime, end: datetime
    ) -> list[ActivityItem]:
        try:
            return await self._fetch_via_api(user, start, end)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403, 404):
                logger.warning(
                    "[github] Auth/not-found error (HTTP %d). Raising permanent failure.",
                    exc.response.status_code,
                )
                raise SkillPermanentError(reason="credentials_missing") from exc
            raise  # transient (5xx/429) — let fetch_with_retry handle
        except SkillPermanentError:
            raise
        except Exception as exc:
            logger.warning("[github] Unexpected error: %s. Returning empty.", exc)
            return []

    async def _fetch_via_api(
        self, user: str, start: datetime, end: datetime
    ) -> list[ActivityItem]:
        limit = self._config.skill_fetch_limit
        headers = {
            "Authorization": f"Bearer {self._config.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        items: list[ActivityItem] = []

        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            pr_items = await self._fetch_prs(client, user, start, end, limit)
            event_items = await self._fetch_push_events(client, user, start, end, limit)
            items = pr_items + event_items

        return items[:limit]

    async def _fetch_prs(
        self,
        client: httpx.AsyncClient,
        user: str,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> list[ActivityItem]:
        start_str = start.strftime("%Y-%m-%d")
        params = {
            "q": f"author:{user} type:pr updated:>={start_str}",
            "per_page": min(limit, 100),
            "sort": "updated",
            "order": "desc",
        }
        try:
            response = await client.get(f"{_GITHUB_API_BASE}/search/issues", params=params)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError:
            raise
        except Exception as exc:
            logger.warning("[github] PR search failed: %s", exc)
            return []

        items: list[ActivityItem] = []
        for issue in data.get("items", []):
            updated_str = issue.get("updated_at", "")
            try:
                ts = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue

            if not (start <= ts <= end):
                continue

            pr = issue.get("pull_request", {})
            if pr.get("merged_at"):
                action = "merged"
            elif issue.get("state") == "closed":
                action = "closed"
            else:
                action = "opened"

            items.append(
                ActivityItem(
                    source="github",
                    action_type=action,
                    title=f"PR #{issue.get('number')} {issue.get('title', '')}",
                    timestamp=ts,
                    url=issue.get("html_url"),
                    metadata={"state": issue.get("state", "")},
                )
            )
        return items

    async def _fetch_push_events(
        self,
        client: httpx.AsyncClient,
        user: str,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> list[ActivityItem]:
        try:
            response = await client.get(
                f"{_GITHUB_API_BASE}/users/{user}/events",
                params={"per_page": min(limit, 100)},
            )
            response.raise_for_status()
            events = response.json()
        except Exception as exc:
            logger.warning("[github] Events fetch failed: %s", exc)
            return []

        items: list[ActivityItem] = []
        for event in events:
            if event.get("type") != "PushEvent":
                continue
            created_str = event.get("created_at", "")
            try:
                ts = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue

            if not (start <= ts <= end):
                continue

            payload = event.get("payload", {})
            commits = payload.get("commits", [])
            commit_count = len(commits)
            repo_name = event.get("repo", {}).get("name", "unknown")

            items.append(
                ActivityItem(
                    source="github",
                    action_type="pushed",
                    title=f"Pushed {commit_count} commit(s) to {repo_name}",
                    timestamp=ts,
                    url=f"https://github.com/{repo_name}",
                    metadata={"repo": repo_name, "commits": str(commit_count)},
                )
            )
        return items
