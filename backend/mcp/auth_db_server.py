"""MCP server for Supabase Auth (cloud) lookups.

This server talks to Supabase Auth over HTTPS (not direct Postgres).
Agents must call these tools rather than accessing auth data directly.
"""

from __future__ import annotations

import json
import os
from typing import Any, Literal

import httpx
import jwt
from mcp.server.fastmcp import FastMCP

from backend.config import settings

mcp = FastMCP(
    "auth-db",
    host="127.0.0.1",
    port=settings.MCP_AUTH_DB_PORT,
    streamable_http_path="/",
)

CertisRank = Literal["SO", "SSO", "SS", "SSS", "CSO"]
DeploymentType = Literal["ground", "command_centre"]
StaffRoleType = Literal["security_officer", "auxiliary_police", "enforcement_officer"]

RANK_PERMISSIONS: dict[CertisRank, list[str]] = {
    "SO": ["respond_incident", "view_own_tasks", "submit_report"],
    "SSO": [
        "respond_incident",
        "view_own_tasks",
        "submit_report",
        "operate_scc",
        "monitor_cctv",
        "manage_keys",
    ],
    "SS": [
        "respond_incident",
        "view_all_incidents",
        "submit_report",
        "operate_scc",
        "monitor_cctv",
        "dispatch_ground",
        "approve_escalation",
        "manage_incident",
    ],
    "SSS": [
        "respond_incident",
        "view_all_incidents",
        "submit_report",
        "operate_scc",
        "monitor_cctv",
        "dispatch_ground",
        "approve_escalation",
        "conduct_audit",
        "risk_assessment",
    ],
    "CSO": ["*"],
}

RANK_LABELS: dict[CertisRank, str] = {
    "SO": "Security Officer",
    "SSO": "Senior Security Officer",
    "SS": "Security Supervisor",
    "SSS": "Senior Security Supervisor",
    "CSO": "Chief Security Officer",
}

_CERTIS_RANKS = frozenset(RANK_PERMISSIONS.keys())


def _parse_certis_rank(meta: dict[str, Any]) -> CertisRank | None:
    r = meta.get("rank")
    if isinstance(r, str):
        u = r.strip().upper()
        if u in _CERTIS_RANKS:
            return u  # type: ignore[return-value]
    legacy = meta.get("role")
    if legacy == "admin":
        return "CSO"
    if isinstance(legacy, str):
        u = legacy.strip().upper()
        if u in _CERTIS_RANKS:
            return u  # type: ignore[return-value]
    return None


def _default_deployment(rank: CertisRank) -> DeploymentType:
    if rank == "SO":
        return "ground"
    return "command_centre"


def _can_approve_escalation(rank: CertisRank) -> bool:
    return rank in ("SS", "SSS", "CSO")


def _can_operate_scc(rank: CertisRank) -> bool:
    return rank in ("SSO", "SS", "SSS", "CSO")


def _coerce_role_type(raw: object) -> StaffRoleType:
    if isinstance(raw, str):
        u = raw.strip().lower()
        if u in ("security_officer", "auxiliary_police", "enforcement_officer"):
            return u  # type: ignore[return-value]
    return "security_officer"


def _get_permissions(profile: dict[str, Any]) -> list[str]:
    role_type = _coerce_role_type(profile.get("role_type"))
    if role_type == "auxiliary_police":
        return ["respond_incident", "view_own_tasks", "submit_report", "armed_response"]
    if role_type == "enforcement_officer":
        return ["respond_incident", "view_own_tasks", "submit_report", "enforcement_action"]
    rank = profile.get("rank")
    if isinstance(rank, str) and rank in RANK_PERMISSIONS:
        return list(RANK_PERMISSIONS[rank])  # type: ignore[index]
    return []


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


async def _fetch_profile_row(
    client: httpx.AsyncClient, base_url: str, service_key: str, user_id: str
) -> dict[str, Any] | None:
    """Load ``public.profiles`` via PostgREST (requires table exposed in Supabase API)."""
    r = await client.get(
        f"{base_url}/rest/v1/profiles",
        params={"id": f"eq.{user_id}", "select": "*"},
        headers={
            "Authorization": f"Bearer {service_key}",
            "apikey": service_key,
            "Accept": "application/json",
            "Accept-Profile": "public",
        },
    )
    if r.status_code not in (200, 206):
        return None
    data = r.json()
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return None


def _rank_from_profile_row(row: dict[str, Any]) -> CertisRank | None:
    raw = row.get("rank")
    if isinstance(raw, str) and raw in _CERTIS_RANKS:
        return raw  # type: ignore[return-value]
    return None


