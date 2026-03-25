"""Human-in-the-loop review node.

This node is used with LangGraph interrupt to pause until an external system
updates human_review_status in the incident state.
"""

from __future__ import annotations

from langgraph.types import interrupt

from backend.workflow.state import IncidentState


async def human_review(state: IncidentState) -> IncidentState:
    status = state.get("human_review_status")

    if status == "approved":
        if not state.get("can_approve_escalation"):
            state["human_review_status"] = "rejected"
            state["workflow_errors"].append("human_review_denied_no_escalation_authority")
            status = "rejected"
        else:
            rr = state.get("human_reviewer_rank")
            if rr is None:
                state["human_review_status"] = "rejected"
                state["workflow_errors"].append("human_review_denied_missing_reviewer_rank")
                status = "rejected"
            elif rr in ("SO", "SSO"):
                state["human_review_status"] = "rejected"
                state["workflow_errors"].append("human_review_denied_insufficient_reviewer_rank")
                status = "rejected"

    if status not in ("approved", "rejected"):
        interrupt({"reason": "human_review_required", "incident_id": state["incident_id"]})
    return state
