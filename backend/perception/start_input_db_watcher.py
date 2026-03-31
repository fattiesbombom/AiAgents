"""Run the input-database perception poller (discrete events → ``POST /trigger``).

From ``security-ai-system`` root::

    python -m backend.perception.start_input_db_watcher

Requires ``INPUT_DB_WATCHER_ENABLED=true`` and ``INPUT_DB_URL`` set. Does not start video or
heartbeat watchers; use ``start_perception_watchers`` for wearable HTTP polling.
"""

from __future__ import annotations

import asyncio
import logging

from backend.config import settings
from backend.perception.input_db_watcher import InputDbWatcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("security_ai.perception.input_db_start")


def main() -> int:
    if not settings.INPUT_DB_WATCHER_ENABLED:
        logger.warning(
            "INPUT_DB_WATCHER_ENABLED is false — set to true in .env to run the input DB poller."
        )
        return 0

    async def amain() -> None:
        watcher = InputDbWatcher()
        try:
            await watcher.run_forever()
        finally:
            await watcher.close()

    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
