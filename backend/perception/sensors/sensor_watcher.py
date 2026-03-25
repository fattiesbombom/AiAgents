"""Sensor watchers for non-video and integration sources.

Polls SQLite / JSON / HTTP and posts full trigger payloads to ``/trigger``.

Also includes dedicated watchers for MOP reports, C2-style feeds, and intercom lines.
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


def post_trigger_to_api(client: httpx.Client, event: dict[str, Any]) -> None:
    try:
        client.post(
            f"http://{settings.API_HOST}:{settings.API_PORT}/trigger",
            json=event,
            timeout=10.0,
        )
    except Exception:
        pass


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

    def _map_alarm_to_source_type(self, etype: str, payload: dict[str, Any]) -> str:
        et = etype.lower()
        if et == "alarm_event":
            at = str(payload.get("alarm_type") or payload.get("type") or "").lower()
            if "fire" in at:
                return "fire_alarm"
            if "lift" in at:
                return "lift_alarm"
            if "door" in at or "access" in at or "forced" in at:
                return "door_alarm"
            if "nursing" in at:
                return "nursing_intercom"
            if "carpark" in at or "car_park" in at:
                return "carpark_intercom"
            return "intruder_alarm"
        if et in ("forced_door", "door_forced"):
            return "door_alarm"
        if et == "intruder":
            return "intruder_alarm"
        if et == "fire":
            return "fire_alarm"
        return "intruder_alarm"

    def _handle_event(self, src: SensorSource, ev: dict[str, Any], client: httpx.Client) -> None:
        etype = str(ev.get("event_type") or "").lower()
        payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}

        if etype not in ("alarm_event", "forced_door", "door_forced", "intruder", "fire"):
            return

        mapped = self._map_alarm_to_source_type(etype, payload)
        hint = payload.get("alarm_type") or payload.get("incident_type_hint") or etype
        source_label = payload.get("source_label") if isinstance(payload.get("source_label"), str) else None
        if not source_label:
            source_label = f"{src.location} ({etype})"

        trigger_event: dict[str, Any] = {
            "source_id": src.source_id,
            "feed_source": "remote",
            "source_type": mapped,
            "source_label": source_label,
            "incident_type_hint": str(hint) if hint is not None else None,
            "location": str(payload.get("zone") or src.location),
            "timestamp": datetime.now(UTC).isoformat(),
            "evidence_refs": payload.get("evidence_refs") if isinstance(payload.get("evidence_refs"), list) else [],
            "confidence_score": float(payload.get("confidence_score") or 0.5),
        }
        post_trigger_to_api(client, trigger_event)


IntercomKind = Literal["lift_alarm", "nursing_intercom", "carpark_intercom"]


@dataclass(frozen=True)
class MOPSource:
    """Webhook that returns JSON list of tip-off objects."""

    source_id: str
    webhook_url: str
    location: str
    default_label: str = "Member of Public report"


@dataclass(frozen=True)
class C2FeedSource:
    """HTTP endpoint returning JSON list of C2-style alert dicts."""

    source_id: str
    feed_url: str
    location: str


@dataclass(frozen=True)
class IntercomSource:
    """Webhook returning JSON list of intercom activation events."""

    source_id: str
    webhook_url: str
    location: str
    intercom_kind: IntercomKind


class MOPWatcher:
    """Polls an app/webhook endpoint for member-of-public reports."""

    def __init__(self, sources: list[MOPSource], poll_interval_seconds: float = 5.0):
        self.sources = sources
        self.poll_interval_seconds = float(poll_interval_seconds)
        self._running = False
        self._thread: threading.Thread | None = None
        self._seen_ids: dict[str, set[str]] = {}

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="MOPWatcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def _loop(self) -> None:
        client = httpx.Client(timeout=15.0)
        try:
            while self._running:
                for src in self.sources:
                    try:
                        self._poll_mop(src, client)
                    except Exception:
                        continue
                time.sleep(self.poll_interval_seconds)
        finally:
            client.close()

    def _poll_mop(self, src: MOPSource, client: httpx.Client) -> None:
        r = client.get(src.webhook_url)
        if r.status_code != 200:
            return
        data = r.json()
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return
        seen = self._seen_ids.setdefault(src.source_id, set())
        for item in data:
            if not isinstance(item, dict):
                continue
            rid = str(item.get("id", ""))
            if not rid or rid in seen:
                continue
            if len(seen) > 2000:
                seen.clear()
            seen.add(rid)
            method = str(item.get("report_method") or "app")
            label = item.get("source_label") if isinstance(item.get("source_label"), str) else src.default_label
            trigger_event = {
                "source_id": src.source_id,
                "feed_source": "remote",
                "source_type": "mop_report",
                "source_label": label,
                "incident_type_hint": item.get("description") or "mop_report",
                "location": str(item.get("location") or src.location),
                "timestamp": str(item.get("timestamp") or datetime.now(UTC).isoformat()),
                "evidence_refs": item.get("evidence_refs") if isinstance(item.get("evidence_refs"), list) else [],
                "confidence_score": float(item.get("confidence_score") or 0.6),
                "report_method": method,
            }
            post_trigger_to_api(client, trigger_event)


class C2SystemWatcher:
    """Polls a C2-style JSON feed (HTTP); each item becomes a ``c2_system`` trigger."""

    def __init__(self, sources: list[C2FeedSource], poll_interval_seconds: float = 3.0):
        self.sources = sources
        self.poll_interval_seconds = float(poll_interval_seconds)
        self._running = False
        self._thread: threading.Thread | None = None
        self._seen_ids: dict[str, set[str]] = {}

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="C2SystemWatcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def _loop(self) -> None:
        client = httpx.Client(timeout=20.0)
        try:
            while self._running:
                for src in self.sources:
                    try:
                        self._poll_c2(src, client)
                    except Exception:
                        continue
                time.sleep(self.poll_interval_seconds)
        finally:
            client.close()

    def _poll_c2(self, src: C2FeedSource, client: httpx.Client) -> None:
        r = client.get(src.feed_url)
        if r.status_code != 200:
            return
        data = r.json()
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return
        seen = self._seen_ids.setdefault(src.source_id, set())
        for item in data:
            if not isinstance(item, dict):
                continue
            rid = str(item.get("id") or item.get("alert_id") or "")
            if not rid:
                rid = json.dumps(item, sort_keys=True)[:128]
            if rid in seen:
                continue
            if len(seen) > 2000:
                seen.clear()
            seen.add(rid)
            code = str(item.get("alert_code") or item.get("code") or "C2")
            zone = str(item.get("zone") or item.get("location") or src.location)
            sev = item.get("severity")
            label = item.get("source_label") if isinstance(item.get("source_label"), str) else f"C2 {code} @ {zone}"
            trigger_event = {
                "source_id": src.source_id,
                "feed_source": "remote",
                "source_type": "c2_system",
                "source_label": label,
                "incident_type_hint": code,
                "location": zone,
                "timestamp": str(item.get("timestamp") or datetime.now(UTC).isoformat()),
                "evidence_refs": item.get("evidence_refs") if isinstance(item.get("evidence_refs"), list) else [],
                "confidence_score": float(item.get("confidence_score") or 0.75),
                "severity": str(sev) if sev is not None else None,
                "c2_payload": item,
            }
            post_trigger_to_api(client, trigger_event)


class IntercomWatcher:
    """Listens (polls) for lift / nursing / carpark intercom activation events."""

    def __init__(self, sources: list[IntercomSource], poll_interval_seconds: float = 2.0):
        self.sources = sources
        self.poll_interval_seconds = float(poll_interval_seconds)
        self._running = False
        self._thread: threading.Thread | None = None
        self._seen_ids: dict[str, set[str]] = {}

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="IntercomWatcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def _loop(self) -> None:
        client = httpx.Client(timeout=15.0)
        try:
            while self._running:
                for src in self.sources:
                    try:
                        self._poll_intercom(src, client)
                    except Exception:
                        continue
                time.sleep(self.poll_interval_seconds)
        finally:
            client.close()

    def _poll_intercom(self, src: IntercomSource, client: httpx.Client) -> None:
        r = client.get(src.webhook_url)
        if r.status_code != 200:
            return
        data = r.json()
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return
        seen = self._seen_ids.setdefault(src.source_id, set())
        for item in data:
            if not isinstance(item, dict):
                continue
            rid = str(item.get("id") or item.get("event_id") or "")
            if not rid or rid in seen:
                continue
            if len(seen) > 2000:
                seen.clear()
            seen.add(rid)
            kind = src.intercom_kind
            labels = {
                "lift_alarm": "Lift intercom",
                "nursing_intercom": "Nursing intercom",
                "carpark_intercom": "Carpark intercom",
            }
            default_l = labels.get(kind, "Intercom")
            label = item.get("source_label") if isinstance(item.get("source_label"), str) else default_l
            trigger_event = {
                "source_id": src.source_id,
                "feed_source": "remote",
                "source_type": kind,
                "source_label": label,
                "incident_type_hint": str(item.get("reason") or kind),
                "location": str(item.get("location") or item.get("zone") or src.location),
                "timestamp": str(item.get("timestamp") or datetime.now(UTC).isoformat()),
                "evidence_refs": item.get("evidence_refs") if isinstance(item.get("evidence_refs"), list) else [],
                "confidence_score": float(item.get("confidence_score") or 0.7),
            }
            post_trigger_to_api(client, trigger_event)
