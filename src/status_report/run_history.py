"""Per-user run history store for auto-computing the report period.

Writes one JSONL entry to ~/.status-report/run_history.log after every
successful or partial agent run.  When --period is omitted, the CLI reads
the most recent entry for the current user to derive the start of the
next report window.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Optional

import structlog
from filelock import FileLock

logger = structlog.get_logger(__name__)

_DEFAULT_LOG_DIR = Path.home() / ".status-report"
_HISTORY_FILENAME = "run_history.log"
_PRUNE_DAYS = 90


@dataclass
class RunHistoryEntry:
    """Single record written to run_history.log after a successful/partial run."""

    schema_version: str
    user: str
    completed_at: str  # ISO 8601 UTC
    period_label: str
    outcome: Literal["success", "partial"]


class RunHistoryStore:
    """Read/write abstraction over ~/.status-report/run_history.log.

    Args:
        log_dir: Override the default storage directory (used in tests via tmp_path).
    """

    def __init__(self, log_dir: Optional[Path] = None) -> None:
        base = log_dir or _DEFAULT_LOG_DIR
        self._log_path: Path = base / _HISTORY_FILENAME
        self._lock_path: Path = self._log_path.with_suffix(".log.lock")

    # ── Public API ─────────────────────────────────────────────────────────

    def get_last_successful_run(self, user: str) -> tuple[datetime, str] | None:
        """Return (completed_at, period_label) of the most recent success/partial
        entry for *user*, or None if no valid entry exists.

        Skips malformed JSON lines (warning logged).
        Skips entries with future timestamps (warning logged).
        Skips entries with outcome not in ("success", "partial").
        """
        if not self._log_path.exists():
            return None

        now = datetime.now(UTC)
        best: tuple[datetime, str] | None = None

        try:
            lines = self._log_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            logger.warning("run_history_read_error", error=str(exc))
            return None

        for lineno, raw in enumerate(lines, start=1):
            raw = raw.strip()
            if not raw:
                continue
            entry = self._parse_line(raw, lineno)
            if entry is None:
                continue
            if entry.user != user:
                continue
            if entry.outcome not in ("success", "partial"):
                continue
            try:
                ts = datetime.fromisoformat(entry.completed_at.replace("Z", "+00:00"))
            except ValueError:
                logger.warning(
                    "run_history_invalid_timestamp",
                    lineno=lineno,
                    completed_at=entry.completed_at,
                )
                continue
            if ts > now:
                logger.warning(
                    "run_history_future_timestamp_skipped",
                    lineno=lineno,
                    completed_at=entry.completed_at,
                )
                continue
            if best is None or ts > best[0]:
                best = (ts, entry.period_label)

        return best

    def record_run(
        self,
        user: str,
        completed_at: datetime,
        outcome: Literal["success", "partial"],
        period_label: str,
    ) -> None:
        """Append a new entry and prune entries older than 90 days.

        The filelock is held for the full read-filter-write operation so that
        concurrent runs from different users cannot interleave or lose entries.

        Raises:
            ValueError: if *outcome* is not "success" or "partial".
        """
        if outcome not in ("success", "partial"):
            raise ValueError(
                f"record_run called with invalid outcome {outcome!r}. "
                "Only 'success' and 'partial' may be recorded."
            )

        new_entry = RunHistoryEntry(
            schema_version="1",
            user=user,
            completed_at=completed_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            period_label=period_label,
            outcome=outcome,
        )

        self._ensure_dir()
        cutoff = datetime.now(UTC) - timedelta(days=_PRUNE_DAYS)

        with FileLock(str(self._lock_path)):
            existing = self._read_all_locked()
            kept = [e for e in existing if self._entry_after_cutoff(e, cutoff)]
            kept.append(new_entry)
            self._write_all_locked(kept)

        logger.debug(
            "run_history_entry_written",
            user=user,
            outcome=outcome,
            path=str(self._log_path),
        )

    # ── Internal helpers ───────────────────────────────────────────────────

    def _ensure_dir(self) -> None:
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self._log_path.parent, stat.S_IRWXU)

    def _parse_line(self, raw: str, lineno: int) -> RunHistoryEntry | None:
        """Parse a single JSONL line; return None and log warning on failure."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning(
                "run_history_malformed_entry",
                lineno=lineno,
                error=str(exc),
            )
            return None
        try:
            return RunHistoryEntry(
                schema_version=data.get("schema_version", "1"),
                user=data["user"],
                completed_at=data["completed_at"],
                period_label=data.get("period_label", ""),
                outcome=data["outcome"],
            )
        except (KeyError, TypeError) as exc:
            logger.warning(
                "run_history_missing_fields",
                lineno=lineno,
                error=str(exc),
            )
            return None

    def _read_all_locked(self) -> list[RunHistoryEntry]:
        """Read and parse all valid entries. Must be called while lock is held."""
        if not self._log_path.exists():
            return []
        entries: list[RunHistoryEntry] = []
        lines = self._log_path.read_text(encoding="utf-8").splitlines()
        for lineno, raw in enumerate(lines, start=1):
            raw = raw.strip()
            if not raw:
                continue
            entry = self._parse_line(raw, lineno)
            if entry is not None:
                entries.append(entry)
        return entries

    def _write_all_locked(self, entries: list[RunHistoryEntry]) -> None:
        """Rewrite the file with *entries*. Must be called while lock is held."""
        with open(self._log_path, "w", encoding="utf-8") as fh:
            for entry in entries:
                fh.write(json.dumps(asdict(entry)) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    @staticmethod
    def _entry_after_cutoff(entry: RunHistoryEntry, cutoff: datetime) -> bool:
        """Return True if the entry's timestamp is within the retention window."""
        try:
            ts = datetime.fromisoformat(entry.completed_at.replace("Z", "+00:00"))
            return ts >= cutoff
        except ValueError:
            return True  # Keep unparseable entries rather than silently drop
