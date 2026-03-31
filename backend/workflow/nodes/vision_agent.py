"""Vision agent node: analyze image evidence using a local multimodal Ollama model."""

from __future__ import annotations

import base64
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from backend.config import settings
from backend.workflow.state import IncidentState


class _VisionResult(BaseModel):
    vision_confirmed: bool
    confidence_score: float = Field(ge=0.0, le=1.0)
    description: str = Field(min_length=1)


def _first_image_path(evidence_refs: list[str]) -> str | None:
    for ref in evidence_refs:
        p = ref.lower()
        if p.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
            return ref
    return None


def _image_to_data_url(path: str) -> str:
    raw = Path(path).read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    ext = Path(path).suffix.lower().lstrip(".") or "jpeg"
    mime = "jpeg" if ext in ("jpg", "jpeg") else ext
    return f"data:image/{mime};base64,{b64}"


async def _mcp_call(server_url: str, tool_name: str, arguments: dict) -> Any:
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await session.call_tool(tool_name, arguments)


async def vision_agent(state: IncidentState) -> IncidentState:
    evidence_refs = list(state.get("evidence_refs") or [])
    image_path = _first_image_path(evidence_refs)

    if not image_path or not Path(image_path).exists():
        state["vision_confirmed"] = False
        state["updated_at"] = datetime.now(UTC).isoformat()
        return state

    data_url = _image_to_data_url(image_path)
    prompt = (
        "You are the vision incident analysis agent.\n"
        "Given the incident context, describe what is visible in the image, "
        "whether it confirms a real threat, and provide a confidence score.\n\n"
        f"incident_type: {state.get('incident_type')}\n"
        f"priority: {state.get('priority')}\n"
        f"location: {(state.get('raw_input') or {}).get('location')}\n"
    )

    llm = ChatOllama(
        model=settings.VISION_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
        temperature=0.2,
    ).with_structured_output(_VisionResult)

    msg = HumanMessage(
        content=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
    )

    result: _VisionResult = await llm.ainvoke([msg])

    state["vision_confirmed"] = result.vision_confirmed
    state["confidence_score"] = float(result.confidence_score)
    # Keep evidence refs as paths; descriptions go to timeline/audit.
    state["updated_at"] = datetime.now(UTC).isoformat()

    out_url = settings.mcp_output_http_url()
    if out_url:
        try:
            await _mcp_call(
                out_url,
                "add_timeline_entry",
                {
                    "incident_id": state["incident_id"],
                    "node_name": "vision_agent",
                    "summary": f"Vision analysis: confirmed={result.vision_confirmed}, confidence={result.confidence_score:.2f}. {result.description}",
                },
            )
        except Exception:
            state["workflow_errors"].append("output_db_write_failed")

    return state
