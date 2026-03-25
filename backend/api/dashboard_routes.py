"""Dashboard REST API: all output/input data via MCP (no direct DB from the browser)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.config import settings
from backend.mcp.mcp_http import call_mcp_tool
from backend.workflow.kickoff import start_workflow
from backend.workflow.state import create_incident_state

logger = logging.getLogger("security_ai.dashboard")

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _mcp_output_url() -> str:
    return f"http://127.0.0.1:{settings.MCP_OUTPUT_DB_PORT}"


def _mcp_input_url() -> str:
    return f"http://127.0.0.1:{settings.MCP_INPUT_DB_PORT}"


async def _out_tool(name: str, arguments: dict) -> dict:
    return await call_mcp_tool(_mcp_output_url(), name, arguments)


async def _in_tool(name: str, arguments: dict) -> dict:
    return await call_mcp_tool(_mcp_input_url(), name, arguments)


# --- Ground officer ---


@router.get("/ground/incidents")
async def ground_incidents(
    rank: str = Query(..., description="Certis rank e.g. SO"),
    zone: str | None = Query(None),
) -> dict:
    try:
        return await _out_tool(
            "list_ground_officer_active_incidents",
            {"officer_rank": rank, "zone": zone or None, "limit": 50},
        )
    except Exception as e:
        logger.exception("ground incidents")
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/ground/dispatches")
async def ground_dispatches(rank: str = Query(...)) -> dict:
    try:
        return await _out_tool(
            "list_unacknowledged_dispatches_for_role",
            {"officer_rank": rank, "limit": 50},
        )
    except Exception as e:
        logger.exception("ground dispatches")
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post("/ground/dispatches/{notification_id}/acknowledge")
async def acknowledge_dispatch_notification(notification_id: str) -> dict:
    try:
        return await _out_tool("acknowledge_dispatch", {"notification_id": notification_id})
    except Exception as e:
        logger.exception("ack dispatch")
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/ground/today-task")
async def ground_today_task(
    rank: str = Query(...),
    zone: str | None = Query(None),
    task_date: str | None = Query(None, description="YYYY-MM-DD, default UTC today"),
) -> dict:
    try:
        return await _out_tool(
            "get_officer_daily_task",
            {"officer_rank": rank, "zone": zone or None, "task_date": task_date},
        )
    except Exception as e:
        logger.exception("today task")
        raise HTTPException(status_code=502, detail=str(e)) from e


class ManualTriggerBody(BaseModel):
    location: str = Field(..., min_length=1)
    incident_type_hint: str | None = None
    description: str | None = None
    user_id: str | None = None


@router.post("/ground/manual-trigger")
async def dashboard_manual_trigger(body: ManualTriggerBody, background_tasks: BackgroundTasks) -> dict:
    payload = {
        "source_id": f"manual-{uuid4()}",
        "feed_source": "live",
        "source_type": "manual_trigger",
        "incident_type_hint": body.incident_type_hint,
        "location": body.location,
        "timestamp": datetime.now(UTC).isoformat(),
        "evidence_refs": [],
        "confidence_score": 1.0,
        "user_id": body.user_id,
        "source_label": (body.description or "").strip() or "manual_field_report",
        "task_mode": "non_routine",
    }
    state = create_incident_state(payload)
    incident_id = state["incident_id"]
    background_tasks.add_task(start_workflow, state)
    return {
        "incident_id": incident_id,
        "status": "processing",
        "message": "Manual trigger accepted; workflow started.",
    }


# --- Command centre ---


@router.get("/cc/incidents")
async def cc_open_incidents() -> dict:
    try:
        return await _out_tool("list_cc_open_incidents_sorted", {"limit": 200})
    except Exception as e:
        logger.exception("cc incidents")
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/cc/review-queue")
async def cc_review_queue() -> dict:
    try:
        return await _out_tool("list_human_review_queue", {"limit": 100})
    except Exception as e:
        logger.exception("review queue")
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/cc/dispatch-panel")
async def cc_dispatch_panel() -> dict:
    try:
        return await _out_tool("list_dispatch_panel_rows", {"limit": 100})
    except Exception as e:
        logger.exception("dispatch panel")
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/cc/zones")
async def cc_zone_counts() -> dict:
    try:
        return await _out_tool("list_zone_open_counts", {})
    except Exception as e:
        logger.exception("zone counts")
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/cc/reports")
async def cc_reports() -> dict:
    try:
        return await _out_tool("list_incident_reports_rows", {"limit": 100})
    except Exception as e:
        logger.exception("reports list")
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post("/cc/reports/{report_id}/submit")
async def cc_submit_report(report_id: str) -> dict:
    try:
        return await _out_tool("submit_incident_report", {"report_id": report_id})
    except Exception as e:
        logger.exception("submit report")
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/cc/incidents/{incident_id}/sop-chunks")
async def cc_sop_chunks(incident_id: str) -> dict:
    try:
        return await _in_tool("get_agent_state", {"incident_id": incident_id})
    except Exception as e:
        logger.exception("sop chunks")
        raise HTTPException(status_code=502, detail=str(e)) from e


# --- Supervisor (SS / SSS / CSO) ---


@router.get("/supervisor/audit/{incident_id}")
async def supervisor_audit(incident_id: str) -> dict:
    try:
        return await _out_tool("list_audit_log_for_incident", {"incident_id": incident_id})
    except Exception as e:
        logger.exception("audit")
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/supervisor/risk-points")
async def supervisor_risk_points() -> dict:
    try:
        return await _out_tool("list_risk_points_last_24h", {})
    except Exception as e:
        logger.exception("risk points")
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/supervisor/shift-export")
async def supervisor_shift_export(
    zone: str = Query("", description="Filter by assigned_zone; empty = all zones"),
    shift_start: str = Query(..., description="ISO 8601 start"),
    shift_end: str = Query(..., description="ISO 8601 end"),
) -> Response:
    try:
        data = await _out_tool(
            "list_zone_shift_incidents",
            {"zone": zone, "shift_start": shift_start, "shift_end": shift_end},
        )
        body = json.dumps(data, indent=2, default=str)
        filename = f"shift-export-{zone or 'all'}-{shift_start[:10]}.json"
        return Response(
            content=body,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        logger.exception("shift export")
        raise HTTPException(status_code=502, detail=str(e)) from e
