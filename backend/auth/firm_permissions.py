"""Firm-membership + role checks for the firm-library endpoints.

  Day 1 added ``is_firm_member`` / ``is_firm_admin`` (boolean predicates).
  Day 3 adds the HTTP-aware ``require_firm_member`` / ``require_firm_admin``
  helpers that raise the right ``HTTPException`` AND record a domain-level
  audit event for failed attempts (so we can spot probing across firms in
  the audit trail without combing through generic 403 logs).
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from fastapi import HTTPException, status

from db.connection import acquire

logger = logging.getLogger(__name__)

FirmRole = Literal["member", "admin"]


async def get_firm_role(firm_id: str, user_id: str) -> FirmRole | None:
    """Return the user's role in the firm, or None if not a member."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT role FROM firm_memberships
            WHERE firm_id = $1::uuid AND user_id = $2::uuid
            """,
            firm_id,
            user_id,
        )
    return row["role"] if row else None  # type: ignore[return-value]


async def is_firm_member(firm_id: str, user: dict) -> bool:
    """True if the user has a row in ``firm_memberships`` for this firm.

    Day 3 tightening: the previous "firm-wide admin (users.role='admin')
    bypasses every firm" branch is GONE. With real multi-tenancy, an
    admin of one firm must not be able to read another firm's library
    just because their user-table role is 'admin'. Membership is the
    only gate. Phase-1 deployments where the same admin user existed
    in only one firm keep working — Day 1's migration backfilled all
    existing users into the default firm with their original role.
    """
    if not user or not user.get("user_id"):
        return False
    return (await get_firm_role(firm_id, user["user_id"])) is not None


async def is_firm_admin(firm_id: str, user: dict) -> bool:
    """True if the user is an admin in firm_memberships for ``firm_id``.

    Same Day-3 tightening as :func:`is_firm_member` — no
    ``users.role='admin'`` bypass. Cross-firm admin actions require
    explicit firm membership.
    """
    if not user or not user.get("user_id"):
        return False
    return (await get_firm_role(firm_id, user["user_id"])) == "admin"


# ---------------------------------------------------------------------------
# HTTP-aware require_* helpers (Day 3)
# ---------------------------------------------------------------------------


async def _audit_unauthorized(
    *,
    user: dict | None,
    firm_id: str,
    action: str,
) -> None:
    """Best-effort domain-level audit row for a denied firm-scoped action.

    The HTTP-level audit middleware already records the 403 (status code,
    path, IP), but a domain-level event with the explicit
    ``firm_library.list_unauthorized_attempt`` action makes cross-firm
    probing easy to find via a single ``WHERE action LIKE 'firm_library.%
    unauthorized%'`` filter. Never raises — failure here must not turn a
    403 into a 500.
    """
    try:
        async with acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_events (
                    actor_user_id, actor_email, action, resource_type,
                    resource_id, payload
                ) VALUES (
                    $1::uuid, $2, $3, 'firm', $4, $5::jsonb
                )
                """,
                user.get("user_id") if user else None,
                user.get("email") if user else None,
                action,
                firm_id,
                json.dumps({"attempted_firm_id": firm_id}),
            )
    except Exception as e:  # noqa: BLE001
        logger.debug("audit unauthorized skipped: %s", e)


async def require_firm_member(firm_id: str, user: dict) -> None:
    """Raise 404 if the user is not a member of ``firm_id``.

    404 (not 403) on cross-firm reads so non-members can't enumerate
    firm UUIDs by probing for 403 vs 404. The denied attempt is still
    audited for monitoring.
    """
    if await is_firm_member(firm_id, user):
        return
    await _audit_unauthorized(
        user=user,
        firm_id=firm_id,
        action="firm_library.list_unauthorized_attempt",
    )
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Firm not found")


async def require_firm_admin(firm_id: str, user: dict) -> None:
    """Raise 403 if the user is not an admin of ``firm_id``.

    Members trying to perform admin-only actions get 403 (we already
    confirmed they can see the firm); non-members fall through to the
    member-check 404 first because callers always check membership
    before invoking this. Denied attempts audited.
    """
    if await is_firm_admin(firm_id, user):
        return
    await _audit_unauthorized(
        user=user,
        firm_id=firm_id,
        action="firm_library.admin_unauthorized_attempt",
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Firm-admin role required",
    )
