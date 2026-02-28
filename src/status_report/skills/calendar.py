"""CalendarSkill: fetch attended events via Google Calendar API v3."""

from __future__ import annotations

import logging
from datetime import datetime

from status_report.auth.google import load_credentials
from status_report.skills.base import ActivityItem, ActivitySkill, SkillPermanentError

logger = logging.getLogger(__name__)

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    _GOOGLE_AVAILABLE = True
except ImportError:
    _GOOGLE_AVAILABLE = False
    logger.warning("google-api-python-client not installed — CalendarSkill unavailable")


class CalendarSkill(ActivitySkill):
    """Fetches Google Calendar events the user attended."""

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
            logger.warning("[calendar] Error fetching activity: %s. Returning empty.", exc)
            return []

    async def _fetch_via_api(
        self, user: str, start: datetime, end: datetime
    ) -> list[ActivityItem]:
        creds = load_credentials()
        if creds is None:
            logger.warning("[calendar] No Google credentials found. Run --consent flow first.")
            raise SkillPermanentError(reason="credentials_missing")

        limit = self._config.skill_fetch_limit

        try:
            service = build("calendar", "v3", credentials=creds)
            events_result = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=start.isoformat(),
                    timeMax=end.isoformat(),
                    maxResults=limit,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
        except Exception as exc:
            logger.warning("[calendar] API error: %s", exc)
            return []

        events = events_result.get("items", [])
        items: list[ActivityItem] = []

        for event in events[:limit]:
            start_info = event.get("start", {})
            dt_str = start_info.get("dateTime") or start_info.get("date", "")
            try:
                ts = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                ts = start

            # Privacy: only collect metadata — never description, attachments, or notes
            attendees = event.get("attendees", [])
            attendee_count = len(attendees)

            # Calculate duration in minutes
            end_info = event.get("end", {})
            duration_min = 0
            try:
                ev_start = datetime.fromisoformat(
                    (start_info.get("dateTime") or "").replace("Z", "+00:00")
                )
                ev_end = datetime.fromisoformat(
                    (end_info.get("dateTime") or "").replace("Z", "+00:00")
                )
                duration_min = int((ev_end - ev_start).total_seconds() / 60)
            except Exception:
                pass

            metadata: dict[str, str] = {}
            if attendee_count:
                metadata["attendees"] = str(attendee_count)
            if duration_min:
                metadata["duration_minutes"] = str(duration_min)

            items.append(
                ActivityItem(
                    source="calendar",
                    action_type="attended",
                    title=event.get("summary", "(no title)"),
                    timestamp=ts,
                    url=event.get("htmlLink"),
                    metadata=metadata,
                )
            )

        return items[:limit]
