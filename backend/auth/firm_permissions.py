"""Firm-membership checks (Phase 2 / Week 5 / Day 1).

Day 1 only checks *membership* — any user who's in ``firm_memberships`` for
the firm can call the firm-library endpoints. Role-gated actions (admin
to retire, etc.) are Day 3 work; this module gives Day 3 a clean place
to extend.
"""

from __future__ import annotations

from typing import Literal

from db.connection import acquire

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
    """True if the user belongs to the firm (any role).

    Firm-wide admins (``users.role='admin'`` from Phase 1) bypass — they
    can see every firm's content for Phase-1 ops needs. We can tighten
    this in Day 3 when role-gated endpoints land.
    """
    if not user or not user.get("user_id"):
        return False
    if user.get("role") == "admin":
        return True
    return (await get_firm_role(firm_id, user["user_id"])) is not None


async def is_firm_admin(firm_id: str, user: dict) -> bool:
    """True if the user is an admin within the firm.

    Used by Day 3's role-gated endpoints (retire, library-edit) — built
    today so the API surface is stable from the start.
    """
    if not user or not user.get("user_id"):
        return False
    if user.get("role") == "admin":
        return True
    return (await get_firm_role(firm_id, user["user_id"])) == "admin"
