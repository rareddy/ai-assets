"""GDriveSkill: fetch user file activity via Google Drive Activity API."""

from __future__ import annotations

import logging
from datetime import datetime

from status_report.auth.google import load_credentials
from status_report.skills.base import ActivityItem, ActivitySkill, SkillPermanentError

logger = logging.getLogger(__name__)

try:
    from googleapiclient.discovery import build
    _GOOGLE_AVAILABLE = True
except ImportError:
    _GOOGLE_AVAILABLE = False
    logger.warning("google-api-python-client not installed — GDriveSkill unavailable")

# Map Drive Activity API action types to human-readable action strings
_ACTION_MAP = {
    "create": "created",
    "edit": "edited",
    "move": "moved",
    "rename": "renamed",
    "delete": "deleted",
    "restore": "restored",
    "permissionChange": "shared",
    "comment": "commented",
    "dlpChange": "updated",
    "reference": "referenced",
    "settingsChange": "updated",
}


class GDriveSkill(ActivitySkill):
    """Fetches Google Drive file activity (created, modified, viewed)."""

    def __init__(self, config: object) -> None:
        self._config = config

    def is_configured(self) -> bool:
        return bool(
            self._config.google_client_id
            and self._config.google_client_secret
            and _GOOGLE_AVAILABLE
        )

    async def fetch_activity(
        self, user: str, start: datetime, end: datetime
    ) -> list[ActivityItem]:
        try:
            return await self._fetch_via_api(user, start, end)
        except SkillPermanentError:
            raise
        except Exception as exc:
            logger.warning("[gdrive] Error fetching activity: %s. Returning empty.", exc)
            return []

    async def _fetch_via_api(
        self, user: str, start: datetime, end: datetime
    ) -> list[ActivityItem]:
        creds = load_credentials()
        if creds is None:
            logger.warning("[gdrive] No Google credentials found. Run --consent flow first.")
            raise SkillPermanentError(reason="credentials_missing")

        limit = self._config.skill_fetch_limit

        try:
            service = build("driveactivity", "v2", credentials=creds)
            body = {
                "filter": (
                    f"time >= \"{start.strftime('%Y-%m-%dT%H:%M:%SZ')}\" "
                    f"time <= \"{end.strftime('%Y-%m-%dT%H:%M:%SZ')}\""
                ),
                "pageSize": limit,
                "ancestorName": "items/root",
            }
            result = service.activity().query(body=body).execute()
        except Exception as exc:
            logger.warning("[gdrive] Activity API error: %s", exc)
            return []

        activities = result.get("activities", [])
        items: list[ActivityItem] = []

        for activity in activities[:limit]:
            ts_str = activity.get("timestamp", "")
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                ts = start

            if not (start <= ts <= end):
                continue

            # Determine action type
            primary = activity.get("primaryActionDetail", {})
            action_key = next(iter(primary.keys()), "updated") if primary else "updated"
            action_type = _ACTION_MAP.get(action_key, "updated")

            # Extract file title from targets
            targets = activity.get("targets", [])
            file_title = "(unknown file)"
            file_url = None
            for target in targets:
                drive_item = target.get("driveItem", {})
                if drive_item.get("title"):
                    file_title = drive_item["title"]
                    item_name = drive_item.get("name", "")
                    if item_name:
                        file_id = item_name.replace("items/", "")
                        file_url = f"https://drive.google.com/file/d/{file_id}/view"
                    break

            items.append(
                ActivityItem(
                    source="gdrive",
                    action_type=action_type,
                    title=file_title,
                    timestamp=ts,
                    url=file_url,
                    metadata={},
                )
            )

        return items[:limit]
