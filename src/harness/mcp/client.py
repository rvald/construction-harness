from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


DEFAULT_CALL_TIMEOUT_S = 30.0


class MCPToolError(Exception):
    """An MCP tool call failed or the server reported a tool-level error.

    The registry's dispatch loop catches any exception from a tool and
    surfaces it to the model as an errored ToolResult (is_error=True). We
    raise this at the MCP boundary so that both timeouts and server-signalled
    failures (`CallToolResult.isError`) reach the model as errors instead of
    being mistaken for successful results.
    """


@dataclass
class MCPServerConfig:
    name: str                    # logical name, used in tool prefixes
    command: str                 # e.g., "npx"
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class MCPTool:
    server: str
    name: str                    # server-qualified name
    raw_name: str                # name as the server knows it
    description: str
    input_schema: dict


class MCPClient:
    """A manager for one or more MCP stdio servers."""

    def __init__(self) -> None:
        self._exit_stack = AsyncExitStack()
        self._sessions: dict[str, ClientSession] = {}
        self._tools: dict[str, MCPTool] = {}

    async def connect(self, config: MCPServerConfig) -> None:
        """Spawn an MCP server and register its tools."""
        params = StdioServerParameters(
            command=config.command, args=config.args, env=config.env
        )
        transport = await self._exit_stack.enter_async_context(
            stdio_client(params)
        )
        read_stream, write_stream = transport

        session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()

        listing = await session.list_tools()
        for raw_tool in listing.tools:
            qualified = f"mcp__{config.name}__{raw_tool.name}"
            self._tools[qualified] = MCPTool(
                server=config.name,
                name=qualified,
                raw_name=raw_tool.name,
                description=raw_tool.description or "",
                input_schema=raw_tool.inputSchema or {"type": "object", "properties": {}},
            )
        self._sessions[config.name] = session

    async def call(
        self,
        qualified_name: str,
        args: dict,
        timeout: float = DEFAULT_CALL_TIMEOUT_S,
    ) -> str:
        mcp_tool = self._tools[qualified_name]
        session = self._sessions[mcp_tool.server]
        # A hung server must not hang the whole agent turn.
        try:
            result = await asyncio.wait_for(
                session.call_tool(mcp_tool.raw_name, args), timeout
            )
        except asyncio.TimeoutError:
            raise MCPToolError(
                f"MCP tool {qualified_name!r} timed out after {timeout}s"
            )
        # result.content is a list of content blocks; stringify
        parts = []
        for c in result.content:
            text = getattr(c, "text", None)
            if text is not None:
                parts.append(text)
            else:
                parts.append(str(c))
        content = "\n".join(parts)
        # MCP signals tool-level failures via `isError`, not exceptions.
        # Surface those as errors so the model doesn't read a failure as a
        # success and build on a bad result.
        if getattr(result, "isError", False):
            raise MCPToolError(
                content or f"MCP tool {qualified_name!r} reported an error"
            )
        return content

    def tools(self) -> list[MCPTool]:
        return list(self._tools.values())

    async def close(self) -> None:
        await self._exit_stack.aclose()
