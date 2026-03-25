"""Risk/decision node: produce risk score + recommended action using SOP chunks."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from backend.config import settings
from backend.workflow.state import IncidentState


class _Decision(BaseModel):
    risk_score: float = Field(ge=0.0, le=1.0)
    recommended_action: str = Field(min_length=1)
    recommended_action_reasoning: str = Field(min_length=1)


async def _mcp_call(server_url: str, tool_name: str, arguments: dict) -> Any:
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await session.call_tool(tool_name, arguments)


async def risk_decision(state: IncidentState) -> IncidentState:
    raw = state.get("raw_input") or {}
    sop_text = "\n\n".join(
        f"- ({c.get('title')} | {c.get('source_file')})\n{c.get('content')}"
        for c in (state.get("sop_chunks") or [])
    )

    prompt = (
        "You are a security incident response decision agent.\n"
        "Given the incident context and retrieved SOPs, produce a risk_score (0-1) "
        "and a clear recommended_action.\n\n"
        f"incident_type: {state.get('incident_type')}\n"
        f"priority: {state.get('priority')}\n"
        f"feed_source: {state.get('feed_source')}\n"
        f"source_type: {state.get('source_type')}\n"
        f"source_label: {(state.get('raw_input') or {}).get('source_label')}\n"
        f"confirmed: {state.get('confirmed')}\n"
        f"location: {raw.get('location')}\n"
        f"responder_rank: {state.get('responder_rank')}\n"
        f"responder_role_label: {state.get('responder_role_label')}\n"
        f"can_approve_escalation: {state.get('can_approve_escalation')}\n"
        f"can_operate_scc: {state.get('can_operate_scc')}\n"
        f"confidence_score: {state.get('confidence_score')}\n\n"
        f"SOP_CHUNKS:\n{sop_text}\n"
    )

    llm = ChatOllama(
        model=settings.LLM_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
        temperature=0.2,
    ).with_structured_output(_Decision)

    result: _Decision = await llm.ainvoke(prompt)

    state["risk_score"] = float(result.risk_score)
    state["recommended_action"] = result.recommended_action
    state["recommended_action_reasoning"] = result.recommended_action_reasoning
    state["updated_at"] = datetime.now(UTC).isoformat()

    out_url = f"http://127.0.0.1:{settings.MCP_OUTPUT_DB_PORT}"
    if out_url:
        try:
            await _mcp_call(
                out_url,
                "update_incident",
                {
                    "incident_id": state["incident_id"],
                    "updates": {
                        "risk_score": state["risk_score"],
                        "recommended_action": state["recommended_action"],
                        "updated_at": datetime.now(UTC),
                    },
                },
            )
            await _mcp_call(
                out_url,
                "add_timeline_entry",
                {
                    "incident_id": state["incident_id"],
                    "node_name": "risk_decision",
                    "summary": f"Risk score {state['risk_score']:.2f}. Recommended action generated.",
                },
            )
            await _mcp_call(
                out_url,
                "write_audit_log",
                {
                    "incident_id": state["incident_id"],
                    "actor": "risk_decision",
                    "action": "decision_computed",
                    "detail": {
                        "risk_score": state["risk_score"],
                        "priority": state.get("priority"),
                        "incident_type": state.get("incident_type"),
                    },
                },
            )
        except Exception:
            state["workflow_errors"].append("output_db_write_failed")

    return state
