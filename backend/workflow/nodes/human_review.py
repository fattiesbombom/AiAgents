"""Human-in-the-loop review node.

This node is used with LangGraph interrupt to pause until an external system
updates human_review_status in the incident state.
"""

from __future__ import annotations

from langgraph.types import interrupt

from backend.workflow.state import IncidentState


async def human_review(state: IncidentState) -> IncidentState:
    status = state.get("human_review_status")
    if status not in ("approved", "rejected"):
        interrupt({"reason": "human_review_required", "incident_id": state["incident_id"]})
    return state
