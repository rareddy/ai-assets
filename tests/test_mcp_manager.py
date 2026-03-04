"""Tests for MCP server lifecycle manager."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from status_report.mcp.config import MCPServerConfig
from status_report.mcp.manager import MCPManager, MCPServerHandle


class TestMCPManager:
    """Test MCP server start/stop lifecycle."""

    @pytest.fixture
    def simple_config(self) -> MCPServerConfig:
        return MCPServerConfig(
            name="test_server",
            command="echo",
            args=["hello"],
            env={"TEST_KEY": "value"},
            read_only_tools=["test_tool"],
            source_label="test",
        )

    @pytest.mark.asyncio
    async def test_start_all_success(self, simple_config):
        """Starting a server successfully returns its handle."""
        manager = MCPManager([simple_config])

        mock_session = AsyncMock()
        mock_tools_result = MagicMock()
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.description = "A test tool"
        mock_tool.inputSchema = {"type": "object"}
        mock_tools_result.tools = [mock_tool]
        mock_session.list_tools = AsyncMock(return_value=mock_tools_result)
        mock_session.initialize = AsyncMock()

        # Patch _create_stdio_connection to return mock streams
        mock_read = AsyncMock()
        mock_write = AsyncMock()
        manager._create_stdio_connection = AsyncMock(return_value=(mock_read, mock_write))

        with patch(
            "status_report.mcp.manager.ClientSession",
            return_value=mock_session,
        ):
            handles = await manager.start_all()

        assert len(handles) == 1
        assert handles[0].config.name == "test_server"
        assert len(handles[0].tools) == 1
        assert handles[0].tools[0]["name"] == "test_tool"

    @pytest.mark.asyncio
    async def test_start_all_partial_failure(self, simple_config):
        """If one server fails to start, others still succeed."""
        config2 = MCPServerConfig(
            name="failing_server",
            command="false",
            args=[],
            env={},
            read_only_tools=["other_tool"],
            source_label="fail",
        )

        manager = MCPManager([simple_config, config2])

        call_count = 0

        async def mock_start(config):
            nonlocal call_count
            call_count += 1
            if config.name == "failing_server":
                raise ConnectionError("Server failed to start")
            return MCPServerHandle(
                config=config,
                session=AsyncMock(),
                tools=[{"name": "test_tool", "description": "", "input_schema": {}}],
            )

        manager._start_server = mock_start
        handles = await manager.start_all()

        assert len(handles) == 1
        assert handles[0].config.name == "test_server"

    @pytest.mark.asyncio
    async def test_start_all_total_failure(self):
        """If all servers fail, returns empty list."""
        config = MCPServerConfig(
            name="bad_server",
            command="false",
            args=[],
            env={},
            read_only_tools=[],
            source_label="bad",
        )

        manager = MCPManager([config])

        async def mock_start_fail(cfg):
            raise ConnectionError("Failed")

        manager._start_server = mock_start_fail
        handles = await manager.start_all()

        assert len(handles) == 0

    @pytest.mark.asyncio
    async def test_shutdown_cleans_up(self):
        """Shutdown calls __aexit__ on all cleanup tasks."""
        manager = MCPManager([])

        ctx1 = AsyncMock()
        ctx2 = AsyncMock()
        manager._cleanup_tasks = [ctx1, ctx2]
        manager._handles = [MagicMock(), MagicMock()]

        await manager.shutdown()

        ctx1.__aexit__.assert_called_once()
        ctx2.__aexit__.assert_called_once()
        assert len(manager.handles) == 0

    @pytest.mark.asyncio
    async def test_shutdown_handles_errors(self):
        """Shutdown continues even if one cleanup fails."""
        manager = MCPManager([])

        ctx1 = AsyncMock()
        ctx1.__aexit__ = AsyncMock(side_effect=Exception("cleanup error"))
        ctx2 = AsyncMock()
        manager._cleanup_tasks = [ctx1, ctx2]

        await manager.shutdown()

        # Both are attempted even though ctx1 failed
        ctx1.__aexit__.assert_called_once()
        ctx2.__aexit__.assert_called_once()
