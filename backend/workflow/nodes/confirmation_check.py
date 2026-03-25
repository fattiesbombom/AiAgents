"""Workflow node that determines overall confirmation status."""

from __future__ import annotations

from backend.workflow.state import VIDEO_ROUTE_SOURCE_TYPES, IncidentState


async def confirmation_check(state: IncidentState) -> IncidentState:
    source_type = state["source_type"]

    confirmed = False
    if source_type in VIDEO_ROUTE_SOURCE_TYPES:
        confirmed = state.get("vision_confirmed") is True
    else:
        confirmed = state.get("logs_confirmed") is True

    state["confirmed"] = bool(confirmed)
    return state
