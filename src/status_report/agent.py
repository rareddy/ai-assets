"""Agent loop: Claude drives data collection via MCP tools, then synthesizes a report."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any, Literal

import anthropic
import structlog

from status_report.config import Config, ReportPeriod
from status_report.mcp.executor import ToolExecutor
from status_report.mcp.registry import ToolRegistry
from status_report.report import Report, ReportSection, SkippedSource, format_report
from status_report.run_history import RunHistoryStore
from status_report.run_log import RunLogger, RunTrace, SkippedSourceEntry

logger = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """You are an autonomous status report agent. You have access to MCP tools connected to
workplace systems (GitHub, Jira, Slack, Google Calendar, Google Drive, Gmail). Your job
is to investigate the user's recent activity and write a detailed, professional status
report.

## Your Process

1. **Discover**: Search across all available tools for the user's activity in the
   requested time period. Start broad — search for recent PRs, tickets updated,
   messages sent, meetings attended, documents modified, and emails sent/replied.

2. **Investigate**: For the most significant items (merged PRs, completed tickets,
   important meetings), drill deeper. Read PR diffs, ticket descriptions and comments,
   thread context. Understand WHAT was actually done, not just that something happened.

3. **Report**: Write a rich, detailed report. Don't just list titles — describe the
   actual work, the context, and the significance.

## Report Sections (include only sections with data)

1. **Key Accomplishments** — Most impactful work completed
2. **Tickets & Issues** — Status changes, progress, blockers
3. **Code Contributions** — PRs, code reviews, commits with context
4. **Meetings & Collaboration** — Meetings attended, key discussions
5. **Documents** — Docs created, reviewed, or significantly modified
6. **Email Activity** — Important threads, responses (subject and action type only — no body content)
7. **Suggested Follow-ups** — Open items, pending reviews, upcoming deadlines

## Rules

- Write in first person ("I merged PR #42...")
- Be concise and professional — suitable for a team standup or weekly update
- Do NOT invent information not present in tool results
- Do NOT include raw credentials, tokens, or email body content
- Each section should be bulleted or short paragraphs
- If a section has no data, omit it entirely
- When you have enough information to write a comprehensive report, stop calling tools
  and write the report directly
