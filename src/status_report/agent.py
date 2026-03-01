"""Agent orchestrator: runs skills concurrently, calls Claude once for synthesis."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from typing import Literal

import anthropic
import structlog

from status_report.config import Config, ReportPeriod
from status_report.report import Report, ReportSection, SkippedSource, format_report
from status_report.run_history import RunHistoryStore
from status_report.run_log import RunLogger, RunTrace, SkippedSourceEntry
from status_report.skills.base import ActivityItem, ActivitySkill, SkillFetchResult, fetch_with_retry

logger = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """You are a professional status report writer. You will receive a structured list
of workplace activity items collected from various tools (Jira, GitHub, Slack, Google Calendar,
Google Drive, Gmail). Synthesise them into a clear, professional status report.

Organise the report into these sections (include a section ONLY if there is relevant data):
1. Key Accomplishments
2. Tickets & Issues
3. Code Contributions
4. Meetings & Collaboration
5. Documents
6. Email Activity
7. Suggested Follow-ups

Rules:
- Write in first person (e.g. "I merged PR #42...")
- Be concise and professional — suitable for a team standup or weekly update
- Do NOT invent information not present in the activity items
- Do NOT include raw credentials, tokens, or personal email body content
- Each section should be a brief bulleted list or short paragraph
- If a section has no data, omit it entirely"""


def _serialise_items(items: list[ActivityItem]) -> str:
    """Convert ActivityItems to a compact JSON string for the Claude prompt."""
    return json.dumps(
        [
            {
                "source": item.source,
                "action_type": item.action_type,
                "title": item.title,
                "timestamp": item.timestamp.isoformat(),
                "url": item.url,
                "metadata": item.metadata,
            }
            for item in items
        ],
        indent=2,
    )


def _parse_claude_response(text: str, period: ReportPeriod, user: str, output_format: str) -> Report:
    """Parse Claude's text response into a Report with sections."""
    sections: list[ReportSection] = []
    current_heading: str | None = None
    current_lines: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## ") or stripped.startswith("# "):
            # Save previous section
            if current_heading and current_lines:
                sections.append(
                    ReportSection(
                        heading=current_heading,
                        content="\n".join(current_lines).strip(),
                    )
                )
            current_heading = stripped.lstrip("#").strip()
            current_lines = []
        elif stripped:
            current_lines.append(line)

    # Save last section
    if current_heading and current_lines:
        sections.append(
            ReportSection(
                heading=current_heading,
                content="\n".join(current_lines).strip(),
            )
        )

    return Report(
        period=period,
        user=user,
        format=output_format,
        sections=sections,
        skipped_sources=[],
        generated_at=datetime.now(UTC),
        raw_text=text,
    )


async def run_agent(
    config: Config,
    user: str,
    period: ReportPeriod,
    enabled_skills: list[ActivitySkill],
    output_format: Literal["text", "markdown", "json"],
    pre_skipped: list[SkippedSource] | None = None,
) -> Report:
    """Orchestrate skill fetching and Claude synthesis for one agent run.

    Args:
        config: Application config.
        user: Target user identifier.
        period: Report time window.
        enabled_skills: Pre-filtered list of ready skills.
        output_format: Desired output format.
        pre_skipped: Sources already known to be unavailable (not configured).

    Returns:
        Report with synthesised content and skipped_sources populated.
    """
    run_start = time.monotonic()

    skill_results: dict[str, list[ActivityItem]] = {}
    skipped: list[SkippedSource] = list(pre_skipped) if pre_skipped else []
    retries: dict[str, int] = {}

    # ── Fetch from all skills concurrently ────────────────────────────────────
    async def _run_skill(skill: ActivitySkill) -> tuple[str, SkillFetchResult]:
        name = skill.__class__.__name__.lower().replace("skill", "")
        logger.info("[%s] Fetching activity for %s (%s → %s)", name, user, period.start.date(), period.end.date())
        result = await fetch_with_retry(skill, user, period.start, period.end)
        if result.failure_reason is None:
            logger.info("[%s] Retrieved %d item(s)", name, len(result.items))
        else:
            logger.warning("[%s] Failed: %s (retries: %d)", name, result.failure_reason, result.retry_count)
        return name, result

    skill_names = [s.__class__.__name__.lower().replace("skill", "") for s in enabled_skills]
    results = await asyncio.gather(*[_run_skill(skill) for skill in enabled_skills])

    all_items: list[ActivityItem] = []
    counts: dict[str, int] = {}

    for name, result in results:
        counts[name] = len(result.items)
        if result.failure_reason is not None:
            # Actual failure (bad credentials, transient retries exhausted, etc.)
            skipped.append(
                SkippedSource(
                    source=name,
                    reason=result.failure_reason,
                    attempts=result.retry_count + 1,
                )
            )
            retries[name] = result.retry_count
        else:
            # Success — even if items=[] (no activity today, not a failure)
            all_items.extend(result.items)
            skill_results[name] = result.items

    # ── Synthesise with Claude via Vertex AI (exactly once) ───────────────────
    if not all_items:
        logger.warning("No activity items retrieved from any skill.")
        report = Report(
            period=period,
            user=user,
            format=output_format,
            sections=[],
            skipped_sources=skipped,
            generated_at=datetime.now(UTC),
            raw_text="",
        )
    else:
        period_label = period.label or f"{period.start.date()}:{period.end.date()}"
        user_message = (
            f"Generate a status report for user '{user}' covering {period_label}.\n\n"
            f"Activity data ({len(all_items)} items):\n{_serialise_items(all_items)}"
        )

        logger.info("Calling Claude for synthesis (%d total items)...", len(all_items))
        client = anthropic.AnthropicVertex(
            project_id=config.vertex_project_id,
            region=config.vertex_region,
        )
        response = client.messages.create(
            model=config.claude_model,
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        report_text = response.content[0].text
        report = _parse_claude_response(report_text, period, user, output_format)
        report.skipped_sources = skipped

    # ── Write RunTrace audit log ───────────────────────────────────────────────
    duration = time.monotonic() - run_start

    if skipped and not all_items:
        outcome = "failed"
    elif skipped:
        outcome = "partial"
    else:
        outcome = "success"

    run_trace = RunTrace(
        timestamp=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        user=user,
        period=period.label or str(period.start.date()),
        format=output_format,
        sources_attempted=skill_names,
        counts=counts,
        outcome=outcome,
        skipped=[
            SkippedSourceEntry(source=s.source, reason=s.reason, attempts=s.attempts)
            for s in skipped
        ],
        retries=retries,
        duration_seconds=round(duration, 3),
    )

    try:
        RunLogger().log_run(run_trace)
    except Exception as exc:
        logger.warning("Failed to write audit log entry: %s", exc)

    if outcome in ("success", "partial"):
        try:
            RunHistoryStore().record_run(
                user=user,
                completed_at=datetime.now(UTC),
                outcome=outcome,
                period_label=period.label or str(period.start.date()),
            )
        except Exception as exc:
            logger.warning("Failed to write run history entry", error=str(exc))

    return report
