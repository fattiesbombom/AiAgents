"""Police immediate notification node (live, confirmed incidents)."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

from backend.workflow.state import IncidentState


async def police_immediate(state: IncidentState) -> IncidentState:
    # Actual police integration is out of scope; we only mark state + audit/timeline hooks.
    now = datetime.now(UTC).isoformat()
    state["police_notified"] = True
    state["police_notification_type"] = "immediate"
    state["police_notified_at"] = now
    state["incident_status"] = "escalated"
    state["updated_at"] = now

    # Best-effort audit entry via MCP (if configured)
    from backend.config import settings

    server_url = settings.mcp_output_http_url()
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
                        "detail": {"type": "immediate"},
                    },
                )
                await session.call_tool(
                    "add_timeline_entry",
                    {
                        "incident_id": state["incident_id"],
                        "node_name": "police_immediate",
                        "summary": "Immediate police notification triggered for live confirmed incident.",
                    },
                )

    # Yield control to allow parallel branch progress
    await asyncio.sleep(0)
    return state
