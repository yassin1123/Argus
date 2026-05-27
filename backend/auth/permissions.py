"""Engagement-level permission resolver.

Roles + capabilities (W2 vocabulary extended in W17/D1):
  - lead         → read + write + admin (add/remove members, change roles, delete)
  - contributor  → read + write (W17 replacement for the legacy "member")
  - reviewer     → read + write (W15 reviewer; review-action gates layer on top)
  - observer     → read-only (W17 replacement for the legacy "viewer")
  - member       → legacy alias for contributor (pre-W17 rows; migration 040
                    rewrote stored rows so this only matters for in-flight code)
  - viewer       → legacy alias for observer

Firm-wide users with role='admin' bypass all engagement checks.
Engagements with no membership rows + metadata.demo=true are public read for
all authenticated users (the seeded case studies).
"""

from __future__ import annotations

from typing import Literal

from db.connection import acquire

EngagementRole = Literal["lead", "contributor", "reviewer", "observer",
                          "member", "viewer"]
Capability = Literal["read", "write", "admin"]


_CAPABILITY_FOR_ROLE: dict[str, set[str]] = {
    "lead":        {"read", "write", "admin"},
    "contributor": {"read", "write"},
    "reviewer":    {"read", "write"},
    "observer":    {"read"},
    # Legacy aliases — migration 040 rewrote stored rows, but
    # in-flight code that snapshotted older rows may still use these.
    "member": {"read", "write"},
    "viewer": {"read"},
}


async def get_engagement_role(engagement_id: str, user_id: str) -> EngagementRole | None:
    """Return the user's role on the engagement, or None if not a member."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT role FROM engagement_memberships
            WHERE engagement_id = $1::uuid AND user_id = $2::uuid
            """,
            engagement_id,
            user_id,
        )
    return row["role"] if row else None  # type: ignore[return-value]


async def _engagement_firm_matches_user(
    engagement_id: str, user: dict,
) -> bool:
    """W23/D1 defense-in-depth: confirm the engagement's firm
    matches the requesting user's default firm. Returns False on
    any lookup failure (fail closed)."""
    user_firm = user.get("default_firm_id")
    if not user_firm:
        return False
    try:
        async with acquire() as conn:
            row = await conn.fetchrow(
                "SELECT firm_id FROM sessions WHERE id = $1::uuid",
                engagement_id,
            )
    except Exception:  # noqa: BLE001
        return False
    if not row or not row["firm_id"]:
        return False
    return str(row["firm_id"]) == str(user_firm)


async def is_demo_engagement(engagement_id: str) -> bool:
    """Demo seeds (metadata.demo=true) are read-only public for any authenticated user."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT metadata FROM sessions WHERE id = $1::uuid",
            engagement_id,
        )
    if not row:
        return False
    meta = row["metadata"]
    if isinstance(meta, str):
        import json
        try:
            meta = json.loads(meta)
        except Exception:
            return False
    return bool(meta and meta.get("demo"))


async def has_capability(engagement_id: str, user: dict, cap: Capability) -> bool:
    """True if the user can perform `cap` on the engagement.

    W23/D1 defense-in-depth: even when the engagement_memberships
    row grants a capability, we additionally require that the
    user's default firm matches the engagement's firm — so a
    stray cross-firm membership row (introduced by a bug or a
    future feature regression) can never grant cross-firm access
    on its own. The :func:`core.collaboration.membership.assign_member`
    write path already blocks cross-firm assignment; this read-
    side check is the second line of defence.
    """
    # System admin (users.role='admin') bypasses every engagement
    # check intentionally — admin tooling reads cross-firm.
    if user.get("role") == "admin":
        return True

    role = await get_engagement_role(engagement_id, user["user_id"])
    if role is not None:
        # W23/D1 defense-in-depth firm-match check.
        if not await _engagement_firm_matches_user(engagement_id, user):
            return False
        return cap in _CAPABILITY_FOR_ROLE.get(role, set())

    # Non-member: only demo engagements are publicly readable.
    if cap == "read" and await is_demo_engagement(engagement_id):
        return True
    return False


async def can_read(engagement_id: str, user: dict) -> bool:
    return await has_capability(engagement_id, user, "read")


async def can_write(engagement_id: str, user: dict) -> bool:
    return await has_capability(engagement_id, user, "write")


async def can_admin(engagement_id: str, user: dict) -> bool:
    return await has_capability(engagement_id, user, "admin")


# ----------------------------------------------------------------------------
# Membership management
# ----------------------------------------------------------------------------

async def add_membership(
    engagement_id: str, user_id: str, role: EngagementRole, added_by: str | None
) -> None:
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO engagement_memberships (engagement_id, user_id, role, added_by)
            VALUES ($1::uuid, $2::uuid, $3, $4::uuid)
            ON CONFLICT (engagement_id, user_id) DO UPDATE SET role = EXCLUDED.role
            """,
            engagement_id,
            user_id,
            role,
            added_by,
        )


async def remove_membership(engagement_id: str, user_id: str) -> bool:
    async with acquire() as conn:
        result = await conn.execute(
            "DELETE FROM engagement_memberships WHERE engagement_id = $1::uuid AND user_id = $2::uuid",
            engagement_id,
            user_id,
        )
    return result.split()[-1] != "0"


async def list_memberships(engagement_id: str) -> list[dict]:
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT em.user_id, em.role, em.added_at,
                   u.email, u.full_name
            FROM engagement_memberships em
            JOIN users u ON u.id = em.user_id
            WHERE em.engagement_id = $1::uuid
            ORDER BY
              CASE em.role WHEN 'lead' THEN 0 WHEN 'member' THEN 1 ELSE 2 END,
              em.added_at ASC
            """,
            engagement_id,
        )
    return [
        {
            "user_id": str(r["user_id"]),
            "email": r["email"],
            "full_name": r["full_name"] or "",
            "role": r["role"],
            "added_at": r["added_at"].isoformat() if r["added_at"] else None,
        }
        for r in rows
    ]
