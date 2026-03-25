"""Call MCP tools over streamable HTTP (shared by FastAPI and tests)."""

from __future__ import annotations

from typing import Any

from backend.mcp.tool_result import tool_result_as_dict


async def call_mcp_tool(server_url: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            res = await session.call_tool(tool_name, arguments)
            parsed = tool_result_as_dict(res)
            if parsed is not None:
                return parsed
            if isinstance(res, dict):
                return res
            return {"result": res}
