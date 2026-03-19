"""Thin FastAPI trigger receiver.

Receives trigger events from the perception layer and hands them to the workflow.
No business logic should live in this module.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.config import settings
from backend.workflow.state import create_incident_state


logger = logging.getLogger("security_ai.api")


def _configure_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _cors_origins() -> list[str]:
    return settings.ALLOWED_ORIGINS


class TriggerEvent(BaseModel):
    source_id: str
    feed_source: Literal["live", "remote"]
    source_type: Literal["video", "non_video"]
    incident_type_hint: str | None = None
    location: str
    timestamp: str
    evidence_refs: list[str] = Field(default_factory=list)
    confidence_score: float = Field(ge=0.0, le=1.0)


class TriggerResponse(BaseModel):
    incident_id: str
    status: Literal["received", "processing"]
    message: str


class HumanReviewRequest(BaseModel):
    human_review_status: Literal["approved", "rejected"]
    human_reviewer_id: str | None = None


def _mcp_output_url() -> str:
    # In this codebase, MCP servers are local processes; server URL is constructed
    # from the configured port.
    return f"http://127.0.0.1:{settings.MCP_OUTPUT_DB_PORT}"


async def _run_workflow_in_background(state: dict) -> None:
    """Kick off the LangGraph workflow execution.

    This intentionally defers to the workflow module; trigger receiver stays thin.
    """
    try:
        from backend.workflow import graph as workflow_graph  # local import to keep startup cheap

        runner = getattr(workflow_graph, "run_workflow", None)
        if runner is None:
            logger.warning("workflow runner not implemented: backend.workflow.graph.run_workflow missing")
            return

        result = runner(state)
        if asyncio.iscoroutine(result):
            await result
    except Exception:
        logger.exception("Failed to launch workflow")


def _schedule_workflow(state: dict) -> None:
    asyncio.create_task(_run_workflow_in_background(state))


async def _mcp_call_tool(server_url: str, tool_name: str, arguments: dict) -> dict:
    """Call an MCP tool on a remote server using streamable-http transport."""
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            res = await session.call_tool(tool_name, arguments)
            # FastMCP typically returns JSON-serializable dict content.
            if isinstance(res, dict):
                return res
            # Some MCP SDKs wrap results; best-effort extraction.
            return {"result": res}


_configure_logging()

app = FastAPI(title="Security AI Trigger Receiver")
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
    background_tasks.add_task(_schedule_workflow, state)

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
        return await _mcp_call_tool(server_url, "get_incident", {"incident_id": incident_id})
    except Exception as e:
        logger.exception("Failed to fetch incident via MCP")
        raise HTTPException(status_code=502, detail=f"Failed to fetch incident: {e}") from e


@app.post("/incident/{incident_id}/review")
async def submit_human_review(incident_id: str, body: HumanReviewRequest) -> dict:
    """External endpoint to resume a workflow paused for human review.

    For now this updates the output DB incident record and returns the latest view.
    Full workflow resumption requires a durable checkpointer; this endpoint is the
    integration point for that next step.
    """
    server_url = _mcp_output_url()
    try:
        await _mcp_call_tool(
            server_url,
            "update_incident",
            {
                "incident_id": incident_id,
                "updates": {"human_review_status": body.human_review_status},
            },
        )
        await _mcp_call_tool(
            server_url,
            "write_audit_log",
            {
                "incident_id": incident_id,
                "actor": body.human_reviewer_id or "human_reviewer",
                "action": "human_review_submitted",
                "detail": {"status": body.human_review_status},
            },
        )
        return await _mcp_call_tool(server_url, "get_incident", {"incident_id": incident_id})
    except Exception as e:
        logger.exception("Failed to submit human review via MCP")
        raise HTTPException(status_code=502, detail=f"Failed to submit human review: {e}") from e
