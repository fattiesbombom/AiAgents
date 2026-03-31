"""MCP server for Output DB writes/reads (dashboard-facing DB).

Agents must never connect to the DB directly; they call these MCP tools.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import asyncpg
from mcp.server.fastmcp import FastMCP

from backend.config import settings

mcp = FastMCP(
    "output-db",
    host="127.0.0.1",
    port=settings.MCP_OUTPUT_DB_PORT,
    streamable_http_path="/",
)

_pool: asyncpg.Pool | None = None


def _output_db_url() -> str:
    # Use pydantic-loaded settings (.env); os.getenv is often unset in child processes.
    url = (settings.OUTPUT_DB_URL or "").strip()
    if not url:
        raise RuntimeError("Missing required env var OUTPUT_DB_URL (set in .env or environment)")
    return url


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn=_output_db_url(), min_size=1, max_size=10)
    return _pool


def _row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    return dict(row)


def _now() -> datetime:
    return datetime.now(UTC)


_INCIDENT_FIELDS = {
    "id",
    "incident_type",
    "priority",
    "feed_source",
    "source_type",
    "location",
    "confirmed",
    "risk_score",
    "recommended_action",
    "incident_status",
    "police_notified",
    "police_notification_type",
    "human_review_status",
    "human_reviewer_rank",
    "responder_rank",
    "responder_role_label",
    "responder_permissions",
    "can_approve_escalation",
    "can_operate_scc",
    "assigned_zone",
    "deployment_type",
    "dispatch_instruction",
    "dispatched_officer_role",
    "dispatch_sent_at",
    "incident_report_generated",
    "incident_report_path",
    "created_at",
    "updated_at",
}


@mcp.tool()
async def create_incident(incident: dict) -> dict:
    """Insert a new incident record and return it."""
    if not isinstance(incident, dict):
        raise ValueError("incident must be a dict")

    cols = [c for c in incident.keys() if c in _INCIDENT_FIELDS]
    if "id" not in cols:
        raise ValueError("incident must include 'id' (UUID string)")

    # Ensure timestamps exist if not provided.
    now = _now()
    if "created_at" not in incident:
        incident["created_at"] = now
        if "created_at" not in cols:
            cols.append("created_at")
    if "updated_at" not in incident:
        incident["updated_at"] = now
        if "updated_at" not in cols:
            cols.append("updated_at")

    placeholders = []
    values: list[Any] = []
    for i, c in enumerate(cols, start=1):
        if c == "id":
            placeholders.append(f"${i}::uuid")
        elif c in ("created_at", "updated_at", "dispatch_sent_at"):
            placeholders.append(f"${i}::timestamptz")
        elif c == "responder_permissions":
            placeholders.append(f"${i}::jsonb")
        else:
            placeholders.append(f"${i}")
        values.append(incident[c])

    sql = f"""
      INSERT INTO incidents ({", ".join(cols)})
      VALUES ({", ".join(placeholders)})
      RETURNING *
    """

    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, *values)
    return _row_to_dict(row) if row else {}


@mcp.tool()
async def update_incident(incident_id: str, updates: dict) -> dict:
    """Update specified fields on an incident record."""
    if not isinstance(updates, dict):
        raise ValueError("updates must be a dict")

    allowed = [k for k in updates.keys() if k in _INCIDENT_FIELDS and k != "id"]
    # Always bump updated_at unless explicitly provided
    if "updated_at" not in updates:
        updates["updated_at"] = _now()
        allowed.append("updated_at")

    if not allowed:
        return {"ok": True, "incident_id": incident_id, "updated": 0}

    sets = []
    values: list[Any] = []
    idx = 1
    for k in allowed:
        if k in ("created_at", "updated_at", "dispatch_sent_at"):
            sets.append(f"{k} = ${idx}::timestamptz")
            values.append(updates[k])
        elif k == "responder_permissions":
            sets.append(f"{k} = ${idx}::jsonb")
            values.append(updates[k])
        else:
            sets.append(f"{k} = ${idx}")
            values.append(updates[k])
        idx += 1

    values.append(incident_id)
    sql = f"""
      UPDATE incidents
      SET {", ".join(sets)}
      WHERE id = ${idx}::uuid
      RETURNING *
    """

    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, *values)
    return _row_to_dict(row) if row else {}


@mcp.tool()
async def add_evidence(
    incident_id: str, evidence_type: str, file_path: str, description: str
) -> dict:
    """Insert evidence for an incident."""
    pool = await _get_pool()
    now = _now()
    evidence_id = str(uuid4())
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO incident_evidence (id, incident_id, evidence_type, file_path, description, created_at)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6)
            RETURNING *
            """,
            evidence_id,
            incident_id,
            evidence_type,
            file_path,
            description,
            now,
        )
    return _row_to_dict(row) if row else {}


