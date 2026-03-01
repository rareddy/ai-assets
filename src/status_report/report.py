"""Report data model and formatters (text, markdown, JSON)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

from status_report.config import ReportPeriod


@dataclass
class ReportSection:
    """One content section of the generated report."""

    heading: str
    content: str


@dataclass
class SkippedSource:
    """A data source that was excluded from this run."""

    source: str
    reason: str
    attempts: int = 0


@dataclass
class Report:
    """The final synthesised report for one agent run."""

    period: ReportPeriod
    user: str
    format: Literal["text", "markdown", "json"]
    sections: list[ReportSection]
    skipped_sources: list[SkippedSource]
    generated_at: datetime
    raw_text: str = ""


def format_report(report: Report) -> str:
    """Render a Report to its requested output format (text, markdown, or json)."""
    if report.format == "markdown":
        return _format_markdown(report)
    elif report.format == "json":
        return _format_json(report)
    else:
        return _format_text(report)


# ── Text formatter ────────────────────────────────────────────────────────────


def _format_text(report: Report) -> str:
    date_str = report.period.start.strftime("%Y-%m-%d")
    lines: list[str] = [
        f"Status Report — {report.user} — {date_str}",
        "=" * 60,
        "",
    ]
    if report.period.label:
        lines.insert(2, f"Period : {report.period.label}")
        lines.insert(3, "")

    for section in report.sections:
        lines.append(section.heading.upper())
        lines.append("-" * len(section.heading))
        lines.append(section.content)
        lines.append("")

    if report.skipped_sources:
        lines.append("─" * 40)
        for skipped in report.skipped_sources:
            lines.append(f"⚠ Skipped: {skipped.source} ({skipped.reason})")

    return "\n".join(lines)


# ── Markdown formatter ────────────────────────────────────────────────────────


def _format_markdown(report: Report) -> str:
    date_str = report.period.start.strftime("%Y-%m-%d")
    lines: list[str] = [
        f"# Status Report — {report.user} — {date_str}",
        "",
    ]
    if report.period.label:
        lines.insert(2, f"**Period**: {report.period.label}")
        lines.insert(3, "")

    for section in report.sections:
        lines.append(f"## {section.heading}")
        lines.append("")
        lines.append(section.content)
        lines.append("")

    if report.skipped_sources:
        lines.append("---")
        lines.append("")
        for skipped in report.skipped_sources:
            lines.append(f"⚠ Skipped: {skipped.source} ({skipped.reason})")
        lines.append("")

    return "\n".join(lines)


# ── JSON formatter ─────────────────────────────────────────────────────────────


def _format_json(report: Report) -> str:
    """Serialize Report to JSON matching the cli-contract.md schema."""
    period_label = report.period.label or str(report.period.start.date())
    payload = {
        "user": report.user,
        "period": {
            "label": period_label,
            "start": report.period.start.isoformat(),
            "end": report.period.end.isoformat(),
        },
        "generated_at": report.generated_at.isoformat(),
        "sections": [
            {"heading": s.heading, "content": s.content}
            for s in report.sections
        ],
        "skipped_sources": [
            {"source": s.source, "reason": s.reason, "attempts": s.attempts}
            for s in report.skipped_sources
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
