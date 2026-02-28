"""Tests for RunLogger: atomic JSONL append, credential rejection, security."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from status_report.run_log import RunLogger, RunTrace
from tests.conftest import make_run_trace


@pytest.fixture
def logger_under_test(tmp_log_dir: Path) -> RunLogger:
    log_path = tmp_log_dir / "runs.log"
    return RunLogger(log_path=log_path)


class TestRunLoggerHappyPath:
    def test_creates_log_file_on_first_write(self, logger_under_test: RunLogger, tmp_log_dir: Path):
        trace = make_run_trace()
        logger_under_test.log_run(trace)
        log_path = tmp_log_dir / "runs.log"
        assert log_path.exists()

    def test_appends_valid_jsonl_entry(self, logger_under_test: RunLogger, tmp_log_dir: Path):
        trace = make_run_trace()
        logger_under_test.log_run(trace)
        log_path = tmp_log_dir / "runs.log"
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["schema_version"] == "1.0"
        assert entry["user"] == "alice@example.com"
        assert entry["outcome"] == "success"

    def test_appends_multiple_entries(self, logger_under_test: RunLogger, tmp_log_dir: Path):
        for i in range(3):
            logger_under_test.log_run(make_run_trace(duration_seconds=float(i)))
        log_path = tmp_log_dir / "runs.log"
        lines = [l for l in log_path.read_text().strip().split("\n") if l]
        assert len(lines) == 3

    def test_each_line_is_valid_json(self, logger_under_test: RunLogger, tmp_log_dir: Path):
        logger_under_test.log_run(make_run_trace())
        logger_under_test.log_run(make_run_trace(outcome="partial"))
        log_path = tmp_log_dir / "runs.log"
        for line in log_path.read_text().strip().split("\n"):
            json.loads(line)  # must not raise

    def test_outcome_values(self, logger_under_test: RunLogger, tmp_log_dir: Path):
        for outcome in ("success", "partial", "failed"):
            logger_under_test.log_run(make_run_trace(outcome=outcome))
        log_path = tmp_log_dir / "runs.log"
        lines = [json.loads(l) for l in log_path.read_text().strip().split("\n") if l]
        outcomes = [e["outcome"] for e in lines]
        assert outcomes == ["success", "partial", "failed"]


class TestRunLoggerSecurityValidation:
    def test_rejects_entry_with_token_in_value(
        self, logger_under_test: RunLogger, tmp_log_dir: Path
    ):
        trace = make_run_trace(period="token=abc123")
        with pytest.raises(ValueError, match="forbidden content"):
            logger_under_test.log_run(trace)

    def test_rejects_entry_with_password(self, logger_under_test: RunLogger, tmp_log_dir: Path):
        trace = make_run_trace(period="password=secret")
        with pytest.raises(ValueError, match="forbidden content"):
            logger_under_test.log_run(trace)

    def test_no_file_written_on_rejection(self, logger_under_test: RunLogger, tmp_log_dir: Path):
        trace = make_run_trace(period="api_key=xyz")
        log_path = tmp_log_dir / "runs.log"
        with pytest.raises(ValueError):
            logger_under_test.log_run(trace)
        assert not log_path.exists()

    def test_rejects_entry_with_authorization_header(
        self, logger_under_test: RunLogger, tmp_log_dir: Path
    ):
        """Entry containing an HTTP Authorization header is rejected."""
        trace = make_run_trace(user="Authorization: Bearer ghp_secret")
        with pytest.raises(ValueError, match="forbidden content"):
            logger_under_test.log_run(trace)

    def test_rejects_entry_with_private_key_marker(
        self, logger_under_test: RunLogger, tmp_log_dir: Path
    ):
        """Entry containing PEM private key marker is rejected."""
        trace = make_run_trace(user="-----BEGIN PRIVATE KEY-----")
        with pytest.raises(ValueError, match="forbidden content"):
            logger_under_test.log_run(trace)


class TestRunTrace:
    def test_valid_trace_constructs(self):
        trace = make_run_trace()
        assert trace.schema_version == "1.0"

    def test_invalid_timestamp_raises(self):
        with pytest.raises(Exception):
            make_run_trace(timestamp="not-a-date")

    def test_invalid_outcome_raises(self):
        with pytest.raises(Exception):
            make_run_trace(outcome="unknown")
