#!/usr/bin/env python3
"""DEV-ONLY: insert sample rows into the input DB over time for demos.

Not for production. Requires ``INPUT_DB_URL`` and a running Postgres with ``backend/db/input_schema.sql``
applied.

Usage (from ``security-ai-system`` root)::

    python -m backend.scripts.demo_seed_input_db

Staggered inserts help exercise ``input_db_watcher`` polling without touching video or heartbeat
pipelines.
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from datetime import UTC, datetime

from backend.config import settings


def _connect():
    try:
        import psycopg
    except ImportError:
        print("psycopg is required (see requirements.txt).", file=sys.stderr)
        raise SystemExit(1) from None
    return psycopg.connect(settings.INPUT_DB_URL)


def main() -> int:
    parser = argparse.ArgumentParser(description="DEV: seed input DB with sample events.")
    parser.add_argument(
        "--sleep",
        type=float,
        default=2.0,
        help="Seconds between inserts (default 2).",
    )
    args = parser.parse_args()

    from psycopg.types.json import Json

    def now() -> datetime:
        return datetime.now(UTC)

    with _connect() as conn:
        conn.execute("SET TIME ZONE 'UTC'")

        # 1) Alarm (fire)
        aid = uuid.uuid4()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alarm_events (id, alarm_type, zone, severity, source_label, timestamp, acknowledged)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (aid, "fire_smoke", "Block A L3", "high", "panel-east", now(), False),
            )
        conn.commit()
        print("Inserted alarm_events", aid)
        time.sleep(max(0.0, args.sleep))

        # 2) MOP report
        mid = uuid.uuid4()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mop_reports (id, report_method, location, description, source_label, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (mid, "mobile_app", "Lobby", "Wet floor near lift B", "cleaning-team", now()),
            )
        conn.commit()
        print("Inserted mop_reports", mid)
        time.sleep(max(0.0, args.sleep))

        # 3) Suspicious access
        lid = uuid.uuid4()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO access_logs (id, badge_id, door_id, employee_id, attempt_result, timestamp, location)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (lid, "BADGE-999", "DOOR-12", None, "tailgating", now(), "Staff entrance"),
            )
        conn.commit()
        print("Inserted access_logs", lid)
        time.sleep(max(0.0, args.sleep))

        # 4) Optional motion row (only if you enabled motion_events on the watcher)
        vid = uuid.uuid4()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO motion_events (
                    id, source_id, source_type, feed_source, detected_objects, confidence, snapshot_path, source_label, timestamp
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    vid,
                    "cam-lobby-1",
                    "cctv",
                    "remote",
                    ["person"],
                    0.88,
                    None,
                    "Lobby PTZ",
                    now(),
                ),
            )
        conn.commit()
        print("Inserted motion_events", vid)
        time.sleep(max(0.0, args.sleep))

        # 5) C2-style alert (optional table)
        cid = uuid.uuid4()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO c2_alerts (id, alert_code, zone, severity, raw_payload, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (cid, "PERIM-01", "Perimeter north", "medium", Json({"note": "demo"}), now()),
            )
        conn.commit()
        print("Inserted c2_alerts", cid)

    print("Done. Ensure INPUT_DB_WATCHER_ENABLED=true and tables list includes what you want to poll.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
