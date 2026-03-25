"""Parse MCP ``call_tool`` return values into plain dicts (FastMCP / streamable HTTP)."""

from __future__ import annotations

import json
from typing import Any


def tool_result_as_dict(result: Any) -> dict | None:
    """Best-effort extract a JSON object from an MCP tool result."""
    if result is None:
        return None
    if isinstance(result, dict):
        if "structuredContent" in result or "content" in result:
            sc = result.get("structuredContent")
            if isinstance(sc, dict):
                return sc
            content = result.get("content") or []
            for item in content:
                t = item.get("text") if isinstance(item, dict) else getattr(item, "text", None)
                if t:
                    try:
                        parsed = json.loads(t)
                        if isinstance(parsed, dict):
                            return parsed
                    except json.JSONDecodeError:
                        continue
            return None
        return result
    sc = getattr(result, "structuredContent", None)
    if isinstance(sc, dict):
        return sc
    content = getattr(result, "content", None) or []
    for item in content:
        t = getattr(item, "text", None) if not isinstance(item, dict) else item.get("text")
        if t:
            try:
                parsed = json.loads(t)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
    return None