@mcp.tool()
async def add_timeline_entry(incident_id: str, node_name: str, summary: str) -> dict:
    """Insert a timeline entry for an incident."""
    pool = await _get_pool()
    now = _now()
    entry_id = str(uuid4())
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO incident_timeline (id, incident_id, node_name, summary, created_at)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5)
            RETURNING *
            """,
            entry_id,
            incident_id,
            node_name,
            summary,
            now,
        )
    return _row_to_dict(row) if row else {}


@mcp.tool()
async def write_audit_log(
    incident_id: str, actor: str, action: str, detail: dict
) -> dict:
    """Insert an audit log entry."""
    pool = await _get_pool()
    now = _now()
    audit_id = str(uuid4())
    payload = json.dumps(detail)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO audit_log (id, incident_id, actor, action, detail, created_at)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5::jsonb, $6)
            RETURNING *
            """,
            audit_id,
            incident_id,
            actor,
            action,
            payload,
            now,
        )
    return _row_to_dict(row) if row else {}


@mcp.tool()
async def list_open_incidents(limit: int = 200) -> dict:
    """Return open incidents (incident_status = 'open') for shift / routine reporting."""
    if limit <= 0:
        limit = 200
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, incident_type, priority, location, feed_source, source_type,
                   incident_status, risk_score, created_at, updated_at
            FROM incidents
            WHERE incident_status = 'open'
            ORDER BY updated_at DESC
            LIMIT $1
            """,
            limit,
        )
    return {"open_incidents": [_row_to_dict(r) for r in rows]}


@mcp.tool()
async def create_shift_report(
    summary: str,
    routine_incident_id: str | None = None,
    scheduled_task_id: str | None = None,
) -> dict:
    """Persist a compiled shift summary (e.g. from routine report_generation)."""
    pool = await _get_pool()
    now = _now()
    report_id = str(uuid4())
    async with pool.acquire() as conn:
        if routine_incident_id:
            row = await conn.fetchrow(
                """
                INSERT INTO shift_reports (id, summary, routine_incident_id, scheduled_task_id, created_at)
                VALUES ($1::uuid, $2, $3::uuid, $4, $5)
                RETURNING *
                """,
                report_id,
                summary,
                routine_incident_id,
                scheduled_task_id,
                now,
            )
        else:
            row = await conn.fetchrow(
                """
                INSERT INTO shift_reports (id, summary, routine_incident_id, scheduled_task_id, created_at)
                VALUES ($1::uuid, $2, NULL, $3, $4)
                RETURNING *
                """,
                report_id,
                summary,
                scheduled_task_id,
                now,
            )
    return _row_to_dict(row) if row else {}


@mcp.tool()
async def create_dispatch_notification(
    incident_id: str,
    instruction: str,
    dispatched_officer_role: str | None,
    dispatched_by: str,
) -> dict:
    """Insert a dispatch notification row (Command Centre → ground)."""
    pool = await _get_pool()
    now = _now()
    nid = str(uuid4())
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO dispatch_notifications (
                id, incident_id, instruction, dispatched_officer_role, dispatched_by, sent_at
            )
            VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6)
            RETURNING *
            """,
            nid,
            incident_id,
            instruction,
            dispatched_officer_role,
            dispatched_by,
            now,
        )
    return _row_to_dict(row) if row else {}


@mcp.tool()
async def acknowledge_dispatch(notification_id: str) -> dict:
    """Mark a dispatch notification as acknowledged."""
    pool = await _get_pool()
    now = _now()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE dispatch_notifications
            SET acknowledged = TRUE, acknowledged_at = $2
            WHERE id = $1::uuid
            RETURNING *
            """,
            notification_id,
            now,
        )
    return _row_to_dict(row) if row else {}


@mcp.tool()
async def create_incident_report(
    incident_id: str,
    report_text: str,
    report_type: str,
    generated_by: str,
) -> dict:
    """Insert an AI- or user-generated incident report narrative."""
    pool = await _get_pool()
    now = _now()
    rid = str(uuid4())
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO incident_reports (
                id, incident_id, report_text, report_type, generated_by, generated_at
            )
            VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6)
            RETURNING *
            """,
            rid,
            incident_id,
            report_text,
            report_type,
            generated_by,
            now,
        )
    return _row_to_dict(row) if row else {}


