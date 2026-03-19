"""Police escalation notification node (remote incidents after human approval)."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from backend.workflow.state import IncidentState


async def police_escalation(state: IncidentState) -> IncidentState:
    # Actual police integration is out of scope; we only mark state + audit/timeline hooks.
    now = datetime.now(UTC).isoformat()
    state["police_notified"] = True
    state["police_notification_type"] = "escalation"
    state["police_notified_at"] = now
    state["incident_status"] = "escalated"
    state["updated_at"] = now

    from backend.config import settings

    server_url = f"http://127.0.0.1:{settings.MCP_OUTPUT_DB_PORT}"
    if server_url:
        from mcp.client.session import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async with streamable_http_client(server_url) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                await session.call_tool(
                    "write_audit_log",
                    {
                        "incident_id": state["incident_id"],
                        "actor": "system",
                        "action": "police_notification",
                        "detail": {"type": "escalation"},
                    },
                )
                await session.call_tool(
                    "add_timeline_entry",
                    {
                        "incident_id": state["incident_id"],
                        "node_name": "police_escalation",
                        "summary": "Police escalation triggered after human approval for remote incident.",
                    },
                )

    return state
