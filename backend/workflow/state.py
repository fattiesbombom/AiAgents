"""Shared incident state schema passed between LangGraph nodes.

This module defines the central IncidentState TypedDict and a factory function
to initialize a new incident state from a raw trigger payload.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, TypedDict
from uuid import uuid4


FeedSource = Literal["live", "remote"]
SourceType = Literal["video", "non_video"]

IncidentType = Literal["intrusion", "fire", "assault", "tailgating", "other"]
Priority = Literal["critical", "high", "medium", "low"]

HumanReviewStatus = Literal["pending", "approved", "rejected"]
PoliceNotificationType = Literal["immediate", "escalation"]

IncidentStatus = Literal["open", "escalated", "closed", "rejected"]


class IncidentState(TypedDict):
    # Source and routing
    incident_id: str
    feed_source: FeedSource
    source_type: SourceType
    raw_input: dict

    # Classification (written by Supervisor)
    incident_type: IncidentType
    priority: Priority
    responder_role: str | None
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

    # Human review (written by workflow routing logic)
    human_review_required: bool
    human_review_status: HumanReviewStatus | None
    human_reviewer_id: str | None

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


def create_incident_state(trigger_event: dict) -> IncidentState:
    """Create a new IncidentState from a raw trigger payload.

    Notes:
    - Initializes all nullable fields to None.
    - Uses conservative defaults for fields written by later nodes.
    """

    feed_source: FeedSource = trigger_event.get("feed_source", "remote")
    if feed_source not in ("live", "remote"):
        feed_source = "remote"

    source_type: SourceType = trigger_event.get("source_type", "non_video")
    if source_type not in ("video", "non_video"):
        source_type = "non_video"

    created_at = _now_iso()

    return IncidentState(
        # Source and routing
        incident_id=str(uuid4()),
        feed_source=feed_source,
        source_type=source_type,
        raw_input=trigger_event,

        # Classification (Supervisor)
        incident_type="other",
        priority="low",
        responder_role=None,
        classification_reasoning="",

        # Confirmation (Vision / Logs)
        vision_confirmed=None,
        logs_confirmed=None,
        confirmed=False,
        confidence_score=0.0,
        evidence_refs=[],

        # SOP retrieval
        incident_query_embedding=None,
        sop_chunks=[],
        sop_retrieval_reasoning="",

        # Risk and decision
        risk_score=0.0,
        recommended_action="",
        recommended_action_reasoning="",

        # Human review
        human_review_required=(feed_source == "remote"),
        human_review_status="pending" if feed_source == "remote" else None,
        human_reviewer_id=None,

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
