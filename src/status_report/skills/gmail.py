"""GmailSkill: fetch sent email metadata via Gmail API (gmail.metadata scope only).

FR-010a: Email body content MUST NOT be fetched, stored, transmitted, or passed to
Claude under any circumstance. The gmail.metadata OAuth scope enforces this at the API
layer. No opt-in path for body content exists in this implementation.
"""

from __future__ import annotations

import logging
from datetime import datetime
from email.utils import parsedate_to_datetime

from status_report.auth.google import load_credentials
from status_report.skills.base import ActivityItem, ActivitySkill, SkillPermanentError

logger = logging.getLogger(__name__)

try:
    from googleapiclient.discovery import build
    _GOOGLE_AVAILABLE = True
except ImportError:
    _GOOGLE_AVAILABLE = False
    logger.warning("google-api-python-client not installed — GmailSkill unavailable")

# Only these headers are requested — body is NEVER accessible with gmail.metadata scope
_METADATA_HEADERS = ["From", "To", "Subject", "Date", "In-Reply-To", "References"]

# Maximum messages to fetch per batch (Google API limit)
_PAGE_SIZE = 100


def _parse_date_header(date_str: str, fallback: datetime) -> datetime:
    """Parse an RFC 2822 Date header string to a UTC-aware datetime."""
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            from datetime import UTC
            return dt.replace(tzinfo=UTC)
        return dt
    except Exception:
        return fallback


def _extract_header(headers: list[dict], name: str) -> str:
    """Extract a single header value by name (case-insensitive)."""
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


class GmailSkill(ActivitySkill):
    """Fetches Gmail sent-message metadata only (no body content ever)."""

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
            logger.warning("[gmail] Error fetching activity: %s. Returning empty.", exc)
            return []

    async def _fetch_via_api(
        self, user: str, start: datetime, end: datetime
    ) -> list[ActivityItem]:
        creds = load_credentials()
        if creds is None:
            logger.warning("[gmail] No Google credentials found. Run --consent flow first.")
            raise SkillPermanentError(reason="credentials_missing")

        limit = self._config.skill_fetch_limit

        try:
            service = build("gmail", "v1", credentials=creds)
            messages_resource = service.users().messages()

            # gmail.metadata scope disables the `q` search parameter.
            # Use labelIds=["SENT"] for sent messages; filter by date client-side.
            list_response = messages_resource.list(
                userId="me",
                labelIds=["SENT"],
                maxResults=min(limit * 2, _PAGE_SIZE),  # fetch extra for date filtering
            ).execute()
        except Exception as exc:
            logger.warning("[gmail] Failed to list messages: %s", exc)
            return []

        messages = list_response.get("messages", [])
        items: list[ActivityItem] = []

        for msg_ref in messages:
            if len(items) >= limit:
                break

            msg_id = msg_ref.get("id", "")
            try:
                # Fetch ONLY metadata headers — body is inaccessible with this format
                msg = messages_resource.get(
                    userId="me",
                    id=msg_id,
                    format="metadata",  # NEVER use "full" or "raw"
                    metadataHeaders=_METADATA_HEADERS,
                ).execute()
            except Exception as exc:
                logger.debug("[gmail] Failed to fetch message %s: %s", msg_id, exc)
                continue

            payload = msg.get("payload", {})
            headers = payload.get("headers", [])

            date_str = _extract_header(headers, "Date")
            ts = _parse_date_header(date_str, fallback=start)

            # Client-side date filter (gmail.metadata disables q parameter)
            if not (start <= ts <= end):
                continue

            subject = _extract_header(headers, "Subject") or "(no subject)"
            from_addr = _extract_header(headers, "From")
            to_addr = _extract_header(headers, "To")
            in_reply_to = _extract_header(headers, "In-Reply-To")

            # Reply detection: presence of In-Reply-To header indicates a reply
            action_type = "replied" if in_reply_to else "sent"

            # Metadata: sender, recipients, and action type only (NO body, NO preview)
            metadata: dict[str, str] = {}
            if from_addr:
                metadata["from"] = from_addr
            if to_addr:
                metadata["to"] = to_addr[:200]  # truncate long To: lists

            items.append(
                ActivityItem(
                    source="gmail",
                    action_type=action_type,
                    title=subject,  # subject line only — body permanently excluded
                    timestamp=ts,
                    url=None,  # Gmail web URLs not accessible via metadata scope
                    metadata=metadata,
                )
            )

        return items[:limit]
