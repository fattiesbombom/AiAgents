"""Start optional perception daemons (e.g. wearable heartbeat pollers).

Configure ``HEARTBEAT_WATCHERS`` in ``.env`` as comma-separated entries::

    officer-uuid|http://127.0.0.1:9100/heartbeat,other-uuid|http://127.0.0.1:9101/heartbeat

Run from ``security-ai-system`` root (loads ``.env`` via pydantic-settings)::

    python -m backend.perception.start_perception_watchers

Requires FastAPI ``/trigger`` reachable at ``TRIGGER_API_BASE_URL`` (default http://127.0.0.1:8000).
"""

from __future__ import annotations

import logging
import signal
import sys
import time

from backend.config import settings
from backend.perception.sensors.heartbeat_watcher import HeartbeatWatcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("security_ai.perception.start")


def _parse_watchers(raw: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for part in raw.split(","):
        p = part.strip()
        if not p or "|" not in p:
            continue
        oid, url = p.split("|", 1)
        oid, url = oid.strip(), url.strip()
        if oid and url:
            out.append((oid, url))
    return out


def main() -> int:
    pairs = _parse_watchers(settings.HEARTBEAT_WATCHERS)
    if not pairs:
        logger.warning(
            "No HEARTBEAT_WATCHERS configured. Set e.g. "
            "HEARTBEAT_WATCHERS=uuid|http://127.0.0.1:9100/heartbeat in .env"
        )
        return 0

    watchers = [HeartbeatWatcher(url, oid) for oid, url in pairs]
    for w in watchers:
        w.start()

    stop = False

    def _handle_sig(*_args: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    logger.info("Running %d heartbeat watcher(s). Ctrl+C to stop.", len(watchers))
    try:
        while not stop:
            time.sleep(0.5)
    finally:
        for w in watchers:
            w.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
