"""Tool registry: collects tool schemas from MCP servers and filters by allowlist."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from status_report.mcp.manager import MCPServerHandle

logger = structlog.get_logger(__name__)


@dataclass
class ToolEntry:
    """A registered tool with its source server handle."""

    name: str
    description: str
    input_schema: dict[str, Any]
    server_handle: MCPServerHandle


class ToolRegistry:
    """Collects and filters MCP tools, enforcing the read-only allowlist.

    Only tools that appear in a server's `read_only_tools` allowlist are
    registered. All other tools are silently dropped.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolEntry] = {}

    @property
    def tools(self) -> dict[str, ToolEntry]:
        return dict(self._tools)

    def register_server(self, handle: MCPServerHandle) -> int:
        """Register tools from an MCP server, filtering by its allowlist.

        Returns the number of tools registered from this server.
        """
        allowlist = set(handle.config.read_only_tools)
        registered = 0

        for tool in handle.tools:
            tool_name = tool["name"]
            if tool_name not in allowlist:
                logger.debug(
                    "tool_filtered_by_allowlist",
                    tool=tool_name,
                    server=handle.config.name,
                )
                continue

            if tool_name in self._tools:
                logger.warning(
                    "tool_name_conflict",
                    tool=tool_name,
                    existing_server=self._tools[tool_name].server_handle.config.name,
                    new_server=handle.config.name,
                )
                continue

            self._tools[tool_name] = ToolEntry(
                name=tool_name,
                description=tool["description"],
                input_schema=tool["input_schema"],
                server_handle=handle,
            )
            registered += 1

        logger.info(
            "tools_registered",
            server=handle.config.name,
            registered=registered,
            total_available=len(handle.tools),
            filtered=len(handle.tools) - registered,
        )
        return registered

    def register_all(self, handles: list[MCPServerHandle]) -> int:
        """Register tools from all MCP server handles. Returns total tools registered."""
        total = 0
        for handle in handles:
            total += self.register_server(handle)
        return total

    def get_tool(self, name: str) -> ToolEntry | None:
        """Look up a tool by name. Returns None if not registered."""
        return self._tools.get(name)

    def get_anthropic_tools(self) -> list[dict[str, Any]]:
        """Return tool definitions in Anthropic API format for Claude.

        This produces the `tools` parameter for the `messages.create` call.
        """
        return [
            {
                "name": entry.name,
                "description": entry.description,
                "input_schema": entry.input_schema,
            }
            for entry in self._tools.values()
        ]

    def get_source_labels(self) -> list[str]:
        """Return unique source labels for all registered tools."""
        return list({
            entry.server_handle.config.source_label
            for entry in self._tools.values()
        })
