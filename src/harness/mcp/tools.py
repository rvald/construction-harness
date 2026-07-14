# src/harness/mcp/tools.py
from __future__ import annotations

from ..tools.base import Tool
from .client import MCPClient


def wrap_mcp_tools(client: MCPClient) -> list[Tool]:
    tools: list[Tool] = []
    for mcp_tool in client.tools():
        t = _wrap_one(client, mcp_tool.name, mcp_tool.description,
                       mcp_tool.input_schema)
        tools.append(t)
    return tools


def _wrap_one(client: MCPClient, name: str, description: str,
              input_schema: dict) -> Tool:
    async def arun(**kwargs) -> str:
        return await client.call(name, kwargs)

    return Tool(
        name=name,
        description=description,
        input_schema=input_schema,
        arun=arun,                   # async Tool field — see below
        side_effects=frozenset({"network", "mutate"}),  # pessimistic default
    )