@mcp.tool()
async def submit_incident_report(report_id: str) -> dict:
    """Mark an incident report as formally submitted."""
    pool = await _get_pool()
    now = _now()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE incident_reports
            SET submitted = TRUE, submitted_at = $2
            WHERE id = $1::uuid
            RETURNING *
            """,
            report_id,
            now,
        )
    return _row_to_dict(row) if row else {}


@mcp.tool()
async def get_shift_summary(
    officer_id: str,
    shift_start: str,
    shift_end: str,
) -> dict:
    """Return incidents and incident_reports overlapping the shift window (ISO 8601 bounds)."""
    pool = await _get_pool()
    try:
        t0 = datetime.fromisoformat(shift_start.replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(shift_end.replace("Z", "+00:00"))
    except ValueError as e:
        raise ValueError(f"Invalid shift_start/shift_end ISO timestamps: {e}") from e

    async with pool.acquire() as conn:
        inc_rows = await conn.fetch(
            """
            SELECT *
            FROM incidents
            WHERE created_at >= $1::timestamptz AND created_at < $2::timestamptz
            ORDER BY created_at DESC
            """,
            t0,
            t1,
        )
        rep_query = """
            SELECT *
            FROM incident_reports
            WHERE generated_at >= $1::timestamptz AND generated_at < $2::timestamptz
        """
        params: list[Any] = [t0, t1]
        if officer_id.strip() and officer_id.strip() != "*":
            rep_query += " AND generated_by = $3"
            params.append(officer_id.strip())
        rep_rows = await conn.fetch(rep_query, *params)

    return {
        "officer_id": officer_id,
        "shift_start": shift_start,
        "shift_end": shift_end,
        "incidents": [_row_to_dict(r) for r in inc_rows],
        "incident_reports": [_row_to_dict(r) for r in rep_rows],
    }


@mcp.tool()
async def get_incident(incident_id: str) -> dict:
    """Return full incident record with evidence and timeline attached."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        incident = await conn.fetchrow(
            "SELECT * FROM incidents WHERE id = $1::uuid",
            incident_id,
        )
        if not incident:
            return {}

        evidence_rows = await conn.fetch(
            """
            SELECT * FROM incident_evidence
            WHERE incident_id = $1::uuid
            ORDER BY created_at ASC
            """,
            incident_id,
        )
        timeline_rows = await conn.fetch(
            """
            SELECT * FROM incident_timeline
            WHERE incident_id = $1::uuid
            ORDER BY created_at ASC
            """,
            incident_id,
        )

    result = _row_to_dict(incident)
    result["evidence"] = [_row_to_dict(r) for r in evidence_rows]
    result["timeline"] = [_row_to_dict(r) for r in timeline_rows]
    return result


_PRIORITY_ORDER_SQL = """
  CASE LOWER(COALESCE(priority, ''))
    WHEN 'critical' THEN 1
    WHEN 'high' THEN 2
    WHEN 'medium' THEN 3
    WHEN 'low' THEN 4
    ELSE 5
  END
"""


@mcp.tool()
async def list_ground_officer_active_incidents(
    officer_rank: str,
    zone: str | None = None,
    limit: int = 50,
) -> dict:
    """Open incidents dispatched to this ground officer rank (optional zone filter)."""
    if limit <= 0:
        limit = 50
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT *
            FROM incidents
            WHERE incident_status = 'open'
              AND dispatched_officer_role = $1
              AND ($2::text IS NULL OR assigned_zone = $2)
            ORDER BY {_PRIORITY_ORDER_SQL}, updated_at DESC
            LIMIT $3
            """,
            officer_rank,
            zone,
            limit,
        )
    return {"incidents": [_row_to_dict(r) for r in rows]}


@mcp.tool()
async def list_unacknowledged_dispatches_for_role(officer_rank: str, limit: int = 50) -> dict:
    """Dispatch notifications not yet acknowledged for the given officer rank."""
    if limit <= 0:
        limit = 50
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT dn.*, i.incident_type, i.priority, i.location, i.incident_status
            FROM dispatch_notifications dn
            JOIN incidents i ON i.id = dn.incident_id
            WHERE dn.acknowledged = FALSE AND dn.dispatched_officer_role = $1
            ORDER BY dn.sent_at DESC
            LIMIT $2
            """,
            officer_rank,
            limit,
        )
    return {"notifications": [_row_to_dict(r) for r in rows]}


