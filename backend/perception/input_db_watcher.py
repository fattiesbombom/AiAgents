"""Poll the Certis **input** Postgres database for discrete events and POST them to ``/trigger``.

Architecture
------------
Operational data (alarms, access, MOP reports, optional motion/C2 rows) lives in the same database
the input-db MCP server uses (``INPUT_DB_URL``). This module is a lightweight **event bus poller**:
it maintains per-table cursors ``(timestamp, id)``, fetches strictly newer rows than the cursor,
applies configurable trigger rules, and forwards matching rows to the existing FastAPI trigger API
(``TriggerEvent`` shape in ``backend/api/trigger.py``).

Video frame pipelines and ``HeartbeatWatcher`` are intentionally **not** integrated here; they keep
their own ingestion paths.

Idempotency
-----------
Each row is processed at most once per cursor advance. Cursors are updated only after a row is
either skipped by rules (no trigger) or successfully POSTed. Failed HTTP posts leave the cursor
unchanged so the row is retried on the next poll.

**Restart safety:** set ``INPUT_DB_CURSOR_FILE`` to a path (default under ``./data/``). Cursors are
saved as JSON after each successful batch. If ``INPUT_DB_CURSOR_FILE`` is empty, cursors are
memory-only (v1-friendly but duplicates possible across restarts if the API accepted a POST that
was not yet checkpointed — prefer a file path for production demos).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
import httpx

from backend.config import settings
from backend.workflow.state import SourceType

logger = logging.getLogger("security_ai.perception.input_db")

ALL_KNOWN_TABLES: frozenset[str] = frozenset(
    {"alarm_events", "mop_reports", "access_logs", "motion_events", "c2_alerts"}
)


def _parse_csv_set(raw: str) -> set[str]:
    return {p.strip().lower() for p in raw.split(",") if p.strip()}


def _iso_ts(v: Any) -> str:
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=UTC)
        return v.astimezone(UTC).isoformat()
    return str(v)


def _uuid_str(v: Any) -> str:
    if isinstance(v, UUID):
        return str(v)
    return str(v)


def _nil_uuid() -> UUID:
    return UUID(int=0)


def _epoch() -> datetime:
    return datetime(1970, 1, 1, tzinfo=UTC)


def alarm_type_to_source_type(alarm_type: str | None) -> SourceType:
    """Map free-text ``alarm_type`` to Certis ``SourceType`` (remote alarm family)."""
    s = (alarm_type or "").lower()
    if "fire" in s or "smoke" in s or "heat" in s:
        return "fire_alarm"
    if "lift" in s or "elevator" in s or "escalat" in s:
        return "lift_alarm"
    if "nursing" in s or "nurse" in s:
        return "nursing_intercom"
    if "carpark" in s or "car park" in s or "car_park" in s or "parking" in s:
        return "carpark_intercom"
    if "door" in s:
        return "door_alarm"
    if "intruder" in s or "panic" in s or "pir" in s or "motion" in s or "glass" in s:
        return "intruder_alarm"
    return "intruder_alarm"


def _severity_confidence(severity: str | None) -> float:
    s = (severity or "").lower()
    if s in ("critical", "crit", "sev1"):
        return 1.0
    if s in ("high", "major", "sev2"):
        return 0.9
    if s in ("medium", "med", "sev3"):
        return 0.75
    if s in ("low", "minor", "sev4", "info"):
        return 0.55
    return 0.7


@dataclass
class TableCursor:
    ts: datetime
    row_id: UUID

    def to_json(self) -> dict[str, str]:
        return {"timestamp": self.ts.astimezone(UTC).isoformat(), "id": str(self.row_id)}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> TableCursor:
        ts_raw = data.get("timestamp")
        id_raw = data.get("id")
        if not ts_raw or not id_raw:
            raise ValueError("cursor requires timestamp and id")
        ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return cls(ts.astimezone(UTC), UUID(str(id_raw)))


class CursorStore:
    """Load/save per-table cursors as JSON."""

    def __init__(self, path: Path | None):
        self.path = path
        self._mem: dict[str, TableCursor] = {}

    def load(self) -> None:
        if not self.path or not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Could not load cursor file %s: %s", self.path, e)
            return
        if not isinstance(raw, dict):
            return
        for k, v in raw.items():
            if isinstance(v, dict):
                try:
                    self._mem[k] = TableCursor.from_json(v)
                except ValueError:
                    continue

    def get(self, table: str) -> TableCursor | None:
        return self._mem.get(table)

    def set(self, table: str, cur: TableCursor) -> None:
        self._mem[table] = cur

    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {t: c.to_json() for t, c in self._mem.items()}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)


class InputDbWatcher:
    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None
        cf = (settings.INPUT_DB_CURSOR_FILE or "").strip()
        self._cursors = CursorStore(Path(cf) if cf else None)
        self._cursors.load()
        self._tables = [t for t in _parse_csv_set(settings.INPUT_DB_TABLES) if t in ALL_KNOWN_TABLES]
        self._severities = _parse_csv_set(settings.INPUT_DB_ALARM_SEVERITIES)
        self._access_triggers = _parse_csv_set(settings.INPUT_DB_ACCESS_TRIGGER_RESULTS)
        if not self._access_triggers:
            self._access_triggers = {"denied", "failed", "tailgating", "rejected"}
        self._batch = max(1, int(settings.INPUT_DB_POLL_BATCH_SIZE))

    async def _get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                dsn=settings.INPUT_DB_URL,
                min_size=1,
                max_size=5,
            )
        return self._pool

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def _ensure_start_cursor(self, conn: asyncpg.Connection, table: str) -> TableCursor:
        existing = self._cursors.get(table)
        if existing is not None:
            return existing
        row = await conn.fetchrow(
            f"SELECT timestamp, id FROM {table} ORDER BY timestamp DESC, id DESC LIMIT 1"
        )
        if row and row["timestamp"] is not None and row["id"] is not None:
            cur = TableCursor(row["timestamp"], row["id"])
        else:
            cur = TableCursor(_epoch(), _nil_uuid())
        self._cursors.set(table, cur)
        self._cursors.save()
        logger.info(
            "input_db_watcher initial cursor table=%s timestamp=%s id=%s",
            table,
            cur.ts.isoformat(),
            cur.row_id,
        )
        return cur

    def _alarm_should_trigger(self, row: asyncpg.Record) -> bool:
        if settings.INPUT_DB_ALARM_SKIP_ACKNOWLEDGED and row.get("acknowledged") is True:
            return False
        sev = row.get("severity")
        if self._severities:
            if (str(sev).strip().lower() if sev is not None else "") not in self._severities:
                return False
        return True

    def _access_should_trigger(self, row: asyncpg.Record) -> bool:
        ar = row.get("attempt_result")
        key = str(ar).strip().lower() if ar is not None else ""
        return bool(key) and key in self._access_triggers

    def _motion_should_trigger(self, row: asyncpg.Record) -> bool:
        conf = row.get("confidence")
        try:
            c = float(conf) if conf is not None else 0.0
        except (TypeError, ValueError):
            c = 0.0
        return c >= float(settings.INPUT_DB_MOTION_MIN_CONFIDENCE)

    def _row_to_trigger_alarm(self, row: asyncpg.Record) -> dict[str, Any]:
        st = alarm_type_to_source_type(row.get("alarm_type"))
        zone = row.get("zone") or row.get("source_label") or "Unknown zone"
        label = row.get("source_label") or row.get("alarm_type")
        rid = _uuid_str(row["id"])
        return {
            "source_id": f"input-db-alarm-{rid}",
            "feed_source": "remote",
            "source_type": st,
            "incident_type_hint": None,
            "location": str(zone),
            "timestamp": _iso_ts(row["timestamp"]),
            "evidence_refs": [f"input_db:alarm_events:{rid}"],
            "confidence_score": _severity_confidence(row.get("severity")),
            "source_label": str(label) if label else None,
            "task_mode": "non_routine",
        }

    def _row_to_trigger_mop(self, row: asyncpg.Record) -> dict[str, Any]:
        rid = _uuid_str(row["id"])
        loc = row.get("location") or row.get("source_label") or "Unknown location"
        return {
            "source_id": f"input-db-mop-{rid}",
            "feed_source": "remote",
            "source_type": "mop_report",
            "incident_type_hint": None,
            "location": str(loc),
            "timestamp": _iso_ts(row["timestamp"]),
            "evidence_refs": [f"input_db:mop_reports:{rid}"],
            "confidence_score": 0.85,
            "source_label": row.get("source_label") or row.get("report_method"),
            "task_mode": "non_routine",
        }

    def _row_to_trigger_access(self, row: asyncpg.Record) -> dict[str, Any]:
        rid = _uuid_str(row["id"])
        loc = row.get("location") or row.get("door_id") or "Unknown door"
        ar = str(row.get("attempt_result") or "").lower()
        hint = "tailgating" if "tailg" in ar else "intrusion"
        return {
            "source_id": f"input-db-access-{rid}",
            "feed_source": "remote",
            "source_type": "door_alarm",
            "incident_type_hint": hint,
            "location": str(loc),
            "timestamp": _iso_ts(row["timestamp"]),
            "evidence_refs": [f"input_db:access_logs:{rid}"],
            "confidence_score": 0.82,
            "source_label": row.get("badge_id") or row.get("door_id"),
            "task_mode": "non_routine",
        }

    def _row_to_trigger_motion(self, row: asyncpg.Record) -> dict[str, Any]:
        rid = _uuid_str(row["id"])
        loc = row.get("source_label") or row.get("source_id") or "Unknown camera"
        conf = row.get("confidence")
        try:
            score = max(0.0, min(1.0, float(conf))) if conf is not None else 0.6
        except (TypeError, ValueError):
            score = 0.6
        snap = row.get("snapshot_path")
        refs = [f"input_db:motion_events:{rid}"]
        if snap:
            refs.append(str(snap))
        return {
            "source_id": f"input-db-motion-{rid}",
            "feed_source": "remote",
            "source_type": "cctv",
            "incident_type_hint": None,
            "location": str(loc),
            "timestamp": _iso_ts(row["timestamp"]),
            "evidence_refs": refs,
            "confidence_score": score,
            "source_label": row.get("source_label"),
            "task_mode": "non_routine",
        }

    def _row_to_trigger_c2(self, row: asyncpg.Record) -> dict[str, Any]:
        rid = _uuid_str(row["id"])
        zone = row.get("zone") or "Unknown zone"
        code = row.get("alert_code")
        return {
            "source_id": f"input-db-c2-{rid}",
            "feed_source": "remote",
            "source_type": "c2_system",
            "incident_type_hint": None,
            "location": str(zone),
            "timestamp": _iso_ts(row["timestamp"]),
            "evidence_refs": [f"input_db:c2_alerts:{rid}"],
            "confidence_score": _severity_confidence(row.get("severity")),
            "source_label": str(code) if code else None,
            "task_mode": "non_routine",
        }

    async def _post_trigger(self, client: httpx.AsyncClient, body: dict[str, Any]) -> None:
        url = f"{settings.TRIGGER_API_BASE_URL.rstrip('/')}/trigger"
        r = await client.post(url, json=body, timeout=30.0)
        r.raise_for_status()

    async def _process_table(
        self,
        conn: asyncpg.Connection,
        client: httpx.AsyncClient,
        table: str,
    ) -> None:
        cur = await self._ensure_start_cursor(conn, table)
        rows = await conn.fetch(
            f"""
            SELECT * FROM {table}
            WHERE (timestamp, id) > ($1::timestamptz, $2::uuid)
            ORDER BY timestamp ASC, id ASC
            LIMIT $3
            """,
            cur.ts,
            cur.row_id,
            self._batch,
        )
        if not rows:
            return

        for row in rows:
            new_cur = TableCursor(row["timestamp"], row["id"])
            should_post = False
            body: dict[str, Any] | None = None

            if table == "alarm_events":
                should_post = self._alarm_should_trigger(row)
                body = self._row_to_trigger_alarm(row) if should_post else None
            elif table == "mop_reports":
                should_post = True
                body = self._row_to_trigger_mop(row)
            elif table == "access_logs":
                should_post = self._access_should_trigger(row)
                body = self._row_to_trigger_access(row) if should_post else None
            elif table == "motion_events":
                should_post = self._motion_should_trigger(row)
                body = self._row_to_trigger_motion(row) if should_post else None
            elif table == "c2_alerts":
                should_post = True
                body = self._row_to_trigger_c2(row)
            else:
                self._cursors.set(table, new_cur)
                continue

            if not should_post or body is None:
                self._cursors.set(table, new_cur)
                self._cursors.save()
                continue

            try:
                await self._post_trigger(client, body)
            except Exception:
                logger.exception(
                    "input_db_watcher trigger POST failed table=%s id=%s; cursor not advanced",
                    table,
                    new_cur.row_id,
                )
                return

            logger.info(
                "input_db_watcher triggered table=%s source_id=%s source_type=%s",
                table,
                body.get("source_id"),
                body.get("source_type"),
            )
            self._cursors.set(table, new_cur)
            self._cursors.save()

    async def poll_once(self) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with httpx.AsyncClient() as client:
                for table in self._tables:
                    await self._process_table(conn, client, table)

    async def run_forever(self) -> None:
        interval = max(0.5, float(settings.INPUT_DB_POLL_INTERVAL_SECONDS))
        logger.info(
            "input_db_watcher started tables=%s interval=%ss cursor_file=%s",
            self._tables,
            interval,
            self._cursors.path,
        )
        while True:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("input_db_watcher poll cycle error")
            await asyncio.sleep(interval)
