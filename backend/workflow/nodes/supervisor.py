"""Supervisor node: classifies incident and initializes output DB record."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Literal

from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from backend.config import settings
from backend.workflow.state import IncidentState


class _Classification(BaseModel):
    incident_type: Literal["intrusion", "fire", "assault", "tailgating", "other"]
    priority: Literal["critical", "high", "medium", "low"]
    classification_reasoning: str = Field(min_length=1)


async def _mcp_call(server_url: str, tool_name: str, arguments: dict) -> Any:
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await session.call_tool(tool_name, arguments)


async def supervisor(state: IncidentState) -> IncidentState:
    raw = state.get("raw_input") or {}

    # 1) Fetch responder role from Supabase Auth via MCP if user_id present
    user_id = raw.get("user_id")
    auth_url = f"http://127.0.0.1:{settings.MCP_AUTH_DB_PORT}"
    if user_id and auth_url:
        try:
            role_info = await _mcp_call(
                auth_url,
                "get_user_role",
                {"user_id": str(user_id)},
            )
            if isinstance(role_info, dict):
                role = role_info.get("role")
                state["responder_role"] = role if isinstance(role, str) else None
        except Exception:
            # Non-fatal; keep responder_role as None
            state["workflow_errors"].append("auth_role_lookup_failed")

    # 2) Classification prompt
    hint = raw.get("incident_type_hint")
    evidence = raw.get("evidence_refs") or state.get("evidence_refs") or []
    prompt = (
        "You are the incident supervisor agent.\n"
        "Classify the incident type and priority.\n\n"
        f"feed_source: {state['feed_source']}\n"
        f"source_type: {state['source_type']}\n"
        f"location: {raw.get('location')}\n"
        f"timestamp: {raw.get('timestamp')}\n"
        f"incident_type_hint: {hint}\n"
        f"responder_role: {state.get('responder_role')}\n"
        f"confidence_score: {raw.get('confidence_score')}\n"
        f"evidence_refs: {evidence}\n\n"
        f"raw_input: {raw}\n"
    )

    # 3) Model call with structured output
    llm = ChatOllama(
        model=settings.LLM_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
        temperature=0.2,
    ).with_structured_output(_Classification)

    result: _Classification = await llm.ainvoke(prompt)

    # 4) Write classification fields
    state["incident_type"] = result.incident_type
    state["priority"] = result.priority
    state["classification_reasoning"] = result.classification_reasoning

    # 5) Create initial incident record in output DB
    out_url = f"http://127.0.0.1:{settings.MCP_OUTPUT_DB_PORT}"
    if out_url:
        now = datetime.now(UTC)
        incident_payload = {
            "id": state["incident_id"],
            "incident_type": state["incident_type"],
            "priority": state["priority"],
            "feed_source": state["feed_source"],
            "source_type": state["source_type"],
            "location": raw.get("location"),
            "confirmed": state.get("confirmed", False),
            "risk_score": state.get("risk_score", 0.0),
            "recommended_action": state.get("recommended_action", ""),
            "incident_status": state.get("incident_status", "open"),
            "police_notified": state.get("police_notified", False),
            "police_notification_type": state.get("police_notification_type"),
            "human_review_status": state.get("human_review_status"),
            "created_at": now,
            "updated_at": now,
        }
        try:
            await _mcp_call(
                out_url,
                "create_incident",
                {"incident": incident_payload},
            )

            # 6) Timeline entry
            await _mcp_call(
                out_url,
                "add_timeline_entry",
                {
                    "incident_id": state["incident_id"],
                    "node_name": "supervisor",
                    "summary": f"Classified as {state['incident_type']} ({state['priority']}).",
                },
            )
        except Exception:
            state["workflow_errors"].append("output_db_write_failed")

    # 7) Return updated state
    state["updated_at"] = datetime.now(UTC).isoformat()
    return state
