"""Output writer: final incident persistence, dispatch notification, AI incident report."""

from __future__ import annotations

from datetime import UTC, datetime

from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from backend.config import settings
from backend.mcp.tool_result import tool_result_as_dict
from backend.workflow.state import IncidentState


def _evidence_type(path: str) -> str:
    p = path.lower()
    if p.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
        return "snapshot"
    return "log_entry"


def _final_incident_status(state: IncidentState) -> str:
    if state.get("incident_status") == "rejected":
        return "rejected"
    if state.get("police_notified"):
        return "escalated"
    return "closed"


class _IncidentReportNarrative(BaseModel):
    narrative: str = Field(
        min_length=20,
        description="Structured plain-English incident report for records",
    )


async def output_writer(state: IncidentState) -> IncidentState:
    now_dt = datetime.now(UTC)
    now_iso = now_dt.isoformat()
    state["updated_at"] = now_iso

    server_url = settings.mcp_output_http_url()
    if not server_url:
        return state

    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    incident_id = state["incident_id"]
    raw = state.get("raw_input") or {}
    final_status = _final_incident_status(state)
    state["incident_status"] = final_status  # type: ignore[assignment]

    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Step 1 — core incident fields (final status, risk, police)
            await session.call_tool(
                "update_incident",
                {
                    "incident_id": incident_id,
                    "updates": {
                        "incident_status": final_status,
                        "risk_score": state.get("risk_score", 0.0),
                        "recommended_action": state.get("recommended_action", ""),
                        "police_notified": state.get("police_notified", False),
                        "police_notification_type": state.get("police_notification_type"),
                        "updated_at": now_dt,
                    },
                },
            )

            # Step 2 — dispatch notification row + incident.dispatch_sent_at if instruction present
            instr = (state.get("dispatch_instruction") or "").strip()
            if instr:
                dispatched_by = str(raw.get("user_id") or "system")
                role = state.get("dispatched_officer_role")
                await session.call_tool(
                    "create_dispatch_notification",
                    {
                        "incident_id": incident_id,
                        "instruction": instr,
                        "dispatched_officer_role": role if isinstance(role, str) else None,
                        "dispatched_by": dispatched_by,
                    },
                )
                if not state.get("dispatch_sent_at"):
                    state["dispatch_sent_at"] = now_iso
                    await session.call_tool(
                        "update_incident",
                        {
                            "incident_id": incident_id,
                            "updates": {"dispatch_sent_at": now_dt, "updated_at": now_dt},
                        },
                    )

            # Context for narrative (timeline + evidence from DB)
            gi_raw = await session.call_tool("get_incident", {"incident_id": incident_id})
            ctx = tool_result_as_dict(gi_raw) or (gi_raw if isinstance(gi_raw, dict) else {})
            timeline = ctx.get("timeline") if isinstance(ctx.get("timeline"), list) else []
            evidence = ctx.get("evidence") if isinstance(ctx.get("evidence"), list) else []

            timeline_txt = "\n".join(
                f"- {e.get('created_at')}: [{e.get('node_name')}] {e.get('summary')}"
                for e in timeline[:40]
                if isinstance(e, dict)
            )
            evidence_txt = "\n".join(
                f"- {e.get('evidence_type')}: {e.get('file_path')} ({e.get('description', '')})"
                for e in evidence[:30]
                if isinstance(e, dict)
            )

            # Steps 3–4 — LLM narrative + incident_reports row (skip if already generated)
            report_id: str | None = None
            if not state.get("incident_report_generated"):
                prompt = (
                    "You are a professional security operations report writer.\n"
                    "Write a single structured plain-English narrative for the official incident record.\n"
                    "Cover: incident type and severity, location, chronological timeline of key events, "
                    "evidence available, actions taken (including police notification if any), "
                    "dispatch instructions if relevant, and recommended follow-up.\n"
                    "Use clear sections or paragraphs; be factual and concise.\n\n"
                    f"incident_id: {incident_id}\n"
                    f"incident_type: {state.get('incident_type')}\n"
                    f"priority: {state.get('priority')}\n"
                    f"location: {raw.get('location')}\n"
                    f"feed_source: {state.get('feed_source')}\n"
                    f"source_type: {state.get('source_type')}\n"
                    f"confirmed: {state.get('confirmed')}\n"
                    f"risk_score: {state.get('risk_score')}\n"
                    f"recommended_action: {state.get('recommended_action')}\n"
                    f"recommended_action_reasoning: {state.get('recommended_action_reasoning')}\n"
                    f"police_notified: {state.get('police_notified')}\n"
                    f"police_notification_type: {state.get('police_notification_type')}\n"
                    f"human_review_status: {state.get('human_review_status')}\n"
                    f"final_incident_status: {final_status}\n"
                    f"dispatch_instruction: {state.get('dispatch_instruction')}\n\n"
                    f"TIMELINE:\n{timeline_txt or '(none)'}\n\n"
                    f"EVIDENCE:\n{evidence_txt or '(none)'}\n"
                )

                llm = ChatOllama(
                    model=settings.LLM_MODEL,
                    base_url=settings.OLLAMA_BASE_URL,
                    temperature=0.2,
                ).with_structured_output(_IncidentReportNarrative)

                try:
                    out: _IncidentReportNarrative = await llm.ainvoke(prompt)
                    narrative = out.narrative
                except Exception:
                    narrative = (
                        f"Automated stub report for incident {incident_id}: "
                        f"{state.get('incident_type')} at {raw.get('location')} "
                        f"(priority {state.get('priority')}). "
                        f"Status: {final_status}. LLM generation failed; amend manually."
                    )
                    state["workflow_errors"].append("incident_report_llm_failed")

                report_type = (
                    "shift_summary"
                    if state.get("task_mode") == "routine"
                    and state.get("routine_task_type") == "report_generation"
                    else "occurrence"
                )
                generated_by = str(raw.get("user_id") or "system")

                rep_raw = await session.call_tool(
                    "create_incident_report",
                    {
                        "incident_id": incident_id,
                        "report_text": narrative,
                        "report_type": report_type,
                        "generated_by": generated_by,
                    },
                )
                rep = tool_result_as_dict(rep_raw) or (rep_raw if isinstance(rep_raw, dict) else {})
                if rep.get("id"):
                    report_id = str(rep["id"])
                state["incident_report_generated"] = True
                state["incident_report_path"] = f"incident_reports:{report_id or incident_id}"

                await session.call_tool(
                    "update_incident",
                    {
                        "incident_id": incident_id,
                        "updates": {
                            "incident_report_generated": True,
                            "incident_report_path": state["incident_report_path"],
                            "updated_at": now_dt,
                        },
                    },
                )

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

            # Step 5 — timeline
            await session.call_tool(
                "add_timeline_entry",
                {
                    "incident_id": incident_id,
                    "node_name": "output_writer",
                    "summary": "Incident closed and report generated",
                },
            )

            # Step 6 — final audit
            await session.call_tool(
                "write_audit_log",
                {
                    "incident_id": incident_id,
                    "actor": "output_writer",
                    "action": "incident_output_finalized",
                    "detail": {
                        "incident_status": final_status,
                        "police_notified": state.get("police_notified"),
                        "incident_report_id": report_id,
                        "dispatch_instruction_recorded": bool(instr),
                    },
                },
            )

            # Refresh remaining dashboard fields on incident row
            await session.call_tool(
                "update_incident",
                {
                    "incident_id": incident_id,
                    "updates": {
                        "incident_type": state.get("incident_type"),
                        "priority": state.get("priority"),
                        "feed_source": state.get("feed_source"),
                        "source_type": state.get("source_type"),
                        "location": raw.get("location"),
                        "confirmed": state.get("confirmed"),
                        "human_review_status": state.get("human_review_status"),
                        "human_reviewer_rank": state.get("human_reviewer_rank"),
                        "responder_rank": state.get("responder_rank"),
                        "responder_role_label": state.get("responder_role_label"),
                        "responder_permissions": state.get("responder_permissions"),
                        "can_approve_escalation": state.get("can_approve_escalation"),
                        "can_operate_scc": state.get("can_operate_scc"),
                        "assigned_zone": state.get("assigned_zone"),
                        "deployment_type": state.get("deployment_type"),
                        "dispatch_instruction": state.get("dispatch_instruction"),
                        "dispatched_officer_role": state.get("dispatched_officer_role"),
                        "updated_at": datetime.now(UTC),
                    },
                },
            )

    return state
