"""Tests for report formatters: text, markdown, JSON."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from status_report.config import ReportPeriod
from status_report.report import Report, ReportSection, SkippedSource, format_report


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_period(label: str = "today") -> ReportPeriod:
    start = datetime(2026, 2, 28, 0, 0, 0, tzinfo=UTC)
    end = datetime(2026, 2, 28, 9, 45, 0, tzinfo=UTC)
    return ReportPeriod(label=label, start=start, end=end)


def _make_report(
    fmt: str = "text",
    sections: list[ReportSection] | None = None,
    skipped: list[SkippedSource] | None = None,
    period: ReportPeriod | None = None,
    user: str = "alice@example.com",
) -> Report:
    return Report(
        period=period or _make_period(),
        user=user,
        format=fmt,
        sections=sections or [
            ReportSection(heading="Key Accomplishments", content="- Merged PR #42"),
            ReportSection(heading="Tickets & Issues", content="- JIRA-100 resolved"),
        ],
        skipped_sources=skipped or [],
        generated_at=datetime(2026, 2, 28, 9, 45, 30, tzinfo=UTC),
    )


# ── Text format ───────────────────────────────────────────────────────────────


class TestTextFormat:
    def test_contains_user_and_date(self):
        output = format_report(_make_report(fmt="text"))
        assert "alice@example.com" in output
        assert "2026-02-28" in output

    def test_section_headings_are_uppercased(self):
        output = format_report(_make_report(fmt="text"))
        assert "KEY ACCOMPLISHMENTS" in output
        assert "TICKETS & ISSUES" in output

    def test_section_content_is_present(self):
        output = format_report(_make_report(fmt="text"))
        assert "Merged PR #42" in output
        assert "JIRA-100 resolved" in output

    def test_separator_line_present(self):
        output = format_report(_make_report(fmt="text"))
        assert "=" * 60 in output

    def test_no_markdown_hash_headings(self):
        output = format_report(_make_report(fmt="text"))
        assert "## " not in output
        assert "# " not in output

    def test_skipped_sources_rendered_as_footer(self):
        skipped = [SkippedSource(source="gdrive", reason="credentials_missing", attempts=1)]
        output = format_report(_make_report(fmt="text", skipped=skipped))
        assert "⚠" in output
        assert "gdrive" in output
        assert "credentials_missing" in output

    def test_no_skipped_footer_when_none(self):
        output = format_report(_make_report(fmt="text", skipped=[]))
        assert "⚠" not in output

    def test_multiple_skipped_sources_all_rendered(self):
        skipped = [
            SkippedSource(source="jira", reason="credentials_missing", attempts=1),
            SkippedSource(source="slack", reason="transient_error_exhausted", attempts=3),
        ]
        output = format_report(_make_report(fmt="text", skipped=skipped))
        assert "jira" in output
        assert "slack" in output

    def test_empty_sections_still_renders_header(self):
        output = format_report(_make_report(fmt="text", sections=[]))
        assert "alice@example.com" in output

    def test_format_report_dispatches_to_text_by_default(self):
        report = _make_report(fmt="text")
        output = format_report(report)
        assert "Status Report" in output
        assert "KEY ACCOMPLISHMENTS" in output


# ── Markdown format ───────────────────────────────────────────────────────────


class TestMarkdownFormat:
    def test_h1_title_contains_user_and_date(self):
        output = format_report(_make_report(fmt="markdown"))
        assert "# Status Report — alice@example.com — 2026-02-28" in output

    def test_h2_headings_per_section(self):
        output = format_report(_make_report(fmt="markdown"))
        assert "## Key Accomplishments" in output
        assert "## Tickets & Issues" in output

    def test_section_content_present(self):
        output = format_report(_make_report(fmt="markdown"))
        assert "Merged PR #42" in output
        assert "JIRA-100 resolved" in output

    def test_skipped_sources_after_divider(self):
        skipped = [SkippedSource(source="gdrive", reason="credentials_missing", attempts=0)]
        output = format_report(_make_report(fmt="markdown", skipped=skipped))
        assert "---" in output
        assert "⚠ Skipped: gdrive (credentials_missing)" in output

    def test_no_divider_without_skipped_sources(self):
        output = format_report(_make_report(fmt="markdown", skipped=[]))
        # The "---" divider only appears when there are skipped sources
        assert "---" not in output

    def test_multiple_skipped_sources_all_rendered(self):
        skipped = [
            SkippedSource(source="jira", reason="credentials_missing", attempts=1),
            SkippedSource(source="slack", reason="not_configured", attempts=0),
        ]
        output = format_report(_make_report(fmt="markdown", skipped=skipped))
        assert "⚠ Skipped: jira (credentials_missing)" in output
        assert "⚠ Skipped: slack (not_configured)" in output

    def test_headings_not_uppercased(self):
        """Markdown headings preserve original case (unlike text format)."""
        output = format_report(_make_report(fmt="markdown"))
        assert "## Key Accomplishments" in output
        assert "KEY ACCOMPLISHMENTS" not in output

    def test_empty_sections_renders_title_only(self):
        output = format_report(_make_report(fmt="markdown", sections=[]))
        assert "# Status Report" in output

    def test_period_label_none_uses_date(self):
        """When period.label is None, the date is used in the title."""
        period = ReportPeriod(
            label=None,
            start=datetime(2026, 1, 15, 0, 0, 0, tzinfo=UTC),
            end=datetime(2026, 1, 15, 23, 59, 59, tzinfo=UTC),
        )
        output = format_report(_make_report(fmt="markdown", period=period))
        assert "2026-01-15" in output


# ── JSON format ───────────────────────────────────────────────────────────────


class TestJsonFormat:
    def _parse(self, fmt: str = "json", **kwargs) -> dict:
        output = format_report(_make_report(fmt=fmt, **kwargs))
        return json.loads(output)

    def test_output_is_valid_json(self):
        output = format_report(_make_report(fmt="json"))
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_top_level_keys_match_contract(self):
        parsed = self._parse()
        assert "user" in parsed
        assert "period" in parsed
        assert "generated_at" in parsed
        assert "sections" in parsed
        assert "skipped_sources" in parsed

    def test_user_field(self):
        parsed = self._parse()
        assert parsed["user"] == "alice@example.com"

    def test_period_object_structure(self):
        parsed = self._parse()
        period = parsed["period"]
        assert "label" in period
        assert "start" in period
        assert "end" in period

    def test_period_label_from_report_period(self):
        parsed = self._parse()
        assert parsed["period"]["label"] == "today"

    def test_period_start_and_end_are_iso8601(self):
        parsed = self._parse()
        # Should parse without error
        datetime.fromisoformat(parsed["period"]["start"].replace("Z", "+00:00"))
        datetime.fromisoformat(parsed["period"]["end"].replace("Z", "+00:00"))

    def test_generated_at_is_iso8601(self):
        parsed = self._parse()
        datetime.fromisoformat(parsed["generated_at"].replace("Z", "+00:00"))

    def test_sections_is_list(self):
        parsed = self._parse()
        assert isinstance(parsed["sections"], list)

    def test_section_items_have_heading_and_content(self):
        parsed = self._parse()
        for section in parsed["sections"]:
            assert "heading" in section
            assert "content" in section

    def test_section_content_matches_input(self):
        parsed = self._parse()
        headings = {s["heading"] for s in parsed["sections"]}
        assert "Key Accomplishments" in headings
        assert "Tickets & Issues" in headings

    def test_skipped_sources_is_list(self):
        parsed = self._parse()
        assert isinstance(parsed["skipped_sources"], list)

    def test_skipped_sources_empty_when_none(self):
        parsed = self._parse(skipped=[])
        assert parsed["skipped_sources"] == []

    def test_skipped_source_item_structure(self):
        skipped = [SkippedSource(source="gdrive", reason="credentials_missing", attempts=1)]
        parsed = self._parse(skipped=skipped)
        assert len(parsed["skipped_sources"]) == 1
        entry = parsed["skipped_sources"][0]
        assert entry["source"] == "gdrive"
        assert entry["reason"] == "credentials_missing"
        assert entry["attempts"] == 1

    def test_multiple_skipped_sources(self):
        skipped = [
            SkippedSource(source="jira", reason="credentials_missing", attempts=1),
            SkippedSource(source="slack", reason="transient_error_exhausted", attempts=3),
        ]
        parsed = self._parse(skipped=skipped)
        assert len(parsed["skipped_sources"]) == 2
        sources = {e["source"] for e in parsed["skipped_sources"]}
        assert sources == {"jira", "slack"}

    def test_no_extra_top_level_keys(self):
        """JSON output must not contain unexpected fields beyond the contract schema."""
        parsed = self._parse()
        allowed = {"user", "period", "generated_at", "sections", "skipped_sources"}
        assert set(parsed.keys()) == allowed

    def test_period_label_none_uses_date_string(self):
        """When period.label is None, period.label in JSON uses the date."""
        period = ReportPeriod(
            label=None,
            start=datetime(2026, 1, 15, 0, 0, 0, tzinfo=UTC),
            end=datetime(2026, 1, 15, 23, 59, 59, tzinfo=UTC),
        )
        parsed = self._parse(period=period)
        # label should be a non-empty string (the date)
        assert parsed["period"]["label"]
        assert "2026-01-15" in parsed["period"]["label"]

    def test_json_is_pretty_printed(self):
        """JSON output should be indented for readability."""
        output = format_report(_make_report(fmt="json"))
        assert "\n" in output  # indented → has newlines


# ── format_report dispatcher ──────────────────────────────────────────────────


class TestFormatReportDispatcher:
    def test_text_format_dispatched(self):
        output = format_report(_make_report(fmt="text"))
        assert "KEY ACCOMPLISHMENTS" in output

    def test_markdown_format_dispatched(self):
        output = format_report(_make_report(fmt="markdown"))
        assert "## Key Accomplishments" in output

    def test_json_format_dispatched(self):
        output = format_report(_make_report(fmt="json"))
        parsed = json.loads(output)
        assert parsed["user"] == "alice@example.com"

    def test_unknown_format_falls_back_to_text(self):
        """Any unrecognised format string falls back to text output."""
        report = _make_report(fmt="xml")  # not a real format
        output = format_report(report)
        # Falls back to _format_text
        assert "KEY ACCOMPLISHMENTS" in output
