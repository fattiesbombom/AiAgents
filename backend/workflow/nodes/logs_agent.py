"""Logs agent node: analyze access logs, alarms, and motion events via Input DB MCP."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from backend.config import settings
from backend.workflow.state import IncidentState


class _LogsResult(BaseModel):
    logs_confirmed: bool
    confidence_score: float = Field(ge=0.0, le=1.0)
    summary: str = Field(min_length=1)


async def _mcp_call(server_url: str, tool_name: str, arguments: dict) -> Any:
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await session.call_tool(tool_name, arguments)


async def logs_agent(state: IncidentState) -> IncidentState:
    raw = state.get("raw_input") or {}
    zone = raw.get("location") or "unknown"
    hint = raw.get("incident_type_hint")

    motion_events: list[dict] = []
    access_logs: list[dict] = []
    alarm_events: list[dict] = []
    authorisation: dict | None = None

    in_url = f"http://127.0.0.1:{settings.MCP_INPUT_DB_PORT}"
    if in_url:
        try:
            motion_events = await _mcp_call(
                in_url,
                "get_recent_motion_events",
                {"source_type": raw.get("source_type", "cctv"), "minutes_back": 10},
            )
            access_logs = await _mcp_call(
                in_url,
                "get_access_logs_for_zone",
                {"zone": zone, "minutes_back": 30},
            )
            alarm_events = await _mcp_call(
                in_url,
                "get_recent_alarm_events",
                {"minutes_back": 10, "alarm_type": hint if hint in ("fire", "intruder") else None},
            )

            if access_logs:
                badge_id = access_logs[0].get("badge_id")
                if badge_id:
                    authorisation = await _mcp_call(
                        in_url,
                        "check_employee_authorisation",
                        {"badge_id": str(badge_id), "zone": zone},
                    )
        except Exception:
            state["workflow_errors"].append("input_db_read_failed")

    prompt = (
        "You are the logs analysis agent.\n"
        "Decide if the incident is confirmed based on motion, access, and alarm events.\n\n"
        f"incident_type_hint: {hint}\n"
        f"zone/location: {zone}\n"
        f"motion_events(last10m): {motion_events}\n"
        f"access_logs(last30m): {access_logs}\n"
        f"alarm_events(last10m): {alarm_events}\n"
        f"employee_authorisation: {authorisation}\n\n"
        "Answer with logs_confirmed (true/false), confidence_score (0-1), and a short summary."
    )

    llm = ChatOllama(
        model=settings.LLM_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
        temperature=0.2,
    ).with_structured_output(_LogsResult)

    result: _LogsResult = await llm.ainvoke(prompt)

    state["logs_confirmed"] = result.logs_confirmed
    state["confidence_score"] = float(result.confidence_score)
    state["updated_at"] = datetime.now(UTC).isoformat()

    out_url = f"http://127.0.0.1:{settings.MCP_OUTPUT_DB_PORT}"
    if out_url:
        try:
            await _mcp_call(
                out_url,
                "add_timeline_entry",
                {
                    "incident_id": state["incident_id"],
                    "node_name": "logs_agent",
                    "summary": f"Logs analysis: confirmed={result.logs_confirmed}, confidence={result.confidence_score:.2f}. {result.summary}",
                },
            )
        except Exception:
            state["workflow_errors"].append("output_db_write_failed")

    return state
