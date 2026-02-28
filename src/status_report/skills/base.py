"""ActivityItem data model and ActivitySkill abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar, Optional

import httpx
import structlog
from pydantic import BaseModel, field_validator
from tenacity import AsyncRetrying, RetryError, retry_if_exception, stop_after_attempt

logger = structlog.get_logger(__name__)

# Sentinel keys that MUST NOT appear in ActivityItem.metadata (security constraint)
_FORBIDDEN_METADATA_KEYS = frozenset(
    {"token", "password", "secret", "authorization", "credential", "body", "content"}
)


class ActivityItem(BaseModel):
    """Single unit of workplace activity returned by a skill."""

    source: str
    action_type: str
    title: str
    timestamp: datetime
    url: Optional[str] = None
    metadata: dict[str, str] = {}

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, v: dict[str, str]) -> dict[str, str]:
        for key in v:
            if key.lower() in _FORBIDDEN_METADATA_KEYS:
                raise ValueError(
                    f"ActivityItem.metadata must not contain sensitive key: '{key}'"
                )
        return v


class SkillPermanentError(Exception):
    """Raised by skills for permanent failures (invalid credentials, resource not found).

    These errors should NOT be retried. The skill will be added to skipped_sources
    with the provided reason string.
    """

    def __init__(self, reason: str = "unknown") -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass
class SkillFetchResult:
    """Result returned by fetch_with_retry.

    - failure_reason=None  → success (items may be empty if no activity today)
    - failure_reason set   → skill failed; items is always []
    """

    items: list[ActivityItem] = field(default_factory=list)
    retry_count: int = 0
    failure_reason: Optional[str] = None


def is_transient(exc: Exception) -> bool:
    """Return True for errors that warrant retry; False for permanent failures."""
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code >= 500 or code == 429
    return False


def _log_retry(retry_state) -> None:
    """Log each retry attempt before sleeping."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    skill_name = (
        retry_state.args[0].__class__.__name__ if retry_state.args else "unknown"
    )
    logger.warning(
        "skill_retry",
        skill=skill_name,
        attempt=retry_state.attempt_number,
        error=str(exc) if exc else "unknown",
    )


def _retry_wait(retry_state) -> float:
    """Custom wait strategy: honour Retry-After header on 429, else exponential backoff."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if (
        exc is not None
        and isinstance(exc, httpx.HTTPStatusError)
        and exc.response.status_code == 429
    ):
        retry_after = exc.response.headers.get("Retry-After", "")
        try:
            return min(float(retry_after), 60.0)
        except (ValueError, TypeError):
            pass
    # Exponential: min(2^(attempt-1), 30) — attempt_number is 1-based
    n = retry_state.attempt_number
    return max(1.0, min(2 ** (n - 1), 30.0))


async def fetch_with_retry(
    skill: "ActivitySkill",
    user: str,
    start: datetime,
    end: datetime,
) -> SkillFetchResult:
    """Invoke skill.fetch_activity with up to 3 attempts for transient errors.

    Returns SkillFetchResult:
    - failure_reason=None  → success (even if items=[])
    - failure_reason set   → skill failed; should be added to skipped_sources
    """
    attempts_made = 0
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=_retry_wait,
            retry=retry_if_exception(is_transient),
            before_sleep=_log_retry,
        ):
            with attempt:
                attempts_made = attempt.retry_state.attempt_number
                items = await skill.fetch_activity(user, start, end)
                return SkillFetchResult(items=items, retry_count=attempts_made - 1)
    except SkillPermanentError as exc:
        logger.warning("[%s] Permanent failure: %s", skill.__class__.__name__, exc.reason)
        return SkillFetchResult(items=[], retry_count=0, failure_reason=exc.reason)
    except RetryError:
        retries = attempts_made - 1
        logger.warning(
            "[%s] Transient errors exhausted after %d attempt(s).",
            skill.__class__.__name__,
            attempts_made,
        )
        return SkillFetchResult(
            items=[],
            retry_count=retries,
            failure_reason="transient_error_exhausted",
        )
    except Exception as exc:
        logger.warning("[%s] Unexpected error: %s", skill.__class__.__name__, exc)
        return SkillFetchResult(items=[], retry_count=attempts_made, failure_reason=str(exc))
    # Unreachable, but satisfies type checkers
    return SkillFetchResult(items=[], failure_reason="unknown")


class ActivitySkill(ABC):
    """Abstract base class for all data-source skills.

    Concrete subclasses are auto-registered via __init_subclass__() into
    _registry keyed by normalised name (e.g. JiraSkill → "jira").
    """

    _registry: ClassVar[dict[str, type[ActivitySkill]]] = {}

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # Skip abstract intermediaries that still have abstract methods
        if not getattr(cls, "__abstractmethods__", None):
            name = cls.__name__.lower().replace("skill", "")
            ActivitySkill._registry[name] = cls

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if all required credentials are present and non-empty."""

    @abstractmethod
    async def fetch_activity(
        self, user: str, start: datetime, end: datetime
    ) -> list[ActivityItem]:
        """Fetch activity items for *user* in [start, end] UTC.

        Implementations MAY:
        - Raise SkillPermanentError for unrecoverable failures (bad credentials, 401/403/404).
        - Let transient httpx errors propagate — fetch_with_retry handles retries.
        - Return [] if no activity exists in the period (this is NOT a failure).

        Implementations MUST:
        - Return items within [start, end] only.
        - Respect SKILL_FETCH_LIMIT (newest first; drop oldest).
        - Never include credential values in ActivityItem fields or metadata.
        """
