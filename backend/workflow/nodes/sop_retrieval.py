"""SOP retrieval node using embeddings + pgvector via Input DB MCP."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from langchain_ollama import OllamaEmbeddings

from backend.config import settings
from backend.workflow.state import IncidentState


async def _mcp_call(server_url: str, tool_name: str, arguments: dict) -> Any:
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await session.call_tool(tool_name, arguments)


async def sop_retrieval(state: IncidentState) -> IncidentState:
    raw = state.get("raw_input") or {}
    query = (
        f"incident_type={state.get('incident_type')} "
        f"location={raw.get('location')} "
        f"priority={state.get('priority')} "
        f"confirmed={state.get('confirmed')}"
    )

    embedder = OllamaEmbeddings(
        model=settings.EMBEDDING_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
    )
    embedding = await asyncio.to_thread(embedder.embed_query, query)

    state["incident_query_embedding"] = [float(x) for x in embedding]

    chunks: list[dict] = []
    in_url = settings.mcp_input_http_url()
    if in_url:
        try:
            chunks = await _mcp_call(
                in_url,
                "search_sop_chunks",
                {"query_embedding": state["incident_query_embedding"], "top_k": 5},
            )
        except Exception:
            state["workflow_errors"].append("input_db_read_failed")

    state["sop_chunks"] = chunks or []
    titles = []
    for c in state["sop_chunks"][:5]:
        t = c.get("title")
        if t and t not in titles:
            titles.append(t)
    state["sop_retrieval_reasoning"] = (
        "Retrieved SOP chunks by semantic similarity for incident context"
        + (f": {', '.join(titles)}" if titles else ".")
    )
    state["updated_at"] = datetime.now(UTC).isoformat()

    out_url = settings.mcp_output_http_url()
    if out_url:
        try:
            await _mcp_call(
                out_url,
                "add_timeline_entry",
                {
                    "incident_id": state["incident_id"],
                    "node_name": "sop_retrieval",
                    "summary": state["sop_retrieval_reasoning"],
                },
            )
        except Exception:
            state["workflow_errors"].append("output_db_write_failed")

    return state
