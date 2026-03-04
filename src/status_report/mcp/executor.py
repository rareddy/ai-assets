"""Tool executor: routes Claude's tool_use calls to MCP sessions with safety."""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from status_report.mcp.registry import ToolRegistry

logger = structlog.get_logger(__name__)

# Gmail fields that must be scrubbed from tool results (FR-010a)
_GMAIL_BODY_KEYS = {"body", "htmlbody", "textbody", "snippet", "raw", "data", "payload_body"}

# Tool names that return Gmail message content requiring scrubbing
_GMAIL_TOOLS = {"gmail_get_message"}


def _scrub_gmail_body(data: Any) -> Any:
    """Recursively remove email body content from Gmail tool results.

    This enforces FR-010a: email body content MUST NEVER reach Claude.
    Only subject, sender, recipients, timestamp, and action type are permitted.
    """
    if isinstance(data, dict):
        scrubbed = {}
        for key, value in data.items():
            if key.lower() in _GMAIL_BODY_KEYS or key == "payload":
                # Scrub body-like fields entirely
                if key == "payload" and isinstance(value, dict):
                    # Keep payload headers (subject, from, to, date) but remove body
                    scrubbed[key] = _scrub_gmail_payload(value)
                else:
                    scrubbed[key] = "[SCRUBBED — email body content excluded per FR-010a]"
            else:
                scrubbed[key] = _scrub_gmail_body(value)
        return scrubbed
    elif isinstance(data, list):
        return [_scrub_gmail_body(item) for item in data]
    return data


def _scrub_gmail_payload(payload: dict) -> dict:
    """Scrub a Gmail message payload, keeping only headers."""
    result: dict[str, Any] = {}
    if "headers" in payload:
        # Only keep safe headers
        safe_headers = {"subject", "from", "to", "cc", "bcc", "date", "message-id",
                        "in-reply-to", "references"}
        result["headers"] = [
            h for h in payload["headers"]
            if h.get("name", "").lower() in safe_headers
        ]
    if "mimeType" in payload:
        result["mimeType"] = payload["mimeType"]
    # Drop body, parts, and other content fields
    return result


class ToolExecutor:
    """Routes Claude's tool_use calls to the correct MCP session.

    Provides safety validation (allowlist check) and Gmail body scrubbing.
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry
        self._call_count = 0

    @property
    def call_count(self) -> int:
        return self._call_count

    async def execute(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """Execute a tool call by routing to the appropriate MCP session.

        Args:
            tool_name: Name of the tool to call.
            tool_input: Arguments for the tool.

        Returns:
            JSON-serialized tool result string.

        Raises:
            ValueError: If the tool is not in the registry (allowlist violation).
        """
        # Safety check: only allowlisted tools can be called
        entry = self._registry.get_tool(tool_name)
        if entry is None:
            logger.warning(
                "tool_call_rejected",
                tool=tool_name,
                reason="not_in_allowlist",
            )
            raise ValueError(
                f"Tool '{tool_name}' is not in the read-only allowlist. "
                "Only allowlisted tools can be called."
            )

        self._call_count += 1
        logger.info(
            "tool_call_dispatched",
            tool=tool_name,
            server=entry.server_handle.config.name,
            call_number=self._call_count,
        )

        try:
            result = await entry.server_handle.session.call_tool(
                tool_name, tool_input
            )

            # Extract text content from MCP result
            result_text = _extract_result_text(result)

            # Gmail body scrubbing (FR-010a)
            if tool_name in _GMAIL_TOOLS:
                result_text = _apply_gmail_scrub(result_text)

            return result_text

        except Exception as exc:
            logger.warning(
                "tool_call_error",
                tool=tool_name,
                server=entry.server_handle.config.name,
                error=str(exc),
            )
            return json.dumps({
                "error": str(exc),
                "tool": tool_name,
            })


def _extract_result_text(result: Any) -> str:
    """Extract text content from an MCP call_tool result."""
    if hasattr(result, "content"):
        parts = []
        for item in result.content:
            if hasattr(item, "text"):
                parts.append(item.text)
            elif hasattr(item, "data"):
                parts.append(str(item.data))
        return "\n".join(parts) if parts else ""
    return str(result)


def _apply_gmail_scrub(result_text: str) -> str:
    """Apply Gmail body scrubbing to a tool result string."""
    try:
        data = json.loads(result_text)
        scrubbed = _scrub_gmail_body(data)
        return json.dumps(scrubbed)
    except (json.JSONDecodeError, TypeError):
        # If we can't parse as JSON, apply regex-based scrubbing as fallback
        # Remove anything that looks like email body content
        scrubbed = re.sub(
            r'"(body|htmlBody|textBody|snippet|raw)":\s*"[^"]*"',
            r'"\1": "[SCRUBBED]"',
            result_text,
        )
        return scrubbed