@mcp.tool()
async def get_user_role(user_id: str) -> dict:
    """Return Certis rank, permissions, deployment, zone, and badge from Supabase.

    Prefer ``public.profiles`` (PostgREST). If no row exists, fall back to
    ``auth`` admin user ``user_metadata`` (``rank``, ``assigned_zone``, etc.).
    """
    url = _supabase_url()
    service_key = _supabase_service_role_key()

    async with await _client() as client:
        auth_r = await client.get(
            f"{url}/auth/v1/admin/users/{user_id}",
            headers={
                "Authorization": f"Bearer {service_key}",
                "apikey": service_key,
            },
        )

        if auth_r.status_code != 200:
            return {
                "role": None,
                "role_type": None,
                "rank": None,
                "role_label": None,
                "permissions": None,
                "can_approve_escalation": False,
                "can_operate_scc": False,
                "assigned_zone": None,
                "deployment_type": None,
                "todays_assignment": None,
                "assignment_set_at": None,
                "badge_id": None,
                "organisation": None,
            }

        auth_data = auth_r.json()
        meta = (auth_data.get("user_metadata") or {}) if isinstance(auth_data, dict) else {}
        legacy_role = meta.get("role")
        organisation = meta.get("organisation")

        profile = await _fetch_profile_row(client, url, service_key, user_id)

        if profile:
            role_type = _coerce_role_type(profile.get("role_type"))
            rank = _rank_from_profile_row(profile) if role_type == "security_officer" else None
            if role_type == "security_officer" and rank is None:
                rank = "SO"
            role_label = profile.get("role_label")
            if not isinstance(role_label, str) or not role_label.strip():
                role_label = RANK_LABELS[rank] if rank else "Officer"

            ta_raw = profile.get("todays_assignment")
            todays_assignment: str | None = ta_raw if ta_raw in ("ground", "command_centre") else None
            assignment_set_at = profile.get("assignment_set_at")
            assignment_set_at_str = assignment_set_at if isinstance(assignment_set_at, str) else None

            if role_type in ("auxiliary_police", "enforcement_officer"):
                deployment_type: DeploymentType = "ground"
            else:
                merged = profile.get("todays_assignment") or profile.get("deployment_type")
                if merged in ("ground", "command_centre"):
                    deployment_type = merged  # type: ignore[assignment]
                elif rank:
                    deployment_type = _default_deployment(rank)
                else:
                    deployment_type = "ground"

            assigned_zone = profile.get("assigned_zone")
            badge_id = profile.get("badge_id")
            perm_profile = {**profile, "role_type": role_type, "rank": rank}
            perms = _get_permissions(perm_profile)
            rk = rank
            return {
                "role": legacy_role,
                "role_type": role_type,
                "rank": rank,
                "role_label": role_label,
                "permissions": perms,
                "can_approve_escalation": rk in ("SS", "SSS", "CSO") if rk else False,
                "can_operate_scc": rk in ("SSO", "SS", "SSS", "CSO") if rk else False,
                "assigned_zone": assigned_zone if isinstance(assigned_zone, str) else None,
                "deployment_type": deployment_type,
                "todays_assignment": todays_assignment,
                "assignment_set_at": assignment_set_at_str,
                "badge_id": badge_id if isinstance(badge_id, str) else None,
                "organisation": organisation,
            }

        rt_fb = _coerce_role_type(meta.get("role_type")) if isinstance(meta, dict) else "security_officer"

        if rt_fb in ("auxiliary_police", "enforcement_officer"):
            rl = meta.get("role_label") if isinstance(meta, dict) else None
            role_label_apo = (
                rl
                if isinstance(rl, str) and rl.strip()
                else (
                    "Auxiliary Police Officer"
                    if rt_fb == "auxiliary_police"
                    else "Enforcement Officer"
                )
            )
            perm_apo = _get_permissions({"role_type": rt_fb, "rank": None})
            return {
                "role": legacy_role,
                "role_type": rt_fb,
                "rank": None,
                "role_label": role_label_apo,
                "permissions": perm_apo,
                "can_approve_escalation": False,
                "can_operate_scc": False,
                "assigned_zone": meta.get("assigned_zone") if isinstance(meta, dict) else None,
                "deployment_type": "ground",
                "todays_assignment": None,
                "assignment_set_at": None,
                "badge_id": meta.get("badge_id") if isinstance(meta.get("badge_id"), str) else None,
                "organisation": organisation,
            }

        rank = _parse_certis_rank(meta if isinstance(meta, dict) else {})

        if rank is None:
            return {
                "role": legacy_role,
                "role_type": None,
                "rank": None,
                "role_label": None,
                "permissions": None,
                "can_approve_escalation": False,
                "can_operate_scc": False,
                "assigned_zone": meta.get("assigned_zone") if isinstance(meta, dict) else None,
                "deployment_type": None,
                "todays_assignment": None,
                "assignment_set_at": None,
                "badge_id": None,
                "organisation": organisation,
            }

        dt_raw = meta.get("deployment_type") if isinstance(meta, dict) else None
        if dt_raw in ("ground", "command_centre"):
            deployment_type_fb: DeploymentType = dt_raw  # type: ignore[assignment]
        else:
            deployment_type_fb = _default_deployment(rank)

        perms_so = list(RANK_PERMISSIONS[rank])

        return {
            "role": legacy_role,
            "role_type": "security_officer",
            "rank": rank,
            "role_label": RANK_LABELS[rank],
            "permissions": perms_so,
            "can_approve_escalation": _can_approve_escalation(rank),
            "can_operate_scc": _can_operate_scc(rank),
            "assigned_zone": meta.get("assigned_zone") if isinstance(meta, dict) else None,
            "deployment_type": deployment_type_fb,
            "todays_assignment": None,
            "assignment_set_at": None,
            "badge_id": meta.get("badge_id") if isinstance(meta.get("badge_id"), str) else None,
            "organisation": organisation,
        }


@mcp.tool()
async def get_role_permissions(role: str) -> dict:
    """Return permissions for a Certis rank (SO, SSO, …) or legacy role name."""
    u = role.strip().upper() if isinstance(role, str) else ""
    if u in _CERTIS_RANKS:
        return {"permissions": RANK_PERMISSIONS[u]}  # type: ignore[index]
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
