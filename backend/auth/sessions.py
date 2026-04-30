"""Cookie-backed auth sessions.

The token is an opaque random string set in an HTTP-only cookie. We store
sha256(token) in `sessions_auth` so a DB compromise doesn't reveal valid tokens.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from db.connection import acquire

COOKIE_NAME = "argus_session"
SESSION_TTL_DAYS = 30


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def create_session(user_id: str, *, ip: str | None = None, user_agent: str | None = None) -> str:
    """Create an auth session for a user. Returns the opaque token (set on cookie)."""
    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    expires_at = _now() + timedelta(days=SESSION_TTL_DAYS)
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sessions_auth (user_id, token_hash, expires_at, ip, user_agent)
            VALUES ($1::uuid, $2, $3, $4, $5)
            """,
            user_id,
            token_hash,
            expires_at,
            ip,
            (user_agent or "")[:500],
        )
    return token


async def lookup_session(token: str) -> dict[str, Any] | None:
    """Resolve a token to {user_id, email, full_name, role} or None."""
    if not token:
        return None
    token_hash = _hash_token(token)
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT s.user_id, s.expires_at, s.revoked_at,
                   u.email, u.full_name, u.role
            FROM sessions_auth s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = $1
            """,
            token_hash,
        )
    if not row:
        return None
    if row["revoked_at"] is not None:
        return None
    if row["expires_at"] < _now():
        return None
    return {
        "user_id": str(row["user_id"]),
        "email": row["email"],
        "full_name": row["full_name"] or "",
        "role": row["role"] or "member",
    }


async def revoke_session(token: str) -> None:
    if not token:
        return
    token_hash = _hash_token(token)
    async with acquire() as conn:
        await conn.execute(
            "UPDATE sessions_auth SET revoked_at = NOW() WHERE token_hash = $1 AND revoked_at IS NULL",
            token_hash,
        )


async def revoke_all_for_user(user_id: str) -> None:
    async with acquire() as conn:
        await conn.execute(
            "UPDATE sessions_auth SET revoked_at = NOW() WHERE user_id = $1::uuid AND revoked_at IS NULL",
            user_id,
        )
