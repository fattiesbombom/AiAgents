"""Schedule LangGraph workflow runs from API layers (trigger + dashboard)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger("security_ai.workflow.kickoff")


async def _run_workflow_in_background(state: dict[str, Any]) -> None:
    try:
        from backend.workflow import graph as workflow_graph

        runner = getattr(workflow_graph, "run_workflow", None)
        if runner is None:
            logger.warning("run_workflow missing on backend.workflow.graph")
            return
        result = runner(state)
        if asyncio.iscoroutine(result):
            await result
    except Exception:
        logger.exception("Failed to launch workflow")


async def start_workflow(state: dict[str, Any]) -> None:
    """Awaitable entrypoint for FastAPI BackgroundTasks."""
    await _run_workflow_in_background(state)
