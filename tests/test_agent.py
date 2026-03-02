"""Tests for the Claude agent loop with MCP tools."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from status_report.agent import _build_user_message, _parse_claude_response, run_agent
from status_report.config import Config, ReportPeriod
from status_report.mcp.executor import ToolExecutor
from status_report.mcp.registry import ToolRegistry
from status_report.report import SkippedSource
from tests.conftest import make_server_handle, make_text_response, make_tool_use_response


@pytest.fixture
def sample_period():
    now = datetime.now(UTC)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return ReportPeriod(label="today", start=start, end=now)


@pytest.fixture
def registry_and_executor(github_mcp_config):
    """Set up a registry with GitHub tools and an executor."""
    handle = make_server_handle(github_mcp_config)
    registry = ToolRegistry()
    registry.register_server(handle)
    executor = ToolExecutor(registry)

    # Default: mock call_tool to return empty results
    mock_result = MagicMock()
    mock_content = MagicMock()
    mock_content.text = json.dumps({"items": []})
    mock_result.content = [mock_content]
    handle.session.call_tool = AsyncMock(return_value=mock_result)

    return registry, executor, handle


class TestBuildUserMessage:
    def test_includes_user_and_period(self, sample_period):
        msg = _build_user_message("alice@example.com", sample_period, ["github", "jira"])
        assert "alice@example.com" in msg
        assert "today" in msg
        assert "github" in msg
        assert "jira" in msg

    def test_handles_no_sources(self, sample_period):
        msg = _build_user_message("alice", sample_period, [])
        assert "all configured" in msg


class TestParseCloudeResponse:
    def test_parses_sections(self, sample_period):
        text = (
            "## Key Accomplishments\n\n"
            "- Merged PR #42 for authentication\n\n"
            "## Code Contributions\n\n"
            "- Reviewed 3 PRs in the backend repo\n"
        )
        report = _parse_claude_response(text, sample_period, "alice", "text")

        assert len(report.sections) == 2
        assert report.sections[0].heading == "Key Accomplishments"
        assert "Merged PR #42" in report.sections[0].content
        assert report.sections[1].heading == "Code Contributions"

    def test_empty_text(self, sample_period):
        report = _parse_claude_response("", sample_period, "alice", "text")
        assert len(report.sections) == 0
        assert report.raw_text == ""


class TestRunAgent:
    """Test the agent loop with mocked Claude responses."""

    @pytest.fixture
    def mock_config(self, monkeypatch):
        monkeypatch.setenv("VERTEX_PROJECT_ID", "test-project")
        monkeypatch.setenv("VERTEX_REGION", "us-east5")
        monkeypatch.setenv("CLAUDE_MODEL", "claude-sonnet-4-6")
        monkeypatch.setenv("MAX_AGENT_TURNS", "10")
        return Config()

    @pytest.mark.asyncio
    async def test_single_turn_end(
        self, mock_config, sample_period, registry_and_executor
    ):
        """Claude produces a report in a single turn (no tool calls)."""
        registry, executor, _ = registry_and_executor

        mock_response = make_text_response(
            "## Key Accomplishments\n\n- Completed the auth feature\n"
        )

        with patch("status_report.agent.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.AnthropicVertex.return_value = mock_client

            with patch("status_report.agent.RunLogger"):
                with patch("status_report.agent.RunHistoryStore"):
                    report = await run_agent(
                        config=mock_config,
                        user="alice@example.com",
                        period=sample_period,
                        registry=registry,
                        executor=executor,
                        output_format="text",
                    )

        assert len(report.sections) >= 1
        assert "auth feature" in report.raw_text

    @pytest.mark.asyncio
    async def test_tool_use_then_end(
        self, mock_config, sample_period, registry_and_executor
    ):
        """Claude calls a tool, gets results, then produces the report."""
        registry, executor, handle = registry_and_executor

        # First response: Claude calls search_issues
        tool_response = make_tool_use_response([
            {"id": "call_1", "name": "search_issues", "input": {"q": "author:alice"}}
        ])

        # Second response: Claude writes the report
        final_response = make_text_response(
            "## Key Accomplishments\n\n- Fixed bug in login flow (issue #123)\n"
        )

        with patch("status_report.agent.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = [tool_response, final_response]
            mock_anthropic.AnthropicVertex.return_value = mock_client

            with patch("status_report.agent.RunLogger"):
                with patch("status_report.agent.RunHistoryStore"):
                    report = await run_agent(
                        config=mock_config,
                        user="alice@example.com",
                        period=sample_period,
                        registry=registry,
                        executor=executor,
                        output_format="text",
                    )

        assert len(report.sections) >= 1
        assert "login flow" in report.raw_text
        assert executor.call_count == 1

    @pytest.mark.asyncio
    async def test_multi_tool_turn(
        self, mock_config, sample_period, registry_and_executor
    ):
        """Claude calls multiple tools in one turn."""
        registry, executor, handle = registry_and_executor

        # Claude calls two tools in one response
        tool_response = make_tool_use_response([
            {"id": "call_1", "name": "search_issues", "input": {"q": "author:alice"}},
            {"id": "call_2", "name": "list_commits", "input": {"repo": "org/repo"}},
        ])

        final_response = make_text_response(
            "## Code Contributions\n\n- Pushed 5 commits to org/repo\n"
        )

        with patch("status_report.agent.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = [tool_response, final_response]
            mock_anthropic.AnthropicVertex.return_value = mock_client

            with patch("status_report.agent.RunLogger"):
                with patch("status_report.agent.RunHistoryStore"):
                    report = await run_agent(
                        config=mock_config,
                        user="alice@example.com",
                        period=sample_period,
                        registry=registry,
                        executor=executor,
                        output_format="text",
                    )

        assert executor.call_count == 2

    @pytest.mark.asyncio
    async def test_turn_limit_enforcement(
        self, sample_period, registry_and_executor, monkeypatch
    ):
        """Agent loop stops when max_agent_turns is reached."""
        monkeypatch.setenv("VERTEX_PROJECT_ID", "test-project")
        monkeypatch.setenv("VERTEX_REGION", "us-east5")
        monkeypatch.setenv("MAX_AGENT_TURNS", "2")  # Very low limit
        config = Config()

        registry, executor, handle = registry_and_executor

        # Claude keeps calling tools on every turn
        tool_response = make_tool_use_response([
            {"id": "call_1", "name": "search_issues", "input": {"q": "test"}}
        ])

        # Final response after turn limit message
        final_response = make_text_response(
            "## Key Accomplishments\n\n- Investigated but hit turn limit\n"
        )

        with patch("status_report.agent.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            # 2 turns of tool use, then the turn-limit final call
            mock_client.messages.create.side_effect = [
                tool_response, tool_response, final_response
            ]
            mock_anthropic.AnthropicVertex.return_value = mock_client

            with patch("status_report.agent.RunLogger"):
                with patch("status_report.agent.RunHistoryStore"):
                    report = await run_agent(
                        config=config,
                        user="alice",
                        period=sample_period,
                        registry=registry,
                        executor=executor,
                        output_format="text",
                    )

        assert "turn limit" in report.raw_text

    @pytest.mark.asyncio
    async def test_empty_registry_returns_empty_report(
        self, mock_config, sample_period
    ):
        """Empty registry (no tools) returns an empty report."""
        registry = ToolRegistry()  # No tools registered
        executor = ToolExecutor(registry)

        with patch("status_report.agent.RunLogger"):
            with patch("status_report.agent.RunHistoryStore"):
                report = await run_agent(
                    config=mock_config,
                    user="alice",
                    period=sample_period,
                    registry=registry,
                    executor=executor,
                    output_format="text",
                )

        assert len(report.sections) == 0
        assert report.raw_text == ""

    @pytest.mark.asyncio
    async def test_skipped_sources_propagated(
        self, mock_config, sample_period, registry_and_executor
    ):
        """Pre-skipped sources are included in the final report."""
        registry, executor, _ = registry_and_executor

        pre_skipped = [
            SkippedSource(source="jira", reason="not_configured", attempts=0),
        ]

        mock_response = make_text_response(
            "## Key Accomplishments\n\n- Did stuff\n"
        )

        with patch("status_report.agent.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.AnthropicVertex.return_value = mock_client

            with patch("status_report.agent.RunLogger"):
                with patch("status_report.agent.RunHistoryStore"):
                    report = await run_agent(
                        config=mock_config,
                        user="alice",
                        period=sample_period,
                        registry=registry,
                        executor=executor,
                        output_format="text",
                        pre_skipped=pre_skipped,
                    )

        assert len(report.skipped_sources) == 1
        assert report.skipped_sources[0].source == "jira"

    @pytest.mark.asyncio
    async def test_audit_log_written(
        self, mock_config, sample_period, registry_and_executor
    ):
        """RunTrace audit log is written after agent loop."""
        registry, executor, _ = registry_and_executor

        mock_response = make_text_response("## Report\n\n- Done\n")

        with patch("status_report.agent.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.AnthropicVertex.return_value = mock_client

            with patch("status_report.agent.RunLogger") as mock_logger_cls:
                mock_run_logger = MagicMock()
                mock_logger_cls.return_value = mock_run_logger

                with patch("status_report.agent.RunHistoryStore"):
                    await run_agent(
                        config=mock_config,
                        user="alice",
                        period=sample_period,
                        registry=registry,
                        executor=executor,
                        output_format="markdown",
                        mcp_servers_started=["github"],
                    )

                mock_run_logger.log_run.assert_called_once()
                trace = mock_run_logger.log_run.call_args[0][0]
                assert trace.schema_version == "2.0"
                assert trace.agent_turns > 0
                assert trace.mcp_servers_started == ["github"]
