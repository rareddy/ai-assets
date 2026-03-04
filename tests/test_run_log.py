"""Tests for RunTrace audit log with MCP agentic fields."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from status_report.run_log import RunLogger, RunTrace, SkippedSourceEntry, _validate_no_secrets


class TestRunTrace:
    """Test RunTrace model with v2.0 schema."""

    def test_creates_valid_trace(self):
        trace = RunTrace(
            timestamp="2026-03-01T12:00:00.000000Z",
            user="alice@example.com",
            period="today",
            format="text",
            sources_attempted=["github", "jira"],
            counts={},
            outcome="success",
            skipped=[],
            retries={},
            duration_seconds=5.123,
            agent_turns=3,
            tool_calls_count=7,
            total_tokens=1500,
            mcp_servers_started=["github", "jira"],
        )
        assert trace.schema_version == "2.0"
        assert trace.agent_turns == 3
        assert trace.tool_calls_count == 7
        assert trace.total_tokens == 1500
        assert trace.mcp_servers_started == ["github", "jira"]

    def test_defaults_for_mcp_fields(self):
        """MCP fields default to 0/empty when not provided."""
        trace = RunTrace(
            timestamp="2026-03-01T12:00:00.000000Z",
            user="alice",
            period="today",
            format="text",
            sources_attempted=[],
            counts={},
            outcome="success",
            skipped=[],
            retries={},
            duration_seconds=1.0,
        )
        assert trace.agent_turns == 0
        assert trace.tool_calls_count == 0
        assert trace.total_tokens == 0
        assert trace.mcp_servers_started == []

    def test_invalid_timestamp_rejected(self):
        with pytest.raises(Exception):
            RunTrace(
                timestamp="not-a-timestamp",
                user="alice",
                period="today",
                format="text",
                sources_attempted=[],
                counts={},
                outcome="success",
                skipped=[],
                retries={},
                duration_seconds=1.0,
            )

    def test_skipped_source_entry(self):
        entry = SkippedSourceEntry(
            source="jira",
            reason="not_configured",
            attempts=0,
        )
        assert entry.source == "jira"


class TestValidateNoSecrets:
    """Test credential sentinel validation."""

    def test_clean_entry_passes(self):
        entry = {"user": "alice", "period": "today", "outcome": "success"}
        _validate_no_secrets(entry)  # Should not raise

    def test_token_detected(self):
        entry = {"user": "alice", "period": "today", "notes": "token=abc123"}
        with pytest.raises(ValueError, match="forbidden"):
            _validate_no_secrets(entry)

    def test_password_detected(self):
        entry = {"password=": "secret"}
        with pytest.raises(ValueError, match="forbidden"):
            _validate_no_secrets(entry)

    def test_api_key_detected(self):
        entry = {"notes": "set api_key to xyz"}
        with pytest.raises(ValueError, match="forbidden"):
            _validate_no_secrets(entry)

    def test_private_key_detected(self):
        entry = {"data": "BEGIN PRIVATE KEY"}
        with pytest.raises(ValueError, match="forbidden"):
            _validate_no_secrets(entry)


class TestRunLogger:
    """Test JSONL log writing."""

    def test_write_and_read(self, tmp_path):
        log_path = tmp_path / "runs.log"
        logger = RunLogger(log_path=log_path)

        trace = RunTrace(
            timestamp="2026-03-01T12:00:00.000000Z",
            user="alice",
            period="today",
            format="markdown",
            sources_attempted=["github"],
            counts={},
            outcome="success",
            skipped=[],
            retries={},
            duration_seconds=2.5,
            agent_turns=5,
            tool_calls_count=12,
            total_tokens=3000,
            mcp_servers_started=["github"],
        )

        logger.log_run(trace)

        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["schema_version"] == "2.0"
        assert data["agent_turns"] == 5
        assert data["tool_calls_count"] == 12
        assert data["total_tokens"] == 3000
        assert data["mcp_servers_started"] == ["github"]

    def test_rejects_secret_content(self, tmp_path):
        log_path = tmp_path / "runs.log"
        logger = RunLogger(log_path=log_path)

        trace = RunTrace(
            timestamp="2026-03-01T12:00:00.000000Z",
            user="token=abc123",  # Credential in user field
            period="today",
            format="text",
            sources_attempted=[],
            counts={},
            outcome="success",
            skipped=[],
            retries={},
            duration_seconds=1.0,
        )

        with pytest.raises(ValueError, match="forbidden"):
            logger.log_run(trace)

    def test_multiple_entries(self, tmp_path):
        log_path = tmp_path / "runs.log"
        logger = RunLogger(log_path=log_path)

        for i in range(3):
            trace = RunTrace(
                timestamp=f"2026-03-0{i+1}T12:00:00.000000Z",
                user="alice",
                period="today",
                format="text",
                sources_attempted=[],
                counts={},
                outcome="success",
                skipped=[],
                retries={},
                duration_seconds=1.0,
                agent_turns=i,
            )
            logger.log_run(trace)

        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 3
