"""Agent loop: Claude drives data collection via MCP tools, then synthesizes a report."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any, Literal

import anthropic
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from status_report.config import Config, ReportPeriod
from status_report.mcp.executor import ToolExecutor
from status_report.mcp.registry import ToolRegistry
from status_report.report import Report, ReportSection, SkippedSource, format_report
from status_report.run_history import RunHistoryStore
from status_report.run_log import RunLogger, RunTrace, SkippedSourceEntry

logger = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """You are an autonomous status report agent. You have access to MCP tools connected to
workplace systems (GitHub, Jira, Slack, Google Calendar, Google Drive, Gmail). Your job
is to investigate and report the user's OWN contributions — work they personally authored,
created, or actively participated in during the requested period.

## What to Report (contributions only)

Focus EXCLUSIVELY on things the user did themselves:

- **GitHub**: PRs they OPENED (`author:USER`), commits they PUSHED (`committer:USER`),
  issues they FILED (`author:USER`), code review comments they WROTE (`commenter:USER`),
  and issue comments they POSTED.
  **DO NOT** report PRs where they are only a requested reviewer, assignee, or mention.
  Review queues (review-requested:USER, involves:USER) are NOT their contributions.

- **Jira**: Tickets they CREATED, tickets they moved to a new status, comments they added.

- **Slack**: Messages they SENT in channels or threads.

- **Google Calendar**: Meetings they ATTENDED or ORGANIZED.

- **Google Drive / Docs**: Documents they CREATED or EDITED.

- **Gmail**: Emails they SENT or REPLIED to (subject and action type only — no body content).

## Your Process

1. **Identify the GitHub user first**: If GitHub tools are available, call `get_me`
   as your very first tool call. This returns the authenticated GitHub login (e.g.
   `rareddy`) — use it for every subsequent filter and search. Do NOT guess the
   username from the email address.

2. **Discover personal repos**: Call `search_repositories` with `user:LOGIN` to find
   the user's personal repositories. Then call `list_commits`, `list_pull_requests`,
   and `list_issues` on each repo scoped to the period.
   **Check personal repos before any organisation repos.**

3. **Search authored activity broadly**: After personal repos, search with
   `author:LOGIN`, `committer:LOGIN`, `commenter:LOGIN` filters across all accessible
   repos. Do NOT use `involves:LOGIN` or `review-requested:LOGIN`.

4. **Investigate**: For each authored PR, commit, or issue found — drill deeper. Read
   the PR diff and description (`get_pull_request_diff`, `get_pull_request`), the
   commit message, the issue body and comments. Understand WHAT changed and WHY.

5. **Report**: Write rich, detailed descriptions of each contribution. Include: what was
   changed, why it was important, the outcome (merged/open/closed), and key context.

## Report Sections (include only sections with data)

1. **Key Accomplishments** — Most impactful work completed in the period
2. **Code Contributions** — PRs opened/merged by the user, commits pushed, with diffs and context
3. **Issues Filed** — New bugs reported or features proposed by the user
4. **Discussion & Reviews** — Substantive comments or reviews the user wrote on others' PRs/issues
5. **Meetings & Collaboration** — Meetings the user attended or organized
6. **Documents** — Docs the user created or significantly edited
7. **Messages & Threads** — Key Slack messages or email threads the user drove
8. **Suggested Follow-ups** — Open PRs awaiting merge, pending decisions, upcoming deadlines

## Rules

- Write in first person ("I opened PR #42 to fix...", "I pushed a commit that...")
- Be SPECIFIC and DETAILED — describe what the code change does, what the issue addresses,
  what was decided in the meeting. Not just titles.
- Do NOT list items the user did not author (review requests, assignments, mentions)
- Do NOT invent information not present in tool results
- Do NOT include raw credentials, tokens, or email body content
- Omit any section that has no data
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
        f"If GitHub tools are available, call get_me first to discover the authenticated "
        f"GitHub username, then use that username for all searches. "
        f"Investigate my own contributions in depth and write a detailed status report."
    )


