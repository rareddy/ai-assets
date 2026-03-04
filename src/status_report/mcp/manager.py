"""MCP server lifecycle manager: start/stop subprocesses via stdio transport."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import structlog
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from status_report.mcp.config import MCPServerConfig

logger = structlog.get_logger(__name__)


@dataclass
class MCPServerHandle:
    """A running MCP server with its client session."""

    config: MCPServerConfig
    session: ClientSession
    tools: list[dict[str, Any]] = field(default_factory=list)


class MCPManager:
    """Manages MCP server subprocess lifecycle.

    Usage:
        async with MCPManager(configs) as manager:
            handles = manager.handles  # list of MCPServerHandle
    """

    def __init__(self, configs: list[MCPServerConfig]) -> None:
        self._configs = configs
        self._handles: list[MCPServerHandle] = []
        self._cleanup_tasks: list[Any] = []

    @property
    def handles(self) -> list[MCPServerHandle]:
        return list(self._handles)

    async def start_all(self) -> list[MCPServerHandle]:
        """Start all MCP servers concurrently. Returns handles for servers that started."""
        results = await asyncio.gather(
            *[self._start_server(cfg) for cfg in self._configs],
            return_exceptions=True,
        )

        for cfg, result in zip(self._configs, results):
            if isinstance(result, Exception):
                logger.warning(
                    "mcp_server_start_failed",
                    server=cfg.name,
                    error=str(result),
                )
            elif result is not None:
                self._handles.append(result)
                logger.info(
                    "mcp_server_started",
                    server=cfg.name,
                    tool_count=len(result.tools),
                )

        return list(self._handles)

    async def _start_server(self, config: MCPServerConfig) -> MCPServerHandle:
        """Start a single MCP server subprocess and initialize its session."""
        server_params = StdioServerParameters(
            command=config.command,
            args=config.args,
            env=config.env if config.env else None,
        )

        # Create the stdio client connection
        read_stream, write_stream = await self._create_stdio_connection(server_params)
        session = ClientSession(read_stream, write_stream)
        await session.initialize()

        # List available tools
        tools_result = await session.list_tools()
        tools = [
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema,
            }
            for tool in tools_result.tools
        ]

        return MCPServerHandle(config=config, session=session, tools=tools)

    async def _create_stdio_connection(self, params: StdioServerParameters) -> tuple:
        """Create stdio connection to MCP server.

        This uses the mcp SDK's stdio_client. The connection is managed
        as an async context manager internally.
        """
        # The stdio_client returns (read, write) streams
        ctx = stdio_client(params)
        streams = await ctx.__aenter__()
        self._cleanup_tasks.append(ctx)
        return streams

    async def shutdown(self) -> None:
        """Shut down all MCP server subprocesses."""
        for ctx in reversed(self._cleanup_tasks):
            try:
                await ctx.__aexit__(None, None, None)
            except Exception as exc:
                logger.warning("mcp_server_shutdown_error", error=str(exc))
        self._cleanup_tasks.clear()
        self._handles.clear()
        logger.info("mcp_servers_shutdown_complete")


@asynccontextmanager
async def managed_mcp_servers(
    configs: list[MCPServerConfig],
) -> AsyncIterator[MCPManager]:
    """Async context manager for MCP server lifecycle.

    Starts all servers on entry, shuts them all down on exit.
    """
    manager = MCPManager(configs)
    try:
        await manager.start_all()
        yield manager
    finally:
        await manager.shutdown()
