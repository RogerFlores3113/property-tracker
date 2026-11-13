"""Helpers for the MCP tests: call a tool on an in-process FastMCP server."""
import anyio
from mcp.types import CallToolResult

from prophelper.mcp_server import build_server


def server(store):
    return build_server(store)


def call(srv, tool, **args):
    async def go():
        return await srv.call_tool(tool, args)
    return anyio.run(go)


def structured(result):
    if isinstance(result, CallToolResult):
        return result.structuredContent
    content, data = result
    return data.get("result", data)


def text(result):
    content = result.content if isinstance(result, CallToolResult) else result[0]
    return "\n".join(c.text for c in content)
