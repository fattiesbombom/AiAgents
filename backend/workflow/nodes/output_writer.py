"""Output writer node.

Persists the latest incident state into the output DB for dashboard consumption.
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.config import settings
from backend.workflow.state import IncidentState


def _evidence_type(path: str) -> str:
    p = path.lower()
    if p.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
        return "snapshot"
    return "log_entry"


async def output_writer(state: IncidentState) -> IncidentState:
    now = datetime.now(UTC).isoformat()
    state["updated_at"] = now

    server_url = f"http://127.0.0.1:{settings.MCP_OUTPUT_DB_PORT}"
    if not server_url:
        return state

    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    incident_id = state["incident_id"]
    raw = state.get("raw_input") or {}

    updates = {
        "incident_type": state.get("incident_type"),
        "priority": state.get("priority"),
        "feed_source": state.get("feed_source"),
        "source_type": state.get("source_type"),
        "location": raw.get("location"),
        "confirmed": state.get("confirmed"),
        "risk_score": state.get("risk_score"),
        "recommended_action": state.get("recommended_action"),
        "incident_status": state.get("incident_status"),
        "police_notified": state.get("police_notified"),
        "police_notification_type": state.get("police_notification_type"),
        "human_review_status": state.get("human_review_status"),
        "updated_at": now,
    }

    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            await session.call_tool("update_incident", {"incident_id": incident_id, "updates": updates})

            for ref in state.get("evidence_refs") or []:
                await session.call_tool(
                    "add_evidence",
                    {
                        "incident_id": incident_id,
                        "evidence_type": _evidence_type(ref),
                        "file_path": ref,
                        "description": "",
                    },
                )

            await session.call_tool(
                "add_timeline_entry",
                {
                    "incident_id": incident_id,
                    "node_name": "output_writer",
                    "summary": "Incident record updated for dashboard output.",
                },
            )

    return state