"""


def _build_user_message(user: str, period: ReportPeriod, available_sources: list[str]) -> str:
    """Build the initial user message for the agent loop."""
    period_label = period.label or f"{period.start.date()} to {period.end.date()}"
    sources_str = ", ".join(available_sources) if available_sources else "all configured"

    return (
        f"Generate a status report for user '{user}' covering the period: {period_label}.\n\n"
        f"Available data sources: {sources_str}\n"
        f"Time range: {period.start.isoformat()} to {period.end.isoformat()}\n\n"
        f"Search for my activity across all available tools, investigate the most "
        f"significant items in depth, and write a detailed status report."
    )


def _parse_claude_response(text: str, period: ReportPeriod, user: str, output_format: str) -> Report:
    """Parse Claude's text response into a Report with sections."""
    sections: list[ReportSection] = []
    current_heading: str | None = None
    current_lines: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## ") or stripped.startswith("# "):
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
    registry: ToolRegistry,
    executor: ToolExecutor,
    output_format: Literal["text", "markdown", "json"],
    pre_skipped: list[SkippedSource] | None = None,
    mcp_servers_started: list[str] | None = None,
) -> Report:
    """Run the Claude agent loop with MCP tools.

    Claude decides what to investigate, calls tools, receives results, and
    iterates until it has enough context to write the report.

    Args:
        config: Application config.
        user: Target user identifier.
        period: Report time window.
        registry: Tool registry with allowlisted tools.
        executor: Tool executor for dispatching tool calls.
        output_format: Desired output format.
        pre_skipped: Sources already known to be unavailable.
        mcp_servers_started: Names of MCP servers that started successfully.

    Returns:
        Report with synthesized content and skipped_sources populated.
    """
    run_start = time.monotonic()
    skipped: list[SkippedSource] = list(pre_skipped) if pre_skipped else []
    available_sources = registry.get_source_labels()

    tools = registry.get_anthropic_tools()
    if not tools:
        logger.warning("No MCP tools available — producing empty report.")
        return Report(
            period=period,
            user=user,
            format=output_format,
            sections=[],
            skipped_sources=skipped,
            generated_at=datetime.now(UTC),
            raw_text="",
        )

    # ── Build initial messages ─────────────────────────────────────────────
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": _build_user_message(user, period, available_sources)},
    ]

    # ── Agent loop ─────────────────────────────────────────────────────────
    client = anthropic.AnthropicVertex(
        project_id=config.vertex_project_id,
        region=config.vertex_region,
    )

    agent_turns = 0
    total_input_tokens = 0
    total_output_tokens = 0
    max_turns = config.max_agent_turns

    logger.info(
        "agent_loop_starting",
        user=user,
        period=period.label,
        tool_count=len(tools),
        max_turns=max_turns,
    )

    while agent_turns < max_turns:
        agent_turns += 1

        logger.info("agent_loop_turn", turn=agent_turns, message_count=len(messages))

        response = client.messages.create(
            model=config.claude_model,
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            messages=messages,
            tools=tools,
        )

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        # ── Handle end_turn: Claude is done ────────────────────────────────
        if response.stop_reason == "end_turn":
            logger.info(
                "agent_loop_complete",
                turns=agent_turns,
                total_tool_calls=executor.call_count,
            )
            # Extract final text
            report_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    report_text += block.text

            report = _parse_claude_response(report_text, period, user, output_format)
            report.skipped_sources = skipped
            break

        # ── Handle tool_use: dispatch tool calls ───────────────────────────
        if response.stop_reason == "tool_use":
            # Add Claude's response (with tool_use blocks) to messages
            messages.append({"role": "assistant", "content": response.content})

            # Process each tool call
            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if block.type == "tool_use":
                    logger.info(
                        "tool_call",
                        tool=block.name,
                        turn=agent_turns,
                    )
                    try:
                        result_text = await executor.execute(block.name, block.input)
                    except ValueError as exc:
                        result_text = str(exc)

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    })

            messages.append({"role": "user", "content": tool_results})
            continue

        # ── Unexpected stop reason ─────────────────────────────────────────
        logger.warning(
            "agent_loop_unexpected_stop",
            stop_reason=response.stop_reason,
            turn=agent_turns,
        )
        report_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                report_text += block.text

        report = _parse_claude_response(report_text, period, user, output_format)
        report.skipped_sources = skipped
        break

    else:
        # Turn limit reached
        logger.warning(
            "agent_loop_turn_limit_reached",
            max_turns=max_turns,
            tool_calls=executor.call_count,
        )

        # Ask Claude to produce its best report with data collected so far
        messages.append({
            "role": "user",
            "content": (
                "You have reached the investigation limit. Please write the best "
                "status report you can with the information you have gathered so far."
            ),
        })
        response = client.messages.create(
            model=config.claude_model,
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            messages=messages,
        )
        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        report_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                report_text += block.text

        report = _parse_claude_response(report_text, period, user, output_format)
        report.skipped_sources = skipped

    # ── Write RunTrace audit log ───────────────────────────────────────────
    duration = time.monotonic() - run_start

    if skipped and not report.sections:
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
        sources_attempted=available_sources,
        counts={},
        outcome=outcome,
        skipped=[
            SkippedSourceEntry(source=s.source, reason=s.reason, attempts=s.attempts)
            for s in skipped
        ],
        retries={},
        duration_seconds=round(duration, 3),
        agent_turns=agent_turns,
        tool_calls_count=executor.call_count,
        total_tokens=total_input_tokens + total_output_tokens,
        mcp_servers_started=mcp_servers_started or [],
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
