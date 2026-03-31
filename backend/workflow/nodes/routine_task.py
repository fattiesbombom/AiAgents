"""Routine task workflow: patrol, CCTV monitoring, shift reports, etc."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.config import settings
from backend.mcp.tool_result import tool_result_as_dict
from backend.workflow.state import IncidentState


def _actor_label(state: IncidentState) -> str:
    r = state.get("responder_rank")
    if r:
        return str(r)
    raw = state.get("raw_input") or {}
    oid = raw.get("officer_id")
    return str(oid) if oid else "unknown"


async def _mcp_call(server_url: str, tool_name: str, arguments: dict) -> Any:
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await session.call_tool(tool_name, arguments)


def _unwrap_dict(res: Any) -> dict[str, Any]:
    d = tool_result_as_dict(res)
    if isinstance(d, dict):
        return d
    if isinstance(res, dict):
        return res
    return {}


async def _ensure_output_incident_row(state: IncidentState, raw: dict) -> None:
    out_url = settings.mcp_output_http_url()
    now = datetime.now(UTC)
    gi = _unwrap_dict(await _mcp_call(out_url, "get_incident", {"incident_id": state["incident_id"]}))
    if gi.get("id"):
        return

    payload = {
        "id": state["incident_id"],
        "incident_type": state.get("incident_type", "other"),
        "priority": state.get("priority", "low"),
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
        "responder_rank": state.get("responder_rank"),
        "responder_role_label": state.get("responder_role_label"),
        "responder_permissions": state.get("responder_permissions"),
        "can_approve_escalation": state.get("can_approve_escalation", False),
        "can_operate_scc": state.get("can_operate_scc", False),
        "assigned_zone": state.get("assigned_zone"),
        "deployment_type": state.get("deployment_type"),
        "dispatch_instruction": state.get("dispatch_instruction"),
        "dispatched_officer_role": state.get("dispatched_officer_role"),
        "dispatch_sent_at": state.get("dispatch_sent_at"),
        "incident_report_generated": state.get("incident_report_generated", False),
        "incident_report_path": state.get("incident_report_path"),
        "created_at": now,
        "updated_at": now,
    }
    try:
        await _mcp_call(out_url, "create_incident", {"incident": payload})
    except Exception:
        pass


async def routine_task(state: IncidentState) -> IncidentState:
    raw = dict(state.get("raw_input") or {})
    out_url = settings.mcp_output_http_url()
    in_url = settings.mcp_input_http_url()
    now_iso = datetime.now(UTC).isoformat()
    task_t = state.get("routine_task_type") or "patrol"
    actor = _actor_label(state)

    await _ensure_output_incident_row(state, raw)

    summary_start = f"{task_t} started by {actor} at {now_iso}"
    try:
        await _mcp_call(
            out_url,
            "add_timeline_entry",
            {
                "incident_id": state["incident_id"],
                "node_name": "routine_task",
                "summary": summary_start,
            },
        )
    except Exception:
        state["workflow_errors"].append("routine_task_timeline_failed")

    # Monitoring tasks: escalate to full incident workflow if input DB shows activity
    if task_t in ("cctv_monitoring", "virtual_patrol"):
        zone = (state.get("assigned_zone") or raw.get("location") or "").strip()
        try:
            chk_raw = await _mcp_call(
                in_url,
                "get_unacknowledged_events_for_zone",
                {"zone": zone, "minutes_back": 15},
            )
            chk = _unwrap_dict(chk_raw)
            if chk.get("has_anomaly"):
                state["task_mode"] = "non_routine"
                state["raw_input"] = {
                    **raw,
                    "incident_type_hint": "Elevated from routine monitoring — unacknowledged motion/alarm in zone",
                }
                try:
                    await _mcp_call(
                        out_url,
                        "add_timeline_entry",
                        {
                            "incident_id": state["incident_id"],
                            "node_name": "routine_task",
                            "summary": "Routine task elevated to non-routine (anomaly in input DB).",
                        },
                    )
                    await _mcp_call(
                        out_url,
                        "write_audit_log",
                        {
                            "incident_id": state["incident_id"],
                            "actor": actor,
                            "action": "routine_escalated_to_incident",
                            "detail": {"zone": zone or None, "check": chk},
                        },
                    )
                except Exception:
                    state["workflow_errors"].append("routine_escalation_log_failed")
                state["updated_at"] = now_iso
                return state
        except Exception:
            state["workflow_errors"].append("routine_input_db_check_failed")

    if task_t == "report_generation":
        lines: list[str] = []
        try:
            lo_raw = await _mcp_call(out_url, "list_open_incidents", {"limit": 200})
            lo = _unwrap_dict(lo_raw)
            open_rows = lo.get("open_incidents") if isinstance(lo.get("open_incidents"), list) else []
            lines.append(f"Open incidents at {now_iso}: {len(open_rows)}")
            for row in open_rows[:50]:
                if not isinstance(row, dict):
                    continue
                lines.append(
                    f"- {row.get('id')}: {row.get('incident_type')} / {row.get('priority')} @ {row.get('location')}"
                )
            full_summary = "\n".join(lines)
            sched_id = raw.get("scheduled_task_id")
            await _mcp_call(
                out_url,
                "create_shift_report",
                {
                    "summary": full_summary,
                    "routine_incident_id": state["incident_id"],
                    "scheduled_task_id": str(sched_id) if sched_id else None,
                },
            )
            state["routine_task_completed"] = True
            state["routine_task_notes"] = full_summary[:4000]
        except Exception:
            state["workflow_errors"].append("routine_shift_report_failed")
            state["routine_task_notes"] = "Shift report generation failed; see workflow_errors."
            state["routine_task_completed"] = True
    else:
        state["routine_task_completed"] = True

    try:
        await _mcp_call(
            out_url,
            "write_audit_log",
            {
                "incident_id": state["incident_id"],
                "actor": actor,
                "action": "routine_task_completed",
                "detail": {
                    "routine_task_type": task_t,
                    "scheduled_task_id": raw.get("scheduled_task_id"),
                },
            },
        )
    except Exception:
        state["workflow_errors"].append("routine_task_audit_failed")

    state["updated_at"] = now_iso
    return state

