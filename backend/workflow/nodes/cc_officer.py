"""Command Centre officer node: dispatch guidance for ground officers (SSO+ workflow)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from backend.config import settings
from backend.workflow.state import IncidentState


class _CCDispatch(BaseModel):
    dispatch_instruction: str = Field(min_length=1)
    dispatched_officer_role: Literal["SO", "SSO", "SS"] = Field(
        description="SO routine patrol, SSO for SCC-level coordination, SS for complex incidents"
    )


async def _mcp_call(server_url: str, tool_name: str, arguments: dict) -> Any:
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await session.call_tool(tool_name, arguments)


async def cc_officer(state: IncidentState) -> IncidentState:
    """Generate CC dispatch instruction; only routed here for remote + command_centre."""
    if state.get("deployment_type") != "command_centre":
        return state

    raw = state.get("raw_input") or {}
    sop_text = "\n\n".join(
        f"- ({c.get('title')} | {c.get('source_file')})\n{c.get('content')}"
        for c in (state.get("sop_chunks") or [])
    )

    prompt = (
        "You are a Command Centre security officer (SSO level or above).\n"
        "Based on this incident context, risk, recommended action, and SOP excerpts, "
        "decide what the ground officer should be told to do next.\n"
        "Write the dispatch instruction in plain English, as a direct order or brief you would radio or send.\n"
        "Also choose which rank should handle it on the ground:\n"
        "- SO: routine response, patrol, standard checks\n"
        "- SSO: SCC-level tasks, key/CCTV coordination, elevated but not full incident command\n"
        "- SS: complex incident, multi-unit coordination, incident management\n\n"
        f"incident_type: {state.get('incident_type')}\n"
        f"priority: {state.get('priority')}\n"
        f"location: {raw.get('location')}\n"
        f"source_type: {state.get('source_type')}\n"
        f"source_label: {raw.get('source_label')}\n"
        f"risk_score: {state.get('risk_score')}\n"
        f"recommended_action: {state.get('recommended_action')}\n"
        f"recommended_action_reasoning: {state.get('recommended_action_reasoning')}\n\n"
        f"SOP_CHUNKS:\n{sop_text}\n"
    )

    llm = ChatOllama(
        model=settings.LLM_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
        temperature=0.2,
    ).with_structured_output(_CCDispatch)

    result: _CCDispatch = await llm.ainvoke(prompt)

    state["dispatch_instruction"] = result.dispatch_instruction
    state["dispatched_officer_role"] = result.dispatched_officer_role
    state["updated_at"] = datetime.now(UTC).isoformat()

    out_url = settings.mcp_output_http_url()
    if out_url:
        try:
            await _mcp_call(
                out_url,
                "update_incident",
                {
                    "incident_id": state["incident_id"],
                    "updates": {
                        "dispatch_instruction": state["dispatch_instruction"],
                        "dispatched_officer_role": state["dispatched_officer_role"],
                        "updated_at": datetime.now(UTC),
                    },
                },
            )
            await _mcp_call(
                out_url,
                "add_timeline_entry",
                {
                    "incident_id": state["incident_id"],
                    "node_name": "cc_officer",
                    "summary": "Command Centre dispatch instruction generated.",
                },
            )
            await _mcp_call(
                out_url,
                "write_audit_log",
                {
                    "incident_id": state["incident_id"],
                    "actor": "cc_officer",
                    "action": "dispatch_instruction_generated",
                    "detail": {
                        "dispatched_officer_role": state["dispatched_officer_role"],
                    },
                },
            )
        except Exception:
            state["workflow_errors"].append("output_db_cc_officer_write_failed")

    return state