@mcp.tool()
async def list_dispatch_panel_rows(limit: int = 100) -> dict:
    """Recent dispatch notifications with incident context (Command Centre panel)."""
    if limit <= 0:
        limit = 100
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT dn.*, i.incident_type, i.priority, i.location, i.incident_status, i.assigned_zone
            FROM dispatch_notifications dn
            JOIN incidents i ON i.id = dn.incident_id
            ORDER BY dn.sent_at DESC
            LIMIT $1
            """,
            limit,
        )
    return {"rows": [_row_to_dict(r) for r in rows]}


@mcp.tool()
async def list_cc_open_incidents_sorted(limit: int = 200) -> dict:
    """All open incidents sorted by Certis-style priority (critical first)."""
    if limit <= 0:
        limit = 200
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT *
            FROM incidents
            WHERE incident_status = 'open'
            ORDER BY {_PRIORITY_ORDER_SQL}, created_at DESC
            LIMIT $1
            """,
            limit,
        )
    return {"incidents": [_row_to_dict(r) for r in rows]}


@mcp.tool()
async def list_human_review_queue(limit: int = 100) -> dict:
    """Remote-feed open incidents awaiting human review."""
    if limit <= 0:
        limit = 100
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT *
            FROM incidents
            WHERE feed_source = 'remote'
              AND incident_status = 'open'
              AND (human_review_status IS NULL OR human_review_status = 'pending')
            ORDER BY {_PRIORITY_ORDER_SQL}, created_at DESC
            LIMIT $1
            """,
            limit,
        )
    return {"incidents": [_row_to_dict(r) for r in rows]}


@mcp.tool()
async def list_incident_reports_rows(limit: int = 100) -> dict:
    """Recent incident reports (narratives) for SCC list + submit flow."""
    if limit <= 0:
        limit = 100
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM incident_reports
            ORDER BY COALESCE(generated_at, 'epoch'::timestamptz) DESC
            LIMIT $1
            """,
            limit,
        )
    return {"reports": [_row_to_dict(r) for r in rows]}


@mcp.tool()
async def list_zone_open_counts() -> dict:
    """Count of open incidents per assigned zone."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT COALESCE(NULLIF(TRIM(assigned_zone), ''), '(unassigned)') AS zone, COUNT(*)::bigint AS open_count
            FROM incidents
            WHERE incident_status = 'open'
            GROUP BY 1
            ORDER BY open_count DESC, zone ASC
            """
        )
    return {"zones": [_row_to_dict(r) for r in rows]}


@mcp.tool()
async def list_risk_points_last_24h() -> dict:
    """Incident risk scores from the last 24 hours (supervisor chart)."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT id, risk_score, priority, assigned_zone, incident_type, created_at
            FROM incidents
            WHERE created_at >= (NOW() AT TIME ZONE 'utc') - INTERVAL '24 hours'
            ORDER BY {_PRIORITY_ORDER_SQL}, created_at DESC
            """
        )
    return {"points": [_row_to_dict(r) for r in rows]}


@mcp.tool()
async def list_audit_log_for_incident(incident_id: str) -> dict:
    """Full audit trail for one incident."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM audit_log
            WHERE incident_id = $1::uuid
            ORDER BY created_at ASC
            """,
            incident_id,
        )
    return {"entries": [_row_to_dict(r) for r in rows]}


@mcp.tool()
async def get_officer_daily_task(
    officer_rank: str,
    zone: str | None = None,
    task_date: str | None = None,
) -> dict:
    """Today's (or given ISO date YYYY-MM-DD) routine task row for rank/zone, if any."""
    pool = await _get_pool()
    date_str = (task_date or "").strip() or datetime.now(UTC).date().isoformat()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT *
            FROM officer_daily_tasks
            WHERE task_date = $1::date
              AND officer_rank = $2
              AND ($3::text IS NULL OR zone IS NULL OR TRIM(zone) = '' OR zone = $3)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            date_str,
            officer_rank,
            zone,
        )
    return {"task": _row_to_dict(row) if row else None, "task_date": date_str}


@mcp.tool()
async def list_zone_shift_incidents(zone: str, shift_start: str, shift_end: str) -> dict:
    """Incidents in a time window for a zone (end-of-shift export)."""
    pool = await _get_pool()
    try:
        t0 = datetime.fromisoformat(shift_start.replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(shift_end.replace("Z", "+00:00"))
    except ValueError as e:
        raise ValueError(f"Invalid ISO shift bounds: {e}") from e
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM incidents
            WHERE created_at >= $1::timestamptz AND created_at < $2::timestamptz
              AND ($3::text IS NULL OR TRIM($3) = '' OR assigned_zone = $3)
            ORDER BY created_at DESC
            """,
            t0,
            t1,
            zone.strip() or None,
        )
    return {
        "zone": zone,
        "shift_start": shift_start,
        "shift_end": shift_end,
        "incidents": [_row_to_dict(r) for r in rows],
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
