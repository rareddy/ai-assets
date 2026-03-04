"""Structured logging configuration for the status-report agent."""

from __future__ import annotations

import logging
import sys

import structlog


def configure_structlog(log_level: str = "WARNING") -> None:
    """Configure structlog for the application.

    Uses ConsoleRenderer when stderr is a TTY (local dev),
    JSONRenderer otherwise (container / log aggregator).
    """
    renderer: object = (
        structlog.dev.ConsoleRenderer()
        if sys.stderr.isatty()
        else structlog.processors.JSONRenderer()
    )
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.WARNING),
        stream=sys.stderr,
    )
