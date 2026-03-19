"""Sensor watcher for non-video sources (alarms/logs).

Supports polling:
- SQLite database file
- JSON file
- HTTP endpoint returning JSON
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx

from backend.config import settings


SourceKind = Literal["sqlite", "json_file", "webhook"]


@dataclass(frozen=True)
class SensorSource:
    source_id: str
    kind: SourceKind
    location: str
    path_or_url: str

    # SQLite specifics
    sqlite_table: str = "events"
    sqlite_id_column: str = "id"
    sqlite_type_column: str = "event_type"
    sqlite_payload_column: str = "payload_json"


class SensorWatcher:
    def __init__(self, sources: list[SensorSource], poll_interval_seconds: float | None = None):
        self.sources = sources
        self.poll_interval_seconds = float(poll_interval_seconds or 5.0)
        self._running = False
        self._thread: threading.Thread | None = None

        self._last_ids: dict[str, str] = {}
        self._last_mtime: dict[str, float] = {}

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="SensorWatcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=2.0)
        self._thread = None

    def _loop(self) -> None:
        client = httpx.Client(timeout=10.0)
        try:
            while self._running:
                for src in self.sources:
                    try:
                        events = self._poll_source(src, client)
                        for ev in events:
                            self._handle_event(src, ev, client)
                    except Exception:
                        # Best-effort; continue watching other sources.
                        continue
                time.sleep(self.poll_interval_seconds)
        finally:
            client.close()

    def _poll_source(self, src: SensorSource, client: httpx.Client) -> list[dict[str, Any]]:
        if src.kind == "sqlite":
            return self._poll_sqlite(src)
        if src.kind == "json_file":
            return self._poll_json_file(src)
        if src.kind == "webhook":
            return self._poll_webhook(src, client)
        return []

    def _poll_sqlite(self, src: SensorSource) -> list[dict[str, Any]]:
        db_path = Path(src.path_or_url)
        if not db_path.exists():
            return []

        last_id = self._last_ids.get(src.source_id)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            if last_id is None:
                row = conn.execute(
                    f"SELECT {src.sqlite_id_column} FROM {src.sqlite_table} ORDER BY {src.sqlite_id_column} DESC LIMIT 1"
                ).fetchone()
                if row:
                    self._last_ids[src.source_id] = str(row[src.sqlite_id_column])
                return []

            rows = conn.execute(
                f"""
                SELECT {src.sqlite_id_column} AS id,
                       {src.sqlite_type_column} AS event_type,
                       {src.sqlite_payload_column} AS payload_json
                FROM {src.sqlite_table}
                WHERE {src.sqlite_id_column} > ?
                ORDER BY {src.sqlite_id_column} ASC
                """,
                (last_id,),
            ).fetchall()
        finally:
            conn.close()

        events: list[dict[str, Any]] = []
        for r in rows:
            payload = {}
            try:
                payload = json.loads(r["payload_json"] or "{}")
            except Exception:
                payload = {}
            events.append({"id": str(r["id"]), "event_type": r["event_type"], "payload": payload})

        if events:
            self._last_ids[src.source_id] = events[-1]["id"]
        return events

    def _poll_json_file(self, src: SensorSource) -> list[dict[str, Any]]:
        path = Path(src.path_or_url)
        if not path.exists():
            return []

        mtime = path.stat().st_mtime
        if self._last_mtime.get(src.source_id) == mtime:
            return []
        self._last_mtime[src.source_id] = mtime

        data = json.loads(path.read_text(encoding="utf-8") or "[]")
        if isinstance(data, dict):
            data = [data]
        events: list[dict[str, Any]] = []
        for i, ev in enumerate(data if isinstance(data, list) else []):
            if isinstance(ev, dict):
                events.append({"id": str(ev.get("id", i)), "event_type": ev.get("event_type"), "payload": ev})
        return events

    def _poll_webhook(self, src: SensorSource, client: httpx.Client) -> list[dict[str, Any]]:
        r = client.get(src.path_or_url)
        if r.status_code != 200:
            return []
        data = r.json()
        if isinstance(data, dict):
            data = [data]
        events: list[dict[str, Any]] = []
        for i, ev in enumerate(data if isinstance(data, list) else []):
            if isinstance(ev, dict):
                events.append({"id": str(ev.get("id", i)), "event_type": ev.get("event_type"), "payload": ev})
        return events

    def _handle_event(self, src: SensorSource, ev: dict[str, Any], client: httpx.Client) -> None:
        etype = str(ev.get("event_type") or "").lower()
        payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}

        # Only trigger on alarm/forced door style events.
        if etype not in ("alarm_event", "forced_door", "door_forced", "intruder", "fire"):
            return

        hint = payload.get("alarm_type") or payload.get("incident_type_hint") or etype

        trigger_event: dict[str, Any] = {
            "source_id": src.source_id,
            "feed_source": "remote",
            "source_type": "non_video",
            "incident_type_hint": str(hint) if hint is not None else None,
            "location": payload.get("zone") or src.location,
            "timestamp": datetime.now(UTC).isoformat(),
            "evidence_refs": payload.get("evidence_refs") if isinstance(payload.get("evidence_refs"), list) else [],
            "confidence_score": float(payload.get("confidence_score") or 0.5),
        }

        try:
            client.post(f"http://{settings.API_HOST}:{settings.API_PORT}/trigger", json=trigger_event)
        except Exception:
            pass

