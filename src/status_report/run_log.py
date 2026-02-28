"""RunLogger: JSONL audit log with filelock and size-based rotation."""

from __future__ import annotations

import json
import logging
import os
import stat
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Literal, Optional

from filelock import FileLock
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

# Security: these substrings must NOT appear in any log entry value
_FORBIDDEN_LOG_SUBSTRINGS = (
    "token=",
    "password=",
    "secret=",
    "authorization=",
    "Authorization:",
    "api_key",
    "PRIVATE KEY",
)

_LOG_PATH = Path.home() / ".status-report" / "runs.log"
_LOCK_PATH = Path.home() / ".status-report" / "runs.log.lock"
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_BACKUP_COUNT = 5


class SkippedSourceEntry(BaseModel):
    source: str
    reason: str
    attempts: int


class RunTrace(BaseModel):
    """Audit record for one agent execution (written to JSONL log and LangFuse)."""

    schema_version: str = "1.0"
    timestamp: str  # ISO 8601 UTC
    user: str
    period: str  # label or date range string
    format: str
    sources_attempted: list[str]
    counts: dict[str, int]
    outcome: Literal["success", "partial", "failed"]
    skipped: list[SkippedSourceEntry]
    retries: dict[str, int]
    duration_seconds: float

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


def _validate_no_secrets(entry: dict) -> None:
    """Raise ValueError if any serialised field looks like a credential."""
    serialised = json.dumps(entry).lower()
    for forbidden in _FORBIDDEN_LOG_SUBSTRINGS:
        if forbidden.lower() in serialised:
            raise ValueError(
                f"RunTrace entry contains forbidden content '{forbidden}'. "
                "Credentials and sensitive data must not appear in the audit log."
            )


def _ensure_log_dir(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(log_path.parent, stat.S_IRWXU)  # chmod 700


def _rotate_if_needed(log_path: Path) -> None:
    """Rotate log file if it exceeds _MAX_BYTES (keeps _BACKUP_COUNT backups)."""
    if not log_path.exists() or log_path.stat().st_size < _MAX_BYTES:
        return
    handler = RotatingFileHandler(
        str(log_path),
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
    )
    handler.doRollover()
    handler.close()


class RunLogger:
    """Appends RunTrace entries to the JSONL audit log atomically."""

    def __init__(self, log_path: Optional[Path] = None) -> None:
        self._log_path = log_path or _LOG_PATH
        self._lock_path = self._log_path.with_suffix(".log.lock")

    def log_run(self, trace: RunTrace) -> None:
        """Validate and atomically append *trace* to the JSONL log.

        Raises ValueError if the entry contains forbidden content.
        """
        entry = json.loads(trace.model_dump_json())
        _validate_no_secrets(entry)

        _ensure_log_dir(self._log_path)
        _rotate_if_needed(self._log_path)

        with FileLock(str(self._lock_path)):
            with open(self._log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
                fh.flush()
                os.fsync(fh.fileno())

        logger.debug("Audit log entry written to %s", self._log_path)
