"""Tests for agent orchestrator: asyncio.gather, single Claude call, Report output."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from status_report.config import Config, ReportPeriod
from status_report.report import Report, ReportSection, format_report
from status_report.run_log import RunTrace
from status_report.skills.base import ActivityItem, ActivitySkill, SkillPermanentError
from tests.conftest import make_activity_item


# ── Stub skill for testing ───────────────────────────────────────────────────


class _StubSkill(ActivitySkill):
    """Concrete stub skill that returns configurable items."""

    def __init__(self, items: list[ActivityItem], name: str = "stub") -> None:
        self._items = items
        self._name = name
        # Override the auto-registration name to avoid polluting global registry
        ActivitySkill._registry.pop(name, None)

    def is_configured(self) -> bool:
        return True

    async def fetch_activity(self, user: str, start: datetime, end: datetime) -> list[ActivityItem]:
        return self._items


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def period(now: datetime) -> ReportPeriod:
    return ReportPeriod(
        label="today",
        start=now.replace(hour=0, minute=0, second=0, microsecond=0),
        end=now,
    )


@pytest.fixture
def two_items() -> list[ActivityItem]:
    return [
        make_activity_item(source="jira", title="JIRA-10 Fix bug"),
        make_activity_item(source="github", title="PR #5 Refactor auth"),
    ]


@pytest.fixture
def stub_skills(two_items: list[ActivityItem]) -> list[ActivitySkill]:
    return [_StubSkill(two_items[:1], "jira_stub"), _StubSkill(two_items[1:], "github_stub")]


# ── Agent tests ───────────────────────────────────────────────────────────────


class TestRunAgentHappyPath:
    @pytest.mark.asyncio
    async def test_calls_anthropic_exactly_once(
        self, config: Config, period: ReportPeriod, stub_skills: list[ActivitySkill]
    ):
        from status_report.agent import run_agent

        fake_text = "## Key Accomplishments\n- Fixed bug\n- Refactored auth"
        fake_response = MagicMock()
        fake_response.content = [MagicMock(text=fake_text)]

        with patch("status_report.agent.anthropic") as mock_anthropic_mod, \
             patch("status_report.agent.RunLogger") as mock_logger_cls:
            client = MagicMock()
            client.messages.create.return_value = fake_response
            mock_anthropic_mod.AnthropicVertex.return_value = client
            mock_logger_cls.return_value.log_run = MagicMock()

            report = await run_agent(
                config=config,
                user="alice@example.com",
                period=period,
                enabled_skills=stub_skills,
                output_format="text",
            )

        # Claude called exactly once
        client.messages.create.assert_called_once()
        assert report is not None

    @pytest.mark.asyncio
    async def test_all_skills_called_concurrently(
        self, config: Config, period: ReportPeriod
    ):
        """Verify asyncio.gather is used (all skills' fetch_activity are awaited)."""
        from status_report.agent import run_agent

        call_log: list[str] = []

        class _TrackedSkill(ActivitySkill):
            def __init__(self, name: str):
                self._name = name

            def is_configured(self) -> bool:
                return True

            async def fetch_activity(self, user, start, end):
                call_log.append(self._name)
                return [make_activity_item(source=self._name)]

        skills = [_TrackedSkill("s1"), _TrackedSkill("s2"), _TrackedSkill("s3")]

        fake_response = MagicMock()
        fake_response.content = [MagicMock(text="## Accomplishments\n- Done")]

        with patch("status_report.agent.anthropic") as mock_anthropic_mod, \
             patch("status_report.agent.RunLogger"):
            client = MagicMock()
            client.messages.create.return_value = fake_response
            mock_anthropic_mod.AnthropicVertex.return_value = client

            await run_agent(
                config=config,
                user="alice@example.com",
                period=period,
                enabled_skills=skills,
                output_format="text",
            )

        assert set(call_log) == {"s1", "s2", "s3"}

    @pytest.mark.asyncio
    async def test_report_contains_sections(
        self, config: Config, period: ReportPeriod, stub_skills: list[ActivitySkill]
    ):
        from status_report.agent import run_agent

        fake_response = MagicMock()
        fake_response.content = [MagicMock(text="## Key Accomplishments\n- Fixed stuff")]

        with patch("status_report.agent.anthropic") as mock_mod, \
             patch("status_report.agent.RunLogger"):
            client = MagicMock()
            client.messages.create.return_value = fake_response
            mock_mod.AnthropicVertex.return_value = client

            report = await run_agent(
                config=config,
                user="alice@example.com",
                period=period,
                enabled_skills=stub_skills,
                output_format="text",
            )

        assert report.user == "alice@example.com"
        assert report.period == period
        assert isinstance(report.sections, list)

    @pytest.mark.asyncio
    async def test_run_trace_written_to_log(
        self, config: Config, period: ReportPeriod, stub_skills: list[ActivitySkill]
    ):
        from status_report.agent import run_agent

        fake_response = MagicMock()
        fake_response.content = [MagicMock(text="## Summary\n- Done")]

        logged_traces: list[RunTrace] = []

        with patch("status_report.agent.anthropic") as mock_mod, \
             patch("status_report.agent.RunLogger") as mock_logger_cls:
            client = MagicMock()
            client.messages.create.return_value = fake_response
            mock_mod.AnthropicVertex.return_value = client

            logger_instance = MagicMock()
            logger_instance.log_run.side_effect = lambda t: logged_traces.append(t)
            mock_logger_cls.return_value = logger_instance

            await run_agent(
                config=config,
                user="alice@example.com",
                period=period,
                enabled_skills=stub_skills,
                output_format="text",
            )

        assert len(logged_traces) == 1
        trace = logged_traces[0]
        assert trace.user == "alice@example.com"
        assert trace.outcome in ("success", "partial", "failed")


class TestRunAgentAggregation:
    @pytest.mark.asyncio
    async def test_items_from_all_skills_passed_to_claude(
        self, config: Config, period: ReportPeriod
    ):
        """All ActivityItems from all skills must be included in the Claude prompt."""
        from status_report.agent import run_agent

        items_a = [make_activity_item(source="jira", title="JIRA-1")]
        items_b = [make_activity_item(source="github", title="PR-1")]

        skills = [_StubSkill(items_a, "a"), _StubSkill(items_b, "b")]

        captured_prompt: list[str] = []

        def capture_create(**kwargs):
            for msg in kwargs.get("messages", []):
                if isinstance(msg.get("content"), str):
                    captured_prompt.append(msg["content"])
                elif isinstance(msg.get("content"), list):
                    for block in msg["content"]:
                        if isinstance(block, dict) and "text" in block:
                            captured_prompt.append(block["text"])
            r = MagicMock()
            r.content = [MagicMock(text="## Summary\n- done")]
            return r

        with patch("status_report.agent.anthropic") as mock_mod, \
             patch("status_report.agent.RunLogger"):
            client = MagicMock()
            client.messages.create.side_effect = capture_create
            mock_mod.AnthropicVertex.return_value = client

            await run_agent(
                config=config,
                user="alice@example.com",
                period=period,
                enabled_skills=skills,
                output_format="text",
            )

        all_prompt_text = " ".join(captured_prompt)
        assert "JIRA-1" in all_prompt_text
        assert "PR-1" in all_prompt_text


class TestRunAgentFailureHandling:
    """Tests for graceful failure handling: permanent errors, transient retries, all-fail."""

    @pytest.mark.asyncio
    async def test_permanent_failure_adds_skipped_source(
        self, config: Config, period: ReportPeriod
    ):
        """SkillPermanentError from a skill → SkippedSource in report; other skills succeed."""
        from status_report.agent import run_agent

        class _CredFailSkill(ActivitySkill):
            def is_configured(self) -> bool:
                return True

            async def fetch_activity(self, user, start, end):
                raise SkillPermanentError(reason="credentials_missing")

        good_items = [make_activity_item(source="github", title="PR #99")]
        skills = [_CredFailSkill(), _StubSkill(good_items, "goodstub")]

        fake_response = MagicMock()
        fake_response.content = [MagicMock(text="## Key Accomplishments\n- PR #99")]

        with patch("status_report.agent.anthropic") as mock_mod, \
             patch("status_report.agent.RunLogger"), \
             patch("asyncio.sleep", new=AsyncMock()):
            client = MagicMock()
            client.messages.create.return_value = fake_response
            mock_mod.AnthropicVertex.return_value = client

            report = await run_agent(
                config=config,
                user="alice@example.com",
                period=period,
                enabled_skills=skills,
                output_format="text",
            )

        assert len(report.skipped_sources) == 1
        skipped = report.skipped_sources[0]
        assert skipped.reason == "credentials_missing"

    @pytest.mark.asyncio
    async def test_transient_error_retried_three_times_then_skipped(
        self, config: Config, period: ReportPeriod
    ):
        """Transient 503 → retried 3 times → SkippedSource with reason 'transient_error_exhausted'."""
        from status_report.agent import run_agent

        call_count = 0

        class _TransientSkill(ActivitySkill):
            def is_configured(self) -> bool:
                return True

            async def fetch_activity(self, user, start, end):
                nonlocal call_count
                call_count += 1
                req = httpx.Request("GET", "http://example.com/api")
                resp = httpx.Response(503, request=req)
                raise httpx.HTTPStatusError("Service Unavailable", request=req, response=resp)

        good_items = [make_activity_item(source="jira", title="JIRA-1")]
        skills = [_TransientSkill(), _StubSkill(good_items, "goodjira")]

        fake_response = MagicMock()
        fake_response.content = [MagicMock(text="## Key Accomplishments\n- JIRA-1")]

        with patch("status_report.agent.anthropic") as mock_mod, \
             patch("status_report.agent.RunLogger"), \
             patch("asyncio.sleep", new=AsyncMock()):
            client = MagicMock()
            client.messages.create.return_value = fake_response
            mock_mod.AnthropicVertex.return_value = client

            report = await run_agent(
                config=config,
                user="alice@example.com",
                period=period,
                enabled_skills=skills,
                output_format="text",
            )

        assert call_count == 3, f"Expected 3 retry attempts, got {call_count}"
        assert len(report.skipped_sources) == 1
        assert report.skipped_sources[0].reason == "transient_error_exhausted"

    @pytest.mark.asyncio
    async def test_all_sources_fail_produces_empty_report(
        self, config: Config, period: ReportPeriod
    ):
        """All skills fail permanently → empty report sections, outcome='failed'."""
        from status_report.agent import run_agent

        class _AlwaysFailSkill(ActivitySkill):
            def is_configured(self) -> bool:
                return True

            async def fetch_activity(self, user, start, end):
                raise SkillPermanentError(reason="credentials_missing")

        skills = [_AlwaysFailSkill(), _AlwaysFailSkill()]

        logged_traces: list[RunTrace] = []

        with patch("status_report.agent.RunLogger") as mock_logger_cls, \
             patch("asyncio.sleep", new=AsyncMock()):
            logger_instance = MagicMock()
            logger_instance.log_run.side_effect = lambda t: logged_traces.append(t)
            mock_logger_cls.return_value = logger_instance

            report = await run_agent(
                config=config,
                user="alice@example.com",
                period=period,
                enabled_skills=skills,
                output_format="text",
            )

        assert report.sections == []
        assert len(report.skipped_sources) == 2
        assert len(logged_traces) == 1
        assert logged_traces[0].outcome == "failed"

    @pytest.mark.asyncio
    async def test_retry_count_captured_in_run_trace(
        self, config: Config, period: ReportPeriod
    ):
        """After transient retries, RunTrace.retries contains the retry count > 0."""
        from status_report.agent import run_agent

        class _RetryTrackedSkill(ActivitySkill):
            def is_configured(self) -> bool:
                return True

            async def fetch_activity(self, user, start, end):
                req = httpx.Request("GET", "http://example.com/api")
                resp = httpx.Response(503, request=req)
                raise httpx.HTTPStatusError("Service Unavailable", request=req, response=resp)

        skills = [_RetryTrackedSkill()]
        logged_traces: list[RunTrace] = []

        with patch("status_report.agent.RunLogger") as mock_logger_cls, \
             patch("asyncio.sleep", new=AsyncMock()):
            logger_instance = MagicMock()
            logger_instance.log_run.side_effect = lambda t: logged_traces.append(t)
            mock_logger_cls.return_value = logger_instance

            await run_agent(
                config=config,
                user="alice@example.com",
                period=period,
                enabled_skills=skills,
                output_format="text",
            )

        assert len(logged_traces) == 1
        trace = logged_traces[0]
        assert any(count > 0 for count in trace.retries.values()), (
            f"Expected retry count > 0 in RunTrace.retries, got: {trace.retries}"
        )

    @pytest.mark.asyncio
    async def test_no_activity_not_treated_as_failure(
        self, config: Config, period: ReportPeriod
    ):
        """Skill returning [] due to no activity is NOT added to skipped_sources."""
        from status_report.agent import run_agent

        skills = [_StubSkill([], "emptyskill")]

        with patch("status_report.agent.RunLogger") as mock_logger_cls, \
             patch("asyncio.sleep", new=AsyncMock()):
            logger_instance = MagicMock()
            logged_traces: list[RunTrace] = []
            logger_instance.log_run.side_effect = lambda t: logged_traces.append(t)
            mock_logger_cls.return_value = logger_instance

            report = await run_agent(
                config=config,
                user="alice@example.com",
                period=period,
                enabled_skills=skills,
                output_format="text",
            )

        # No activity is not a failure — skipped_sources must be empty
        assert report.skipped_sources == []
        assert len(logged_traces) == 1
        assert logged_traces[0].outcome == "success"


class TestRunAgentSourceFiltering:
    """Tests that source filtering integrates correctly with the agent."""

    @pytest.mark.asyncio
    async def test_only_enabled_skills_are_called(
        self, config: Config, period: ReportPeriod
    ):
        """Only the skills in enabled_skills have their fetch_activity called."""
        from status_report.agent import run_agent

        called: list[str] = []

        class _TrackedJira(ActivitySkill):
            def is_configured(self): return True
            async def fetch_activity(self, user, start, end):
                called.append("jira")
                return [make_activity_item(source="jira")]

        class _TrackedSlack(ActivitySkill):
            def is_configured(self): return True
            async def fetch_activity(self, user, start, end):
                called.append("slack")
                return [make_activity_item(source="slack")]

        # Only pass the Jira skill — Slack should never be called
        skills = [_TrackedJira()]

        fake_response = MagicMock()
        fake_response.content = [MagicMock(text="## Summary\n- done")]

        with patch("status_report.agent.anthropic") as mock_mod, \
             patch("status_report.agent.RunLogger"):
            client = MagicMock()
            client.messages.create.return_value = fake_response
            mock_mod.AnthropicVertex.return_value = client

            await run_agent(
                config=config,
                user="alice@example.com",
                period=period,
                enabled_skills=skills,
                output_format="text",
            )

        assert called == ["jira"]

    @pytest.mark.asyncio
    async def test_pre_skipped_appear_in_report_skipped_sources(
        self, config: Config, period: ReportPeriod
    ):
        """Unconfigured-but-requested sources passed as pre_skipped appear in the report."""
        from status_report.agent import run_agent
        from status_report.report import SkippedSource

        good_items = [make_activity_item(source="github", title="PR #1")]
        skills = [_StubSkill(good_items, "githubstub")]

        pre_skipped = [SkippedSource(source="jira", reason="not_configured", attempts=0)]

        fake_response = MagicMock()
        fake_response.content = [MagicMock(text="## Key Accomplishments\n- PR #1")]

        with patch("status_report.agent.anthropic") as mock_mod, \
             patch("status_report.agent.RunLogger"):
            client = MagicMock()
            client.messages.create.return_value = fake_response
            mock_mod.AnthropicVertex.return_value = client

            report = await run_agent(
                config=config,
                user="alice@example.com",
                period=period,
                enabled_skills=skills,
                output_format="text",
                pre_skipped=pre_skipped,
            )

        skipped_sources = {s.source for s in report.skipped_sources}
        assert "jira" in skipped_sources
        reasons = {s.reason for s in report.skipped_sources}
        assert "not_configured" in reasons

    @pytest.mark.asyncio
    async def test_pre_skipped_and_runtime_failures_merged(
        self, config: Config, period: ReportPeriod
    ):
        """pre_skipped entries are merged with runtime failures in skipped_sources."""
        from status_report.agent import run_agent
        from status_report.report import SkippedSource

        pre_skipped = [SkippedSource(source="slack", reason="not_configured", attempts=0)]

        class _FailSkill(ActivitySkill):
            def is_configured(self): return True
            async def fetch_activity(self, user, start, end):
                raise SkillPermanentError(reason="credentials_missing")

        skills = [_FailSkill()]

        with patch("status_report.agent.RunLogger"), \
             patch("asyncio.sleep", new=AsyncMock()):

            report = await run_agent(
                config=config,
                user="alice@example.com",
                period=period,
                enabled_skills=skills,
                output_format="text",
                pre_skipped=pre_skipped,
            )

        skipped_sources = {s.source for s in report.skipped_sources}
        assert "slack" in skipped_sources      # from pre_skipped
        assert len(report.skipped_sources) == 2  # slack + the failing skill


# ── Helpers shared with TestAutoperiodLabelInOutput ───────────────────────────

_PERIOD_START = datetime(2026, 2, 27, 9, 0, 0, tzinfo=UTC)
_PERIOD_END = datetime(2026, 2, 28, 9, 0, 0, tzinfo=UTC)


def _make_report_with_label(label: str, fmt: str = "text") -> Report:
    period = ReportPeriod(label=label, start=_PERIOD_START, end=_PERIOD_END)
    return Report(
        period=period,
        user="alice@example.com",
        format=fmt,
        sections=[ReportSection(heading="Key Accomplishments", content="- Merged PR #42")],
        skipped_sources=[],
        generated_at=datetime(2026, 2, 28, 9, 0, 0, tzinfo=UTC),
    )


class TestAutoperiodLabelInOutput:
    """Verify auto-computed period labels flow through format_report() unchanged."""

    _LAST_RUN_LABEL = "since last run at 2026-02-27T09:00:00Z"
    _FIRST_RUN_LABEL = "today (first run)"

    def test_since_last_run_label_in_text_format(self) -> None:
        report = _make_report_with_label(self._LAST_RUN_LABEL, fmt="text")
        output = format_report(report)
        assert "since last run" in output
        assert "2026-02-27T09:00:00Z" in output

    def test_since_last_run_label_in_markdown_format(self) -> None:
        report = _make_report_with_label(self._LAST_RUN_LABEL, fmt="markdown")
        output = format_report(report)
        assert "since last run" in output

    def test_since_last_run_label_in_json_format(self) -> None:
        import json as _json

        report = _make_report_with_label(self._LAST_RUN_LABEL, fmt="json")
        output = format_report(report)
        data = _json.loads(output)
        assert data["period"]["label"] == self._LAST_RUN_LABEL

    def test_first_run_label_in_text_format(self) -> None:
        report = _make_report_with_label(self._FIRST_RUN_LABEL, fmt="text")
        output = format_report(report)
        assert "today (first run)" in output

    def test_first_run_label_in_markdown_format(self) -> None:
        report = _make_report_with_label(self._FIRST_RUN_LABEL, fmt="markdown")
        output = format_report(report)
        assert "today (first run)" in output

    def test_first_run_label_in_json_format(self) -> None:
        import json as _json

        report = _make_report_with_label(self._FIRST_RUN_LABEL, fmt="json")
        output = format_report(report)
        data = _json.loads(output)
        assert data["period"]["label"] == self._FIRST_RUN_LABEL

    @pytest.mark.asyncio
    async def test_run_agent_period_label_propagates_to_report(
        self, config: Config
    ) -> None:
        """When run_agent receives an auto-computed period, report.period.label is preserved."""
        from status_report.agent import run_agent

        auto_period = ReportPeriod(
            label=self._LAST_RUN_LABEL,
            start=_PERIOD_START,
            end=_PERIOD_END,
        )
        good_items = [make_activity_item(source="github", title="PR #1")]
        skills = [_StubSkill(good_items, "githubstub2")]

        fake_response = MagicMock()
        fake_response.content = [MagicMock(text="## Key Accomplishments\n- PR #1")]

        with patch("status_report.agent.anthropic") as mock_mod, \
             patch("status_report.agent.RunLogger"), \
             patch("status_report.agent.RunHistoryStore"):
            client = MagicMock()
            client.messages.create.return_value = fake_response
            mock_mod.AnthropicVertex.return_value = client

            report = await run_agent(
                config=config,
                user="alice@example.com",
                period=auto_period,
                enabled_skills=skills,
                output_format="text",
            )

        assert report.period.label == self._LAST_RUN_LABEL
