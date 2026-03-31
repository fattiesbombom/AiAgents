"""Thin FastAPI trigger receiver.

Receives trigger events from the perception layer and hands them to the workflow.
No business logic should live in this module.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.api.dashboard_routes import router as dashboard_router
from backend.config import settings
from backend.mcp.mcp_http import call_mcp_tool
from backend.workflow.kickoff import start_workflow
from backend.workflow.state import SourceType, TaskMode, create_incident_state


logger = logging.getLogger("security_ai.api")


def _configure_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _cors_origins() -> list[str]:
    raw = settings.ALLOWED_ORIGINS or "http://localhost:5173"
    return [s.strip() for s in raw.split(",") if s.strip()]


class TriggerEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    source_id: str
    feed_source: Literal["live", "remote"]
    source_type: SourceType
    incident_type_hint: str | None = None
    location: str
    timestamp: str
    evidence_refs: list[str] = Field(default_factory=list)
    confidence_score: float = Field(ge=0.0, le=1.0)
    user_id: str | None = None
    source_label: str | None = None
    task_mode: TaskMode = "non_routine"
    routine_task_type: str | None = None
    scheduled_task_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_source_type(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        fs = data.get("feed_source")
        st = data.get("source_type")
        if st == "video":
            data["source_type"] = "body_worn" if fs == "live" else "cctv"
        elif st == "non_video":
            data["source_type"] = "cctv"
        elif st is None or st == "":
            data["source_type"] = "body_worn" if fs == "live" else "cctv"
        return data


class TriggerResponse(BaseModel):
    incident_id: str
    status: Literal["received", "processing"]
    message: str


CertisRank = Literal["SO", "SSO", "SS", "SSS", "CSO"]


class HumanReviewRequest(BaseModel):
    human_review_status: Literal["approved", "rejected"]
    human_reviewer_id: str | None = None
    human_reviewer_rank: CertisRank | None = None


class DispatchRequest(BaseModel):
    officer_id: str
    instruction_override: str | None = None
    dispatched_by: str


def _mcp_output_url() -> str:
    return settings.mcp_output_http_url()


_configure_logging()

app = FastAPI(title="Security AI Trigger Receiver")
app.include_router(dashboard_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/trigger", response_model=TriggerResponse)
async def trigger(event: TriggerEvent, background_tasks: BackgroundTasks) -> TriggerResponse:
    # Validate + normalize into shared workflow state
    state = create_incident_state(event.model_dump())
    incident_id = state["incident_id"]

    logger.info(
        "trigger_received incident_id=%s feed_source=%s source_type=%s source_id=%s",
        incident_id,
        state["feed_source"],
        state["source_type"],
        event.source_id,
    )

    # Launch workflow without awaiting
    background_tasks.add_task(start_workflow, state)

    return TriggerResponse(
        incident_id=incident_id,
        status="processing",
        message="Trigger received; workflow processing started.",
    )


@app.get("/incident/{incident_id}")
async def get_incident(incident_id: str) -> dict:
    try:
        server_url = _mcp_output_url()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    try:
        return await call_mcp_tool(server_url, "get_incident", {"incident_id": incident_id})
    except Exception as e:
        logger.exception("Failed to fetch incident via MCP")
        raise HTTPException(status_code=502, detail=f"Failed to fetch incident: {e}") from e


@app.post("/incident/{incident_id}/review")
async def submit_human_review(incident_id: str, body: HumanReviewRequest) -> dict:
    """External endpoint to resume a workflow paused for human review.

    For now this updates the output DB incident record and returns the latest view.
    Full workflow resumption requires a durable checkpointer; this endpoint is the
    integration point for that next step.

    Escalation approval is only persisted when ``can_approve_escalation`` is true on
    the incident and the reviewer's rank is not SO/SSO.
    """
    server_url = _mcp_output_url()
    try:
        current = await call_mcp_tool(server_url, "get_incident", {"incident_id": incident_id})
        if not current or not current.get("id"):
            raise HTTPException(status_code=404, detail="Incident not found")

        effective = body.human_review_status
        audit_detail: dict = {
            "requested_status": body.human_review_status,
            "human_reviewer_rank": body.human_reviewer_rank,
        }

        if body.human_review_status == "approved":
            if body.human_reviewer_rank is None:
                raise HTTPException(
                    status_code=400,
                    detail="human_reviewer_rank is required when approving",
                )
            if not current.get("can_approve_escalation"):
                effective = "rejected"
                audit_detail["rejection_reason"] = "human_review_denied_no_escalation_authority"
            elif body.human_reviewer_rank in ("SO", "SSO"):
                effective = "rejected"
                audit_detail["rejection_reason"] = "human_review_denied_insufficient_reviewer_rank"

        updates = {
            "human_review_status": effective,
            "human_reviewer_rank": body.human_reviewer_rank,
        }
        await call_mcp_tool(
            server_url,
            "update_incident",
            {"incident_id": incident_id, "updates": updates},
        )
        await call_mcp_tool(
            server_url,
            "write_audit_log",
            {
                "incident_id": incident_id,
                "actor": body.human_reviewer_id or "human_reviewer",
                "action": "human_review_submitted",
                "detail": {**audit_detail, "effective_status": effective},
            },
        )
        return await call_mcp_tool(server_url, "get_incident", {"incident_id": incident_id})
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to submit human review via MCP")
        raise HTTPException(status_code=502, detail=f"Failed to submit human review: {e}") from e


@app.post("/incident/{incident_id}/dispatch")
async def confirm_dispatch(incident_id: str, body: DispatchRequest) -> dict:
    """Confirm that a dispatch instruction was sent to a ground officer (Command Centre workflow)."""
    server_url = _mcp_output_url()
    try:
        current = await call_mcp_tool(server_url, "get_incident", {"incident_id": incident_id})
        if not current or not current.get("id"):
            raise HTTPException(status_code=404, detail="Incident not found")

        now = datetime.now(UTC)
        updates: dict = {"dispatch_sent_at": now}
        if body.instruction_override is not None:
            updates["dispatch_instruction"] = body.instruction_override

        await call_mcp_tool(
            server_url,
            "update_incident",
            {"incident_id": incident_id, "updates": updates},
        )
        await call_mcp_tool(
            server_url,
            "write_audit_log",
            {
                "incident_id": incident_id,
                "actor": body.dispatched_by,
                "action": "dispatch_confirmed",
                "detail": {
                    "officer_id": body.officer_id,
                    "instruction_override": body.instruction_override,
                },
            },
        )
        return {
            "incident_id": incident_id,
            "dispatch_sent_at": now.isoformat(),
            "status": "dispatched",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to confirm dispatch via MCP")
        raise HTTPException(status_code=502, detail=f"Failed to confirm dispatch: {e}") from e
