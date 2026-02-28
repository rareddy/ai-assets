"""LangFuse observability setup.

Creates a top-level trace per agent run with child spans for each
skill execution and the Claude synthesis step.

Security: credentials MUST NOT appear in any span data.
"""

from __future__ import annotations

import logging
import sys
from contextlib import contextmanager
from typing import Generator, Optional

import structlog

logger = logging.getLogger(__name__)


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

# LangFuse is optional — if import fails, tracing becomes a no-op
try:
    from langfuse import Langfuse
    from langfuse.decorators import langfuse_context, observe  # noqa: F401

    _LANGFUSE_AVAILABLE = True
except ImportError:
    _LANGFUSE_AVAILABLE = False
    logger.warning("langfuse not installed — tracing disabled")


class _NoopSpan:
    """Null-object span used when LangFuse is unavailable or disabled."""

    def end(self, **kwargs: object) -> None:
        pass

    def update(self, **kwargs: object) -> None:
        pass


class _NoopTrace:
    """Null-object trace used when LangFuse is unavailable or disabled."""

    def span(self, **kwargs: object) -> _NoopSpan:
        return _NoopSpan()

    def generation(self, **kwargs: object) -> _NoopSpan:
        return _NoopSpan()

    def update(self, **kwargs: object) -> None:
        pass

    def flush(self) -> None:
        pass


class TracingClient:
    """Thin wrapper around LangFuse providing trace/span lifecycle management."""

    def __init__(self, config: object) -> None:
        self._client: Optional[object] = None
        if _LANGFUSE_AVAILABLE:
            try:
                self._client = Langfuse(
                    public_key=config.langfuse_public_key,
                    secret_key=config.langfuse_secret_key,
                    host=config.langfuse_host,
                )
            except Exception as exc:
                logger.warning("Failed to initialise LangFuse client: %s", exc)

    def create_trace(self, user: str, period_label: str, output_format: str) -> object:
        """Create a top-level trace for one agent run."""
        if self._client is None:
            return _NoopTrace()
        return self._client.trace(
            name="status-report",
            user_id=user,
            metadata={"period": period_label, "format": output_format},
        )

    @contextmanager
    def skill_span(self, trace: object, skill_name: str) -> Generator[object, None, None]:
        """Context manager for a skill-fetch child span."""
        if isinstance(trace, _NoopTrace):
            yield _NoopSpan()
            return
        span = trace.span(name=f"skill:{skill_name}")
        try:
            yield span
        finally:
            span.end()

    @contextmanager
    def synthesis_span(self, trace: object) -> Generator[object, None, None]:
        """Context manager for the Claude synthesis child span."""
        if isinstance(trace, _NoopTrace):
            yield _NoopSpan()
            return
        span = trace.generation(name="claude:synthesis")
        try:
            yield span
        finally:
            span.end()

    def flush(self, trace: object) -> None:
        """Flush all pending events to LangFuse."""
        try:
            trace.flush()
        except Exception as exc:
            logger.debug("LangFuse flush error (non-fatal): %s", exc)
        if self._client:
            try:
                self._client.flush()
            except Exception as exc:
                logger.debug("LangFuse client flush error (non-fatal): %s", exc)
