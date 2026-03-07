"""CLI entrypoint for the Status Report Agent.

Usage:
    python -m status_report.main --user alice@example.com --period today
    python -m status_report.main --user alice@example.com --period yesterday --format markdown
    python -m status_report.main --user alice --period 2026-02-24:2026-02-28 --sources github,slack

Exit codes:
    0 — success (all configured sources returned data)
    1 — partial success (report generated; >=1 source skipped)
    2 — complete failure (no data; all sources failed or none configured)
    3 — invalid arguments (bad --period, unknown format, future date, etc.)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime

import structlog

from status_report.config import Config, ReportPeriod, parse_period
from status_report.mcp.config import build_mcp_configs, filter_configs_by_sources
from status_report.mcp.executor import ToolExecutor
from status_report.mcp.manager import MCPManager
from status_report.mcp.registry import ToolRegistry
from status_report.report import SkippedSource, format_report
from status_report.run_history import RunHistoryStore
from status_report.tracing import configure_structlog

logger = structlog.get_logger(__name__)


def _load_dotenv() -> None:
    """Load .env into os.environ so MCP subprocesses and build_mcp_configs see all credentials.

    pydantic-settings loads .env for Config but does not modify os.environ, so
    build_mcp_configs(dict(os.environ)) would miss any vars defined only in .env.
    Only sets keys not already present — existing shell exports take priority.
    """
    from pathlib import Path

    env_file = Path(".env")
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_VALID_SOURCES = ("jira", "slack", "github", "google", "browser")
_VALID_FORMATS = ("text", "markdown", "json")


def _configure_logging(level: str = "INFO") -> None:
    configure_structlog(log_level=level)


async def _run_with_mcp(
    config: Config,
    user: str,
    period: ReportPeriod,
    output_format: str,
    requested_sources: list[str] | None,
) -> int:
    """Start MCP servers, run agent loop, return exit code."""
    from status_report.agent import run_agent

    # Build MCP server configs from environment
    env = dict(os.environ)
    all_configs = build_mcp_configs(env)

    # Filter to requested sources
    configs, not_available = filter_configs_by_sources(all_configs, requested_sources)

    pre_skipped = [
        SkippedSource(source=name, reason="not_configured", attempts=0)
        for name in not_available
    ]

    if not configs:
        print(
            "ERROR: No MCP servers can be configured. "
            "Set at least one of: GITHUB_TOKEN, JIRA_API_TOKEN, SLACK_MCP_XOXC_TOKEN, GOOGLE_CLIENT_ID.",
            file=sys.stderr,
        )
        return 2

    # Start MCP servers
    manager = MCPManager(configs)
    try:
        handles = await manager.start_all()

        if not handles:
            print(
                "ERROR: All MCP servers failed to start. Check credentials and connectivity.",
                file=sys.stderr,
            )
            return 2

        mcp_servers_started = [h.config.name for h in handles]
        logger.info(
            "mcp_servers_ready",
            servers=mcp_servers_started,
            total=len(handles),
        )

        # Build tool registry and executor
        registry = ToolRegistry()
        registry.register_all(handles)
        executor = ToolExecutor(registry)

        tools = registry.get_anthropic_tools()
        if not tools:
            print(
                "ERROR: No read-only tools available from MCP servers.",
                file=sys.stderr,
            )
            return 2

        logger.info(
            "Starting report generation",
            user=user,
            period=period.label,
            tool_count=len(tools),
            format=output_format,
        )

        # Run agent loop
        report = await run_agent(
            config=config,
            user=user,
            period=period,
            registry=registry,
            executor=executor,
            output_format=output_format,
            pre_skipped=pre_skipped,
            mcp_servers_started=mcp_servers_started,
        )

        # Write report to stdout
        print(format_report(report))

        # Determine exit code
        if not report.sections and not report.raw_text:
            return 2
        elif report.skipped_sources:
            return 1
        else:
            return 0

    finally:
        await manager.shutdown()


def main() -> None:
    """CLI entry point — parses args, starts MCP servers, runs agent."""
    _load_dotenv()
    _configure_logging()

    parser = argparse.ArgumentParser(
        prog="status-report",
        description="Generate a structured status report from your workplace tools.",
    )
    parser.add_argument(
        "--user",
        required=True,
        help="Target user identifier (email or username)",
    )
    parser.add_argument(
        "--period",
        required=False,
        default=None,
        help=(
            "Time range: today | yesterday | last-24h | last-7d | YYYY-MM-DD | YYYY-MM-DD:YYYY-MM-DD. "
            "If omitted, auto-computed from run history."
        ),
    )
    parser.add_argument(
        "--sources",
        default=None,
        help=f"Comma-separated sources to include. Default: all configured. "
             f"Options: {', '.join(_VALID_SOURCES)}",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        default="text",
        choices=_VALID_FORMATS,
        help="Output format (default: text)",
    )

    args = parser.parse_args()

    # ── Validate --user ────────────────────────────────────────────────────
    if not args.user.strip():
        print("ERROR: --user must be a non-empty string.", file=sys.stderr)
        sys.exit(3)

    # ── Resolve --period ───────────────────────────────────────────────────
    if args.period is not None:
        try:
            period = parse_period(args.period)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(3)
    else:
        now = datetime.now(UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        result = RunHistoryStore().get_last_successful_run(args.user)
        if result:
            last_ts, _ = result
            period = ReportPeriod(
                label=f"since last run at {last_ts.strftime('%Y-%m-%dT%H:%M:%SZ')}",
                start=last_ts,
                end=now,
            )
            logger.info("Period auto-computed from run history", last_run=str(last_ts))
        else:
            period = ReportPeriod(label="today (first run)", start=today_start, end=now)
            logger.info("No run history found — defaulting to today (first run)")

    # ── Load config ────────────────────────────────────────────────────────
    try:
        config = Config()
    except Exception as exc:
        print(f"ERROR: Configuration error: {exc}", file=sys.stderr)
        sys.exit(3)

    # ── Parse --sources ────────────────────────────────────────────────────
    requested_sources: list[str] | None = None
    if args.sources:
        requested_sources = [s.strip().lower() for s in args.sources.split(",") if s.strip()]
        if not requested_sources:
            print(
                "ERROR: No valid sources specified. "
                f"Valid sources: {', '.join(_VALID_SOURCES)}.",
                file=sys.stderr,
            )
            sys.exit(3)

    # ── Run agent with MCP servers ─────────────────────────────────────────
    sources_label = ", ".join(requested_sources) if requested_sources else "all configured"
    print(
        f"Generating report for {args.user} | period: {period.label or str(period.start.date())} | sources: {sources_label}",
        file=sys.stderr,
    )

    try:
        exit_code = asyncio.run(
            _run_with_mcp(
                config=config,
                user=args.user,
                period=period,
                output_format=args.output_format,
                requested_sources=requested_sources,
            )
        )
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        print(f"ERROR: Agent failed: {exc}", file=sys.stderr)
        logger.exception("Agent run failed", exc=exc)
        sys.exit(2)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