def _parse_claude_response(text: str, period: ReportPeriod, user: str, output_format: str) -> Report:
    """Parse Claude's text response into a Report with sections.

    Text before the first heading is captured as a 'Summary' section rather than
    being silently dropped.
    """
    sections: list[ReportSection] = []
    current_heading: str | None = None
    current_lines: list[str] = []
    pre_heading_lines: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## ") or stripped.startswith("# "):
            if current_heading is None and pre_heading_lines:
                # Flush pre-heading content as a Summary section
                sections.append(
                    ReportSection(
                        heading="Summary",
                        content="\n".join(pre_heading_lines).strip(),
                    )
                )
                pre_heading_lines = []
            elif current_heading and current_lines:
                sections.append(
                    ReportSection(
                        heading=current_heading,
                        content="\n".join(current_lines).strip(),
                    )
                )
            current_heading = stripped.lstrip("#").strip()
            current_lines = []
        elif stripped:
            if current_heading is None:
                pre_heading_lines.append(line)
            else:
                current_lines.append(line)

    # Flush remaining content
    if current_heading is None and pre_heading_lines:
        sections.append(
            ReportSection(
                heading="Summary",
                content="\n".join(pre_heading_lines).strip(),
            )
        )
    elif current_heading and current_lines:
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


# Tool results are truncated to prevent context overflow (GitHub code search can be huge).
# ~8 000 chars ≈ 2 000 tokens; generous enough for useful data.
_MAX_TOOL_RESULT_CHARS = 8_000

# Total message-history budget before we start dropping oldest tool-result pairs.
# 500 000 chars ≈ 125 000 tokens — well inside the 200 000-token API limit.
_MAX_MESSAGES_CHARS = 500_000


def _truncate_result(text: str) -> str:
    """Cap a single tool result, appending a truncation notice if needed."""
    if len(text) <= _MAX_TOOL_RESULT_CHARS:
        return text
    dropped = len(text) - _MAX_TOOL_RESULT_CHARS
    return text[:_MAX_TOOL_RESULT_CHARS] + f"\n\n[...truncated — {dropped:,} chars omitted to stay within context limits...]"


def _estimate_chars(messages: list[dict[str, Any]]) -> int:
    """Rough character count of the entire message list."""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    total += len(str(item.get("content", "") or item.get("text", "")))
                elif hasattr(item, "text"):
                    total += len(item.text)
    return total


def _prune_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop oldest tool-use / tool-result pairs to stay under the char budget.

    Message structure:
        messages[0]  — initial user request (always kept)
        messages[1]  — assistant turn N (tool_use blocks)   ┐ oldest pair
        messages[2]  — user turn N (tool_result blocks)     ┘
        ...
    Pairs are dropped two at a time from the front until under budget.
    """
    while len(messages) > 3 and _estimate_chars(messages) > _MAX_MESSAGES_CHARS:
        messages = [messages[0]] + messages[3:]
        logger.info("messages_pruned", remaining_messages=len(messages))
    return messages


@retry(
    retry=retry_if_exception_type(
        (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError)
    ),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(3),
    reraise=True,
)
async def _call_claude(client: anthropic.AsyncAnthropicVertex, **kwargs: Any) -> Any:
    """Call Claude API with automatic retry on transient errors."""
    return await client.messages.create(**kwargs)


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
    client = anthropic.AsyncAnthropicVertex(
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

        # Drop oldest tool-result pairs if history is growing too large.
        messages = _prune_messages(messages)

        logger.info("agent_loop_turn", turn=agent_turns, message_count=len(messages))

        response = await _call_claude(
            client,
            model=config.claude_model,
            max_tokens=config.max_response_tokens,
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
            report_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    report_text += block.text

            report = _parse_claude_response(report_text, period, user, output_format)
            report.skipped_sources = skipped
            break

        # ── Handle tool_use: dispatch tool calls in parallel ───────────────
        if response.stop_reason == "tool_use":
            # Add Claude's response (with tool_use blocks) to messages
            messages.append({"role": "assistant", "content": response.content})

            tool_blocks = [b for b in response.content if b.type == "tool_use"]

            async def _execute_one(block: Any) -> dict[str, Any]:
                logger.info("tool_call", tool=block.name, turn=agent_turns)
                try:
                    result_text = await executor.execute(block.name, block.input)
                except ValueError as exc:
                    result_text = str(exc)
                return {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": _truncate_result(result_text),
                }

            tool_results = list(await asyncio.gather(*[_execute_one(b) for b in tool_blocks]))
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
        # Turn limit reached — ask Claude for best report with data so far
        logger.warning(
            "agent_loop_turn_limit_reached",
            max_turns=max_turns,
            tool_calls=executor.call_count,
        )

        messages.append({
            "role": "user",
            "content": (
                "You have reached the investigation limit. Please write the best "
                "status report you can with the information you have gathered so far."
            ),
        })
        response = await _call_claude(
            client,
            model=config.claude_model,
            max_tokens=config.max_response_tokens,
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

    has_content = bool(report.sections or report.raw_text.strip())
    if not has_content:
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
