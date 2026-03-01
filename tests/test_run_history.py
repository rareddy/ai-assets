"""Tests for RunHistoryStore (run_history.py).

All tests use tmp_path fixtures — no writes to real ~/.status-report/.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from status_report.run_history import RunHistoryEntry, RunHistoryStore


# ── Helpers ───────────────────────────────────────────────────────────────────


def _store(tmp_path: Path) -> RunHistoryStore:
    """Return a RunHistoryStore backed by tmp_path."""
    return RunHistoryStore(log_dir=tmp_path)


def _write_entry(tmp_path: Path, **kwargs) -> None:
    """Append a raw JSONL entry to the log file in tmp_path."""
    log_path = tmp_path / "run_history.log"
    entry = {
        "schema_version": "1",
        "user": "alice@example.com",
        "completed_at": "2026-01-01T00:00:00.000000Z",
        "period_label": "today",
        "outcome": "success",
    }
    entry.update(kwargs)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


# ── TestRunHistoryStoreRecordRun ──────────────────────────────────────────────


class TestRunHistoryStoreRecordRun:
    """Unit tests for RunHistoryStore.record_run()."""

    def test_creates_file_on_first_record(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        log_path = tmp_path / "run_history.log"
        assert not log_path.exists()

        store.record_run(
            user="alice@example.com",
            completed_at=datetime.now(UTC),
            outcome="success",
            period_label="today",
        )

        assert log_path.exists()

    def test_entry_has_correct_fields(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        now = datetime(2026, 2, 28, 9, 45, 0, tzinfo=UTC)

        store.record_run(
            user="alice@example.com",
            completed_at=now,
            outcome="success",
            period_label="today (first run)",
        )

        log_path = tmp_path / "run_history.log"
        lines = log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1

        data = json.loads(lines[0])
        assert data["schema_version"] == "1"
        assert data["user"] == "alice@example.com"
        assert data["period_label"] == "today (first run)"
        assert data["outcome"] == "success"
        # completed_at should be ISO 8601 UTC
        ts = datetime.fromisoformat(data["completed_at"].replace("Z", "+00:00"))
        assert ts.year == 2026
        assert ts.month == 2
        assert ts.day == 28

    def test_appends_multiple_entries(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        now = datetime.now(UTC)

        store.record_run(user="alice@example.com", completed_at=now, outcome="success", period_label="today")
        store.record_run(user="alice@example.com", completed_at=now, outcome="partial", period_label="today")

        log_path = tmp_path / "run_history.log"
        lines = [l for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 2

    def test_preserves_existing_entries_within_90_days(self, tmp_path: Path) -> None:
        # Pre-populate with a 30-day-old entry
        thirty_days_ago = datetime.now(UTC) - timedelta(days=30)
        _write_entry(
            tmp_path,
            user="alice@example.com",
            completed_at=thirty_days_ago.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            outcome="success",
            period_label="old run",
        )

        store = _store(tmp_path)
        store.record_run(
            user="alice@example.com",
            completed_at=datetime.now(UTC),
            outcome="success",
            period_label="today",
        )

        log_path = tmp_path / "run_history.log"
        lines = [l for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 2

        labels = [json.loads(l)["period_label"] for l in lines]
        assert "old run" in labels
        assert "today" in labels

    def test_prunes_entries_older_than_90_days(self, tmp_path: Path) -> None:
        # Pre-populate with a 91-day-old entry (should be pruned)
        old_ts = datetime.now(UTC) - timedelta(days=91)
        _write_entry(
            tmp_path,
            user="alice@example.com",
            completed_at=old_ts.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            outcome="success",
            period_label="ancient run",
        )

        store = _store(tmp_path)
        store.record_run(
            user="alice@example.com",
            completed_at=datetime.now(UTC),
            outcome="success",
            period_label="today",
        )

        log_path = tmp_path / "run_history.log"
        lines = [l for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 1

        data = json.loads(lines[0])
        assert data["period_label"] == "today"

    def test_does_not_record_failed_outcome(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        with pytest.raises(ValueError, match="invalid outcome"):
            store.record_run(
                user="alice@example.com",
                completed_at=datetime.now(UTC),
                outcome="failed",  # type: ignore[arg-type]
                period_label="today",
            )

    def test_multiple_users_stored_independently(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        now = datetime.now(UTC)

        store.record_run(user="alice@example.com", completed_at=now, outcome="success", period_label="alice-period")
        store.record_run(user="bob@example.com", completed_at=now, outcome="success", period_label="bob-period")

        log_path = tmp_path / "run_history.log"
        lines = [l for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 2

        users = {json.loads(l)["user"] for l in lines}
        assert "alice@example.com" in users
        assert "bob@example.com" in users

    def test_file_created_in_correct_directory(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.record_run(
            user="alice@example.com",
            completed_at=datetime.now(UTC),
            outcome="success",
            period_label="today",
        )

        log_path = tmp_path / "run_history.log"
        assert log_path.exists()
        assert log_path.parent == tmp_path


# ── TestRunHistoryStoreGetLastSuccessfulRun ───────────────────────────────────


class TestRunHistoryStoreGetLastSuccessfulRun:
    """Unit tests for RunHistoryStore.get_last_successful_run()."""

    def test_returns_none_when_file_does_not_exist(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        result = store.get_last_successful_run("alice@example.com")
        assert result is None

    def test_returns_none_when_file_is_empty(self, tmp_path: Path) -> None:
        log_path = tmp_path / "run_history.log"
        log_path.write_text("", encoding="utf-8")

        store = _store(tmp_path)
        result = store.get_last_successful_run("alice@example.com")
        assert result is None

    def test_returns_most_recent_success_entry_for_user(self, tmp_path: Path) -> None:
        t1 = "2026-01-01T08:00:00.000000Z"
        t2 = "2026-01-02T08:00:00.000000Z"
        t3 = "2026-01-03T08:00:00.000000Z"

        for ts, label in [(t1, "run1"), (t2, "run2"), (t3, "run3")]:
            _write_entry(tmp_path, user="alice@example.com", completed_at=ts, outcome="success", period_label=label)

        store = _store(tmp_path)
        result = store.get_last_successful_run("alice@example.com")
        assert result is not None
        ts_result, label_result = result
        assert label_result == "run3"
        assert ts_result.year == 2026
        assert ts_result.month == 1
        assert ts_result.day == 3

    def test_ignores_entries_for_other_users(self, tmp_path: Path) -> None:
        _write_entry(tmp_path, user="alice@example.com", completed_at="2026-01-01T08:00:00.000000Z", outcome="success", period_label="alice-run")
        _write_entry(tmp_path, user="bob@example.com", completed_at="2026-01-02T08:00:00.000000Z", outcome="success", period_label="bob-run")

        store = _store(tmp_path)
        result = store.get_last_successful_run("alice@example.com")
        assert result is not None
        _, label = result
        assert label == "alice-run"

    def test_skips_malformed_json_lines_with_warning(self, tmp_path: Path) -> None:
        log_path = tmp_path / "run_history.log"
        # One valid entry + one garbage line
        valid_entry = {
            "schema_version": "1",
            "user": "alice@example.com",
            "completed_at": "2026-01-01T08:00:00.000000Z",
            "period_label": "valid-run",
            "outcome": "success",
        }
        log_path.write_text(
            json.dumps(valid_entry) + "\n" + "NOT_VALID_JSON{{{" + "\n",
            encoding="utf-8",
        )

        store = _store(tmp_path)
        result = store.get_last_successful_run("alice@example.com")
        assert result is not None
        _, label = result
        assert label == "valid-run"

    def test_skips_future_dated_entries_with_warning(self, tmp_path: Path) -> None:
        future_ts = (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        _write_entry(
            tmp_path,
            user="alice@example.com",
            completed_at=future_ts,
            outcome="success",
            period_label="future-run",
        )

        store = _store(tmp_path)
        result = store.get_last_successful_run("alice@example.com")
        assert result is None

    def test_returns_none_when_only_failed_entries(self, tmp_path: Path) -> None:
        # Write a "failed" entry directly (bypassing record_run validation)
        _write_entry(
            tmp_path,
            user="alice@example.com",
            completed_at="2026-01-01T08:00:00.000000Z",
            outcome="failed",
            period_label="failed-run",
        )

        store = _store(tmp_path)
        result = store.get_last_successful_run("alice@example.com")
        assert result is None

    def test_returns_partial_outcome_as_valid(self, tmp_path: Path) -> None:
        _write_entry(
            tmp_path,
            user="alice@example.com",
            completed_at="2026-01-01T08:00:00.000000Z",
            outcome="partial",
            period_label="partial-run",
        )

        store = _store(tmp_path)
        result = store.get_last_successful_run("alice@example.com")
        assert result is not None
        _, label = result
        assert label == "partial-run"
