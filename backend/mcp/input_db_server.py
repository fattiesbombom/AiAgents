"""MCP server for Input DB reads/writes (operational + RAG DB).

Agents must never connect to the DB directly; they call these MCP tools.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
from mcp.server.fastmcp import FastMCP

from backend.config import settings

mcp = FastMCP("input-db", host="127.0.0.1", port=settings.MCP_INPUT_DB_PORT)

_pool: asyncpg.Pool | None = None


def _input_db_url() -> str:
    url = os.getenv("INPUT_DB_URL")
    if not url:
        raise RuntimeError("Missing required env var INPUT_DB_URL")
    return url


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn=_input_db_url(), min_size=1, max_size=10)
    return _pool


def _since_ts(minutes_back: int) -> datetime:
    if minutes_back < 0:
        minutes_back = 0
    return datetime.now(UTC) - timedelta(minutes=minutes_back)


def _vector_literal(values: list[float]) -> str:
    # pgvector accepts: '[1,2,3]'::vector
    return "[" + ",".join(str(float(v)) for v in values) + "]"


def _row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    return dict(row)


@mcp.tool()
async def get_recent_motion_events(source_type: str, minutes_back: int = 10) -> list[dict]:
    """Return recent motion events for the given source_type."""
    pool = await _get_pool()
    since = _since_ts(minutes_back)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, source_id, source_type, feed_source, detected_objects, confidence,
                   snapshot_path, source_label, timestamp
            FROM motion_events
            WHERE source_type = $1 AND timestamp >= $2
            ORDER BY timestamp DESC
            """,
            source_type,
            since,
        )
    return [_row_to_dict(r) for r in rows]


@mcp.tool()
async def get_access_logs_for_zone(zone: str, minutes_back: int = 30) -> list[dict]:
    """Return recent access logs for a zone, enriched with employee details."""
    pool = await _get_pool()
    since = _since_ts(minutes_back)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
              al.id,
              al.badge_id,
              al.door_id,
              al.employee_id,
              al.attempt_result,
              al.timestamp,
              al.location,
              e.name AS employee_name,
              e.authorised_zones AS authorised_zones
            FROM access_logs al
            LEFT JOIN employees e ON e.id = al.employee_id OR e.badge_id = al.badge_id
            WHERE al.location = $1 AND al.timestamp >= $2
            ORDER BY al.timestamp DESC
            """,
            zone,
            since,
        )
    return [_row_to_dict(r) for r in rows]


@mcp.tool()
async def check_employee_authorisation(badge_id: str, zone: str) -> dict:
    """Check whether a badge holder is authorised for the given zone."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, name, department, role, badge_id, authorised_zones
            FROM employees
            WHERE badge_id = $1
            """,
            badge_id,
        )

    if not row:
        return {"is_authorised": False, "employee": None}

    employee = _row_to_dict(row)
    zones = employee.get("authorised_zones") or []
    is_authorised = zone in zones
    return {"is_authorised": bool(is_authorised), "employee": employee}


@mcp.tool()
async def get_unacknowledged_events_for_zone(zone: str, minutes_back: int = 15) -> dict[str, Any]:
    """Return recent unacknowledged alarm events for a zone and recent motion events (best-effort zone match)."""
    pool = await _get_pool()
    since = _since_ts(minutes_back)
    zone_like = f"%{zone}%" if zone else "%"
    async with pool.acquire() as conn:
        alarm_rows = await conn.fetch(
            """
            SELECT id, alarm_type, zone, severity, source_label, timestamp, acknowledged
            FROM alarm_events
            WHERE timestamp >= $1
              AND COALESCE(acknowledged, FALSE) = FALSE
              AND ($2::text = '' OR zone = $2 OR zone ILIKE $3 OR source_label ILIKE $3)
            ORDER BY timestamp DESC
            LIMIT 50
            """,
            since,
            zone or "",
            zone_like,
        )
        motion_rows = []
        if zone:
            motion_rows = await conn.fetch(
                """
                SELECT id, source_id, source_type, feed_source, detected_objects, confidence,
                       snapshot_path, source_label, timestamp
                FROM motion_events
                WHERE timestamp >= $1
                  AND (source_id ILIKE $2 OR COALESCE(source_label, '') ILIKE $2)
                ORDER BY timestamp DESC
                LIMIT 50
                """,
                since,
                zone_like,
            )
    alarms = [_row_to_dict(r) for r in alarm_rows]
    motions = [_row_to_dict(r) for r in motion_rows]
    has_anomaly = bool(alarms) or bool(motions)
    return {"alarms": alarms, "motion_events": motions, "has_anomaly": has_anomaly}


@mcp.tool()
async def get_recent_alarm_events(
    minutes_back: int = 10, alarm_type: str | None = None
) -> list[dict]:
    """Return recent alarm events, optionally filtered by alarm_type."""
    pool = await _get_pool()
    since = _since_ts(minutes_back)
    async with pool.acquire() as conn:
        if alarm_type:
            rows = await conn.fetch(
                """
                SELECT id, alarm_type, zone, severity, source_label, timestamp, acknowledged
                FROM alarm_events
                WHERE alarm_type = $1 AND timestamp >= $2
                ORDER BY timestamp DESC
                """,
                alarm_type,
                since,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, alarm_type, zone, severity, source_label, timestamp, acknowledged
                FROM alarm_events
                WHERE timestamp >= $1
                ORDER BY timestamp DESC
                """,
                since,
            )
    return [_row_to_dict(r) for r in rows]


@mcp.tool()
async def search_sop_chunks(query_embedding: list[float], top_k: int = 5) -> list[dict]:
    """Semantic search SOP chunks using pgvector cosine distance."""
    if top_k <= 0:
        top_k = 5
    pool = await _get_pool()
    vec = _vector_literal(query_embedding)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
              content,
              title,
              source_file,
              (1 - (embedding <=> ($1)::vector)) AS similarity_score
            FROM sop_documents
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> ($1)::vector
            LIMIT $2
            """,
            vec,
            top_k,
        )
    return [_row_to_dict(r) for r in rows]


@mcp.tool()
async def get_agent_state(incident_id: str) -> dict:
    """Return persisted LangGraph state JSON for an incident (includes sop_chunks when present)."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT state_json FROM incident_agent_state WHERE incident_id = $1::uuid",
            incident_id,
        )
    if not row or row["state_json"] is None:
        return {"sop_chunks": [], "state_json": None}
    sj = row["state_json"]
    if isinstance(sj, str):
        sj = json.loads(sj)
    chunks: list = []
    if isinstance(sj, dict):
        raw = sj.get("sop_chunks")
        if isinstance(raw, list):
            chunks = raw
    return {"sop_chunks": chunks, "state_json": sj}


@mcp.tool()
async def save_agent_state(incident_id: str, state_json: dict) -> dict:
    """Persist the full incident shared state snapshot for debugging/restarts."""
    pool = await _get_pool()
    now = datetime.now(UTC)
    payload = json.dumps(state_json)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO incident_agent_state (incident_id, state_json, updated_at)
            VALUES ($1::uuid, $2::jsonb, $3)
            ON CONFLICT (incident_id)
            DO UPDATE SET state_json = EXCLUDED.state_json, updated_at = EXCLUDED.updated_at
            """,
            incident_id,
            payload,
            now,
        )
    return {"ok": True, "incident_id": incident_id, "updated_at": now.isoformat()}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
