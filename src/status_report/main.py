"""CLI entrypoint for the Status Report Agent.

Usage:
    python -m status_report.main --user alice@example.com --period today
    python -m status_report.main --user alice@example.com --period yesterday --format markdown
    python -m status_report.main --user alice --period 2026-02-24:2026-02-28 --sources github,slack

Exit codes:
    0 — success (all configured sources returned data)
    1 — partial success (report generated; ≥1 source skipped)
    2 — complete failure (no data; all sources failed or none configured)
    3 — invalid arguments (bad --period, unknown format, future date, etc.)
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import structlog

from status_report.config import Config, parse_period
from status_report.report import SkippedSource, format_report
from status_report.skills import get_enabled_skills
from status_report.tracing import TracingClient, configure_structlog

logger = structlog.get_logger(__name__)

_VALID_SOURCES = ("jira", "slack", "github", "calendar", "gdrive", "gmail")
_VALID_FORMATS = ("text", "markdown", "json")


def _configure_logging(level: str = "WARNING") -> None:
    configure_structlog(log_level=level)


def _parse_sources(sources_str: str) -> list[str]:
    """Parse and validate --sources argument; warn about unknown names."""
    requested = [s.strip().lower() for s in sources_str.split(",") if s.strip()]
    valid: list[str] = []
    for name in requested:
        if name not in _VALID_SOURCES and name not in __import__(
            "status_report.skills.base", fromlist=["ActivitySkill"]
        ).ActivitySkill._registry:
            print(
                f'WARNING: Unknown source "{name}" — skipping. '
                f"Valid sources: {', '.join(_VALID_SOURCES)}.",
                file=sys.stderr,
            )
        else:
            valid.append(name)
    return valid


def main() -> None:
    """CLI entry point — parses args, runs agent, writes report to stdout."""
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
        required=True,
        help="Time range: today | yesterday | last-24h | YYYY-MM-DD | YYYY-MM-DD:YYYY-MM-DD",
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

    # ── Validate --user ────────────────────────────────────────────────────────
    if not args.user.strip():
        print("ERROR: --user must be a non-empty string.", file=sys.stderr)
        sys.exit(3)

    # ── Validate --period ──────────────────────────────────────────────────────
    try:
        period = parse_period(args.period)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(3)

    # ── Load config ────────────────────────────────────────────────────────────
    try:
        config = Config()
    except Exception as exc:
        print(f"ERROR: Configuration error: {exc}", file=sys.stderr)
        sys.exit(3)

    # ── Resolve --sources ──────────────────────────────────────────────────────
    requested_sources: list[str] | None = None
    if args.sources:
        requested_sources = _parse_sources(args.sources)
        if not requested_sources:
            print(
                "ERROR: No valid sources specified after filtering. "
                f"Valid sources: {', '.join(_VALID_SOURCES)}.",
                file=sys.stderr,
            )
            sys.exit(3)

    # ── Discover and filter skills ─────────────────────────────────────────────
    enabled_skills, not_configured = get_enabled_skills(config, requested_sources)

    if not enabled_skills:
        print(
            "ERROR: No skills are configured. "
            "Set at least one of: JIRA_API_TOKEN, SLACK_BOT_TOKEN, GITHUB_TOKEN, GOOGLE_CLIENT_ID.",
            file=sys.stderr,
        )
        sys.exit(2)

    logger.info(
        "Starting report generation",
        user=args.user,
        period=args.period,
        skills=[s.__class__.__name__ for s in enabled_skills],
        format=args.output_format,
    )

    # ── Run agent ──────────────────────────────────────────────────────────────
    from status_report.agent import run_agent

    tracing_client = TracingClient(config)

    # Convert unconfigured-but-requested skill names to pre-populated SkippedSource entries
    pre_skipped = [
        SkippedSource(source=name, reason="not_configured", attempts=0)
        for name in not_configured
    ]

    try:
        report = asyncio.run(
            run_agent(
                config=config,
                user=args.user,
                period=period,
                enabled_skills=enabled_skills,
                output_format=args.output_format,
                tracing_client=tracing_client,
                pre_skipped=pre_skipped,
            )
        )
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        print(f"ERROR: Agent failed: {exc}", file=sys.stderr)
        logger.exception("Agent run failed", exc=exc)
        sys.exit(2)

    # ── Write report to stdout ─────────────────────────────────────────────────
    print(format_report(report))

    # ── Determine exit code ────────────────────────────────────────────────────
    if not report.sections and not report.raw_text:
        sys.exit(2)
    elif report.skipped_sources:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
