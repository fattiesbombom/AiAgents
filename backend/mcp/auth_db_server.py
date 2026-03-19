"""MCP server for Supabase Auth (cloud) lookups.

This server talks to Supabase Auth over HTTPS (not direct Postgres).
Agents must call these tools rather than accessing auth data directly.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
import jwt
from mcp.server.fastmcp import FastMCP

from backend.config import settings

mcp = FastMCP("auth-db", host="127.0.0.1", port=settings.MCP_AUTH_DB_PORT)


def _supabase_url() -> str:
    url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    if not url:
        raise RuntimeError("Missing required env var SUPABASE_URL")
    return url


def _supabase_anon_key() -> str:
    key = os.getenv("SUPABASE_ANON_KEY") or ""
    if not key:
        raise RuntimeError("Missing required env var SUPABASE_ANON_KEY")
    return key


def _supabase_service_role_key() -> str:
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not key:
        raise RuntimeError("Missing required env var SUPABASE_SERVICE_ROLE_KEY")
    return key


def _role_permissions() -> dict[str, Any]:
    raw = os.getenv("ROLE_PERMISSIONS_JSON")
    if raw:
        return json.loads(raw)
    # Minimal safe default; customize via ROLE_PERMISSIONS_JSON.
    return {
        "admin": {"can": ["*"], "data_scope": "all"},
        "supervisor": {"can": ["review", "approve", "reject", "view"], "data_scope": "org"},
        "responder": {"can": ["view", "acknowledge"], "data_scope": "assigned"},
        "viewer": {"can": ["view"], "data_scope": "org"},
    }


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=10.0)


@mcp.tool()
async def get_user_role(user_id: str) -> dict:
    """Return role/permissions/organisation from Supabase user metadata."""
    url = _supabase_url()
    service_key = _supabase_service_role_key()

    async with await _client() as client:
        r = await client.get(
            f"{url}/auth/v1/admin/users/{user_id}",
            headers={
                "Authorization": f"Bearer {service_key}",
                "apikey": service_key,
            },
        )

    if r.status_code != 200:
        return {"role": None, "permissions": None, "organisation": None}

    data = r.json()
    meta = (data.get("user_metadata") or {}) if isinstance(data, dict) else {}
    role = meta.get("role")
    organisation = meta.get("organisation")
    permissions = meta.get("permissions")
    if permissions is None and isinstance(role, str):
        permissions = _role_permissions().get(role)

    return {"role": role, "permissions": permissions, "organisation": organisation}


@mcp.tool()
async def get_role_permissions(role: str) -> dict:
    """Return permissions definition for a role."""
    return _role_permissions().get(role, {})


@mcp.tool()
async def verify_session(jwt_token: str) -> dict:
    """Verify a Supabase session JWT and return basic identity info.

    We first call Supabase /auth/v1/user to validate the token server-side. If
    SUPABASE_JWT_SECRET is configured, we also decode locally to extract role.
    """
    url = _supabase_url()
    anon_key = _supabase_anon_key()

    async with await _client() as client:
        r = await client.get(
            f"{url}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {jwt_token}",
                "apikey": anon_key,
            },
        )

    if r.status_code != 200:
        return {"is_valid": False, "user_id": None, "role": None}

    data = r.json()
    user_id = data.get("id") if isinstance(data, dict) else None

    role: str | None = None
    secret = os.getenv("SUPABASE_JWT_SECRET")
    if secret:
        try:
            decoded = jwt.decode(jwt_token, secret, algorithms=["HS256"], options={"verify_aud": False})
            meta = (decoded.get("user_metadata") or {}) if isinstance(decoded, dict) else {}
            role = meta.get("role")
        except Exception:
            role = None

    return {"is_valid": True, "user_id": user_id, "role": role}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
