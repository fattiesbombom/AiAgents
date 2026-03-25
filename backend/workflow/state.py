"""Shared incident state schema passed between LangGraph nodes.

This module defines the shared IncidentState TypedDict and a factory function
to initialize a new incident state from a raw trigger payload.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, TypedDict
from uuid import uuid4


FeedSource = Literal["live", "remote"]
SourceType = Literal[
    "body_worn",
    "cctv",
    "fire_alarm",
    "intruder_alarm",
    "lift_alarm",
    "door_alarm",
    "mop_report",
    "c2_system",
    "nursing_intercom",
    "carpark_intercom",
    "manual_trigger",
    "watch_heartbeat",
]

IncidentType = Literal["intrusion", "fire", "assault", "tailgating", "other", "officer_down"]
Priority = Literal["critical", "high", "medium", "low"]

HumanReviewStatus = Literal["pending", "approved", "rejected"]
PoliceNotificationType = Literal["immediate", "escalation"]

IncidentStatus = Literal["open", "escalated", "closed", "rejected"]

CertisRank = Literal["SO", "SSO", "SS", "SSS", "CSO"]
DeploymentType = Literal["ground", "command_centre"]
StaffRoleType = Literal["security_officer", "auxiliary_police", "enforcement_officer"]

TaskMode = Literal["routine", "non_routine"]
RoutineTaskType = Literal[
    "access_control",
    "patrol",
    "cctv_monitoring",
    "virtual_patrol",
    "report_generation",
]

HeartbeatStatus = Literal["normal", "elevated", "no_signal", "flat_line"]

ALL_SOURCE_TYPES: frozenset[str] = frozenset(
    {
        "body_worn",
        "cctv",
        "fire_alarm",
        "intruder_alarm",
        "lift_alarm",
        "door_alarm",
        "mop_report",
        "c2_system",
        "nursing_intercom",
        "carpark_intercom",
        "manual_trigger",
        "watch_heartbeat",
    }
)
REMOTE_SOURCE_TYPES: frozenset[str] = ALL_SOURCE_TYPES - frozenset({"body_worn"})

# Vision / YOLO path (live body cam or CCTV stream with frames).
VIDEO_ROUTE_SOURCE_TYPES: frozenset[str] = frozenset({"body_worn", "cctv"})

VALID_ROUTINE_TASK_TYPES: frozenset[str] = frozenset(
    {"access_control", "patrol", "cctv_monitoring", "virtual_patrol", "report_generation"}
)


def _normalize_source_for_feed(feed_source: FeedSource, source_type_raw: object) -> SourceType:
    """Apply Certis feed rules: live → body_worn (except explicit manual_trigger / watch_heartbeat); remote → non–body_worn types."""
    st = str(source_type_raw).strip() if source_type_raw is not None else ""
    if st not in ALL_SOURCE_TYPES:
        st = ""
    if feed_source == "live":
        if st == "manual_trigger":
            return "manual_trigger"
        if st == "watch_heartbeat":
            return "watch_heartbeat"
        return "body_worn"
    if st == "body_worn" or st not in REMOTE_SOURCE_TYPES or st == "":
        return "cctv"
    return st  # type: ignore[return-value]


class IncidentState(TypedDict):
    # Source and routing
    incident_id: str
    feed_source: FeedSource
    source_type: SourceType
    raw_input: dict

    # Wearable heartbeat (watch feed; populated from trigger raw_input)
    officer_heartbeat_bpm: int | None
    officer_heartbeat_status: HeartbeatStatus | None
    officer_id_from_watch: str | None
    officer_last_seen_zone: str | None

    # Routine vs incident workflow
    task_mode: TaskMode
    routine_task_type: RoutineTaskType | None
    routine_task_completed: bool
    routine_task_notes: str | None

    # Classification (written by Supervisor)
    incident_type: IncidentType
    priority: Priority
    responder_rank: CertisRank | None
    role_type: StaffRoleType | None
    todays_assignment: Literal["ground", "command_centre"] | None
    responder_role_label: str | None
    responder_permissions: list[str] | None
    can_approve_escalation: bool
    can_operate_scc: bool
    assigned_zone: str | None
    deployment_type: DeploymentType | None
    classification_reasoning: str

    # Confirmation (written by Vision and Logs agents)
    vision_confirmed: bool | None
    logs_confirmed: bool | None
    confirmed: bool
    confidence_score: float
    evidence_refs: list[str]

    # SOP retrieval (written by SOP retrieval node)
    incident_query_embedding: list[float] | None
    sop_chunks: list[dict]
    sop_retrieval_reasoning: str

    # Risk and decision (written by Risk/Decision node)
    risk_score: float
    recommended_action: str
    recommended_action_reasoning: str

    # Command Centre (cc_officer node + dispatch API)
    dispatch_instruction: str | None
    dispatched_officer_role: str | None
    dispatch_sent_at: str | None
    incident_report_generated: bool
    incident_report_path: str | None

    # Human review (written by workflow routing logic / API)
    human_review_required: bool
    human_review_status: HumanReviewStatus | None
    human_reviewer_id: str | None
    human_reviewer_rank: CertisRank | None

    # Police notification
    police_notified: bool
    police_notification_type: PoliceNotificationType | None
    police_notified_at: str | None

    # Workflow status
    incident_status: IncidentStatus
    created_at: str
    updated_at: str
    workflow_errors: list[str]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_bpm(raw: dict) -> int | None:
    if "bpm" in raw and raw["bpm"] is not None:
        try:
            return int(raw["bpm"])
        except (TypeError, ValueError):
            pass
    for key in ("heart_rate", "hr", "heartbeat"):
        if key in raw and raw[key] is not None:
            try:
                return int(raw[key])
            except (TypeError, ValueError):
                pass
    return None


def _parse_heartbeat_status(raw: dict) -> HeartbeatStatus | None:
    s = raw.get("heartbeat_status")
    if s in ("normal", "elevated", "no_signal", "flat_line"):
        return s  # type: ignore[return-value]
    return None


def create_incident_state(trigger_event: dict) -> IncidentState:
    """Create a new IncidentState from a raw trigger payload.

    Notes:
    - Initializes all nullable fields to None.
    - Uses conservative defaults for fields written by later nodes.
    - ``feed_source`` / ``source_type`` are normalised per Certis rules (live ↔ body_worn).
    """

    feed_source: FeedSource = trigger_event.get("feed_source", "remote")
    if feed_source not in ("live", "remote"):
        feed_source = "remote"

    default_st: SourceType = "body_worn" if feed_source == "live" else "cctv"
    source_type = _normalize_source_for_feed(feed_source, trigger_event.get("source_type", default_st))

    tm_raw = trigger_event.get("task_mode", "non_routine")
    task_mode: TaskMode = tm_raw if tm_raw in ("routine", "non_routine") else "non_routine"
    rt_raw = trigger_event.get("routine_task_type")
    routine_task_type: RoutineTaskType | None = (
        rt_raw if isinstance(rt_raw, str) and rt_raw in VALID_ROUTINE_TASK_TYPES else None
    )

    created_at = _now_iso()

    oid = trigger_event.get("officer_id") or trigger_event.get("user_id")
    oid_str = str(oid).strip() if oid else None

    zone = trigger_event.get("officer_last_seen_zone") or trigger_event.get("location")
    zone_str = str(zone).strip() if zone else None

    bpm = _parse_bpm(trigger_event)
    hb_status = _parse_heartbeat_status(trigger_event)

    ev = trigger_event.get("evidence_refs")
    evidence_refs: list[str] = list(ev) if isinstance(ev, list) else []

    return IncidentState(
        # Source and routing
        incident_id=str(uuid4()),
        feed_source=feed_source,
        source_type=source_type,
        raw_input=trigger_event,
        officer_heartbeat_bpm=bpm,
        officer_heartbeat_status=hb_status,
        officer_id_from_watch=oid_str,
        officer_last_seen_zone=zone_str,
        # Routine
        task_mode=task_mode,
        routine_task_type=routine_task_type,
        routine_task_completed=False,
        routine_task_notes=None,
        # Classification (Supervisor)
        incident_type="other",
        priority="low",
        responder_rank=None,
        role_type=None,
        todays_assignment=None,
        responder_role_label=None,
        responder_permissions=None,
        can_approve_escalation=False,
        can_operate_scc=False,
        assigned_zone=None,
        deployment_type=None,
        classification_reasoning="",
        # Confirmation (Vision / Logs)
        vision_confirmed=None,
        logs_confirmed=None,
        confirmed=False,
        confidence_score=float(trigger_event.get("confidence_score") or 0.0),
        evidence_refs=evidence_refs,
        # SOP retrieval
        incident_query_embedding=None,
        sop_chunks=[],
        sop_retrieval_reasoning="",
        # Risk and decision
        risk_score=0.0,
        recommended_action="",
        recommended_action_reasoning="",
        # Command Centre
        dispatch_instruction=None,
        dispatched_officer_role=None,
        dispatch_sent_at=None,
        incident_report_generated=False,
        incident_report_path=None,
        # Human review
        human_review_required=(feed_source == "remote"),
        human_review_status="pending" if feed_source == "remote" else None,
        human_reviewer_id=None,
        human_reviewer_rank=None,
        # Police notification
        police_notified=False,
        police_notification_type=None,
        police_notified_at=None,
        # Workflow status
        incident_status="open",
        created_at=created_at,
        updated_at=created_at,
        workflow_errors=[],
    )
