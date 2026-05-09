"""FastAPI dependencies for the current authenticated user."""

from __future__ import annotations

import os
from typing import Any

from fastapi import HTTPException, Request, status

from .sessions import COOKIE_NAME, lookup_session


def _bypass_enabled() -> bool:
    """Auth bypass for explicitly-flagged dev/test envs ONLY.

    Set ARGUS_AUTH_BYPASS=1 to fall back to the seeded demo user when no cookie
    is present. DEMO_MODE alone does NOT enable bypass — DEMO_MODE means
    "fixture-backed demo data is loaded," not "auth is off."
    """
    return os.getenv("ARGUS_AUTH_BYPASS", "0") == "1"


async def _demo_user() -> dict[str, Any]:
    from db.connection import acquire
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT u.id, u.email, u.full_name, u.role, u.default_firm_id,
                   m.role AS firm_role
            FROM users u
            LEFT JOIN firm_memberships m
                   ON m.user_id = u.id AND m.firm_id = u.default_firm_id
            WHERE u.email = 'demo@argus.local'
            """
        )
    if not row:
        # No demo user provisioned yet — refuse rather than fabricate identity.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return {
        "user_id": str(row["id"]),
        "email": row["email"],
        "full_name": row["full_name"] or "",
        "role": row["role"] or "member",
        "default_firm_id": str(row["default_firm_id"]) if row["default_firm_id"] else None,
        "default_firm_role": row["firm_role"] if row["firm_role"] else None,
    }


async def get_current_user(request: Request) -> dict[str, Any]:
    """Return the authenticated user dict, or 401."""
    token = request.cookies.get(COOKIE_NAME)
    user = await lookup_session(token) if token else None
    if user:
        return user
    if _bypass_enabled():
        return await _demo_user()
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


async def get_optional_user(request: Request) -> dict[str, Any] | None:
    """Return the user dict if authenticated, else None (no 401)."""
    token = request.cookies.get(COOKIE_NAME)
    if token:
        user = await lookup_session(token)
        if user:
            return user
    return None
