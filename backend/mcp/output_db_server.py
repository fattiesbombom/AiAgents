"""MCP server for Output DB writes/reads (dashboard-facing DB).

Agents must never connect to the DB directly; they call these MCP tools.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import asyncpg
from mcp.server.fastmcp import FastMCP

from backend.config import settings

mcp = FastMCP("output-db", host="127.0.0.1", port=settings.MCP_OUTPUT_DB_PORT)

_pool: asyncpg.Pool | None = None


def _output_db_url() -> str:
    url = os.getenv("OUTPUT_DB_URL")
    if not url:
        raise RuntimeError("Missing required env var OUTPUT_DB_URL")
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
        elif c in ("created_at", "updated_at"):
            placeholders.append(f"${i}::timestamptz")
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
        if k in ("created_at", "updated_at"):
            sets.append(f"{k} = ${idx}::timestamptz")
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


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
