"""Supervisor node: classifies incident and initializes output DB record."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from backend.config import settings
from backend.mcp.tool_result import tool_result_as_dict
from backend.workflow.state import CertisRank, IncidentState


class _Classification(BaseModel):
    incident_type: Literal["intrusion", "fire", "assault", "tailgating", "other", "officer_down"]
    priority: Literal["critical", "high", "medium", "low"]
    classification_reasoning: str = Field(min_length=1)


async def _mcp_call(server_url: str, tool_name: str, arguments: dict) -> Any:
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await session.call_tool(tool_name, arguments)


_CERTIS_RANKS: frozenset[str] = frozenset({"SO", "SSO", "SS", "SSS", "CSO"})


def _coerce_int_optional(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


async def _supervisor_load_auth(state: IncidentState, raw: dict, user_id: Any) -> None:
    """Load role from Auth MCP into state."""
    auth_url = f"http://127.0.0.1:{settings.MCP_AUTH_DB_PORT}"
    if not user_id:
        state["responder_rank"] = None
        state["role_type"] = None
        state["todays_assignment"] = None
        state["responder_role_label"] = None
        state["responder_permissions"] = None
        state["can_approve_escalation"] = False
        state["can_operate_scc"] = False
        state["assigned_zone"] = None
        state["deployment_type"] = None
    elif auth_url:
        try:
            role_raw = await _mcp_call(
                auth_url,
                "get_user_role",
                {"user_id": str(user_id)},
            )
            role_info = tool_result_as_dict(role_raw) or {}
            rank_raw = role_info.get("rank")
            rank: CertisRank | None = rank_raw if isinstance(rank_raw, str) and rank_raw in _CERTIS_RANKS else None
            state["responder_rank"] = rank
            rt = role_info.get("role_type")
            if rt in ("security_officer", "auxiliary_police", "enforcement_officer"):
                state["role_type"] = rt  # type: ignore[assignment]
            else:
                state["role_type"] = None
            ta = role_info.get("todays_assignment")
            if ta in ("ground", "command_centre"):
                state["todays_assignment"] = ta  # type: ignore[assignment]
            else:
                state["todays_assignment"] = None
            rl = role_info.get("role_label")
            state["responder_role_label"] = rl if isinstance(rl, str) else None
            perms = role_info.get("permissions")
            state["responder_permissions"] = perms if isinstance(perms, list) else None
            state["can_approve_escalation"] = bool(role_info.get("can_approve_escalation"))
            state["can_operate_scc"] = bool(role_info.get("can_operate_scc"))
            az = role_info.get("assigned_zone")
            state["assigned_zone"] = az if isinstance(az, str) else None
            dt = role_info.get("deployment_type")
            if dt in ("ground", "command_centre"):
                state["deployment_type"] = dt  # type: ignore[assignment]
            else:
                state["deployment_type"] = None
        except Exception:
            state["workflow_errors"].append("auth_role_lookup_failed")


async def _supervisor_persist_incident(state: IncidentState, raw: dict) -> None:
    """Create/update output DB incident + supervisor timeline from current state."""
    out_url = f"http://127.0.0.1:{settings.MCP_OUTPUT_DB_PORT}"
    if not out_url:
        return
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
        gi_raw = await _mcp_call(out_url, "get_incident", {"incident_id": state["incident_id"]})
        existing = tool_result_as_dict(gi_raw) or (gi_raw if isinstance(gi_raw, dict) else {})
        if not existing.get("id"):
            await _mcp_call(
                out_url,
                "create_incident",
                {"incident": incident_payload},
            )
        else:
            updates = {k: v for k, v in incident_payload.items() if k not in ("id", "created_at")}
            await _mcp_call(
                out_url,
                "update_incident",
                {"incident_id": state["incident_id"], "updates": updates},
            )

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


def _certis_priority_hint(state: IncidentState) -> str:
    """Certis Top-10-style starting hint; the LLM may override with reasoning."""
    raw = state.get("raw_input") or {}
    st = state["source_type"]
    sev = str(raw.get("severity") or raw.get("c2_severity") or "").lower()

    if st == "fire_alarm":
        return "critical (fire / life safety)"
    if st == "intruder_alarm":
        return "critical (intruder / VCA)"
    if st in ("lift_alarm", "carpark_intercom"):
        return "high (lift or carpark intercom)"
    if st == "body_worn":
        return "high (body-worn / officer VCA)"
    if st == "door_alarm":
        return "high (door / access breach)"
    if st == "cctv":
        return "high (CCTV / VCA)"
    if st == "nursing_intercom":
        return "medium (nursing intercom — escalate if corroborated)"
    if st == "mop_report":
        return "medium (member-of-public report — escalate if corroborated)"
    if st == "c2_system":
        if sev in ("critical", "crit", "sev1", "p1"):
            return "critical (from C2 severity / payload)"
        if sev in ("high", "sev2", "p2"):
            return "high (from C2 severity / payload)"
        if sev in ("medium", "med", "sev3", "p3"):
            return "medium (from C2 severity / payload)"
        if sev in ("low", "sev4", "p4", "info"):
            return "low (from C2 severity / payload)"
        return "medium — infer from raw_input.severity and any c2_payload / extra fields"
    if st == "manual_trigger":
        return "high default (officer manual trigger — downgrade only with clear justification)"
    if st == "watch_heartbeat":
        return "critical default (wearable biometric — follow incident_type_hint)"
    return "low — use full context"


async def supervisor(state: IncidentState) -> IncidentState:
    raw = state.get("raw_input") or {}

    # 0) Officer down (wearable): deterministic classification — no LLM; skip vision/logs path via graph router
    hint = raw.get("incident_type_hint")
    if hint == "officer_down":
        state["incident_type"] = "officer_down"
        state["priority"] = "critical"
        state["confirmed"] = True
        state["classification_reasoning"] = (
            "Wearable heartbeat alert: officer_down (flat_line or no_signal). "
            "Mandatory critical priority; vision/logs bypass per policy."
        )
        state["officer_heartbeat_bpm"] = _coerce_int_optional(raw.get("bpm"))
        hs = raw.get("heartbeat_status")
        if hs in ("normal", "elevated", "no_signal", "flat_line"):
            state["officer_heartbeat_status"] = hs  # type: ignore[assignment]
        else:
            hb = str(raw.get("heartbeat_status") or "").lower()
            state["officer_heartbeat_status"] = "no_signal" if hb == "no_signal" else "flat_line"  # type: ignore[assignment]
        oid = raw.get("officer_id") or raw.get("user_id")
        state["officer_id_from_watch"] = str(oid).strip() if oid else None
        z = raw.get("officer_last_seen_zone") or raw.get("location")
        state["officer_last_seen_zone"] = str(z).strip() if z else None
        state["confidence_score"] = float(raw.get("confidence_score") or 1.0)
        user_id = raw.get("user_id") or raw.get("officer_id")
        await _supervisor_load_auth(state, raw, user_id)
        await _supervisor_persist_incident(state, raw)
        state["updated_at"] = datetime.now(UTC).isoformat()
        return state

    # 0b) Officer distress (sustained elevated BPM): high priority, still uses logs path unless extended later
    if hint == "officer_distress":
        state["incident_type"] = "assault"
        state["priority"] = "high"
        state["classification_reasoning"] = (
            "Wearable sustained elevated heart rate — treating as officer_distress / possible medical or stress event."
        )
        state["officer_heartbeat_bpm"] = _coerce_int_optional(raw.get("bpm"))
        state["officer_heartbeat_status"] = "elevated"
        oid = raw.get("officer_id") or raw.get("user_id")
        state["officer_id_from_watch"] = str(oid).strip() if oid else None
        z = raw.get("officer_last_seen_zone") or raw.get("location")
        state["officer_last_seen_zone"] = str(z).strip() if z else None
        state["confidence_score"] = float(raw.get("confidence_score") or 0.9)
        user_id = raw.get("user_id") or raw.get("officer_id")
        await _supervisor_load_auth(state, raw, user_id)
        await _supervisor_persist_incident(state, raw)
        state["updated_at"] = datetime.now(UTC).isoformat()
        return state

    # 1) Certis rank / permissions from Auth MCP
    user_id = raw.get("user_id")
    if state["source_type"] == "watch_heartbeat" and not user_id:
        user_id = raw.get("officer_id")
    await _supervisor_load_auth(state, raw, user_id)

    # 2) Classification prompt
    incident_hint = raw.get("incident_type_hint")
    evidence = raw.get("evidence_refs") or state.get("evidence_refs") or []
    priority_hint = _certis_priority_hint(state)
    source_label = raw.get("source_label")
    prompt = (
        "You are the incident supervisor agent.\n"
        "Classify the incident type and priority.\n"
        "A Certis priority hint is given for alignment with standard taskings; "
        "you may override it if the evidence and context justify a different priority — explain in classification_reasoning.\n\n"
        f"feed_source: {state['feed_source']}\n"
        f"source_type: {state['source_type']}\n"
        f"source_label: {source_label}\n"
        f"certis_priority_hint: {priority_hint}\n"
        f"location: {raw.get('location')}\n"
        f"timestamp: {raw.get('timestamp')}\n"
        f"incident_type_hint: {incident_hint}\n"
        f"responder_rank: {state.get('responder_rank')}\n"
        f"responder_role_label: {state.get('responder_role_label')}\n"
        f"responder_permissions: {state.get('responder_permissions')}\n"
        f"can_approve_escalation: {state.get('can_approve_escalation')}\n"
        f"can_operate_scc: {state.get('can_operate_scc')}\n"
        f"assigned_zone: {state.get('assigned_zone')}\n"
        f"deployment_type: {state.get('deployment_type')}\n"
        f"confidence_score: {raw.get('confidence_score')}\n"
        f"evidence_refs: {evidence}\n\n"
        f"raw_input: {raw}\n"
    )

    # 4) Model call with structured output
    llm = ChatOllama(
        model=settings.LLM_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
        temperature=0.2,
    ).with_structured_output(_Classification)

    result: _Classification = await llm.ainvoke(prompt)

    # 5) Write classification fields from LLM
    state["incident_type"] = result.incident_type
    state["priority"] = result.priority
    state["classification_reasoning"] = result.classification_reasoning

    # 6) Persist updated classification after LLM
    await _supervisor_persist_incident(state, raw)

    # 7) Return updated state
    state["updated_at"] = datetime.now(UTC).isoformat()
    return state
