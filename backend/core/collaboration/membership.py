"""Engagement-membership service — Phase 4 / Week 17 / Day 1.

Enforces five invariants on top of the W2-era ``engagement_memberships``
table (extended in migration 040 with the W17 role vocabulary +
soft-remove):

  1. Only an engagement LEAD or firm admin can assign / remove
     members or change roles.
  2. The target user must be a firm-member of the engagement's firm.
     Cross-firm assignment is rejected with a clean reason; the API
     layer maps it to 403 / 404 as appropriate.
  3. Exactly one LEAD per engagement, always. Assigning a second
     lead is rejected with status_code=409 — callers must demote
     the existing lead first (per the W17/D1 surface decision).
  4. A LEAD cannot be removed without a replacement. The service
     rejects ``remove_member(lead)`` with 409 unless a different
     active lead exists.
  5. Reviewer alignment with W15 — when a member is assigned
     ``role=reviewer`` and the engagement isn't already locked into
     a different reviewer mid-cycle, ``sessions.review_assigned_to``
     is set to the new reviewer's user_id so the W15 transition
     authorisation gate stays consistent.

Soft remove only. ``removed_at`` is set; the row stays for audit-
trail integrity (matches the W16 comments pattern).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from audit.queries import append_event
from db.connection import acquire

from .roles import EngagementRole

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class EngagementMember:
    """Service-layer row shape. ``assigned_by`` / ``assigned_at``
    are the W17 names for the schema's ``added_by`` / ``added_at``
    (kept under the legacy names to avoid breaking W9 / W15 callers
    that still read directly from the table)."""

    id: str
    session_id: str
    firm_id: str
    user_id: str
    role: str
    assigned_by: str | None
    assigned_at: str
    removed_at: str | None

    @classmethod
    def from_row(cls, row: Any) -> "EngagementMember":
        return cls(
            id=str(row["id"]),
            session_id=str(row["engagement_id"]),
            firm_id=str(row["firm_id"]) if row.get("firm_id") else "",
            user_id=str(row["user_id"]),
            role=str(row["role"]),
            assigned_by=str(row["added_by"]) if row.get("added_by") else None,
            assigned_at=row["added_at"].isoformat() if row.get("added_at") else "",
            removed_at=row["removed_at"].isoformat() if row.get("removed_at") else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "firm_id": self.firm_id,
            "user_id": self.user_id,
            "role": self.role,
            "assigned_by": self.assigned_by,
            "assigned_at": self.assigned_at,
            "removed_at": self.removed_at,
        }


@dataclass
class MembershipResult:
    """Uniform return shape for every mutator. ``ok`` is True only
    when the operation committed; on failure ``status_code`` +
    ``reason`` map cleanly to an HTTP response."""

    ok: bool
    member: EngagementMember | None = None
    status_code: int = 200
    reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


# Error reason strings — kept short + 4xx-body-safe.
_AUTHOR_GATE = "engagement lead or firm admin only"
_CROSS_FIRM = "user must be a member of the engagement's firm"
_LEAD_EXISTS = "an active lead is already assigned; demote them first"
_LEAD_REMOVAL = "cannot remove the lead without first assigning a new lead"
_NOT_FOUND = "engagement membership not found"
_INVALID_ROLE = "invalid role"
_SESSION_NOT_FOUND = "session not found"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_session_firm(session_id: UUID) -> UUID | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT firm_id FROM sessions WHERE id = $1::uuid", session_id,
        )
    return row["firm_id"] if row else None


async def _is_firm_member(firm_id: UUID, user_id: UUID) -> bool:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT 1 FROM firm_memberships
             WHERE firm_id = $1::uuid AND user_id = $2::uuid
            """,
            firm_id, user_id,
        )
    return row is not None


async def _is_firm_admin(firm_id: UUID, user_id: UUID) -> bool:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT role FROM firm_memberships
             WHERE firm_id = $1::uuid AND user_id = $2::uuid
            """,
            firm_id, user_id,
        )
    return bool(row) and str(row["role"]).lower() == "admin"


async def _load_active(session_id: UUID, user_id: UUID) -> dict[str, Any] | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT em.id, em.engagement_id, em.user_id, em.role,
                   em.added_by, em.added_at, em.removed_at,
                   s.firm_id
              FROM engagement_memberships em
              JOIN sessions s ON s.id = em.engagement_id
             WHERE em.engagement_id = $1::uuid
               AND em.user_id = $2::uuid
               AND em.removed_at IS NULL
            """,
            session_id, user_id,
        )
    return dict(row) if row else None


async def _can_manage(session_id: UUID, actor_id: UUID) -> bool:
    """True when ``actor_id`` is the active lead of the engagement
    OR a firm admin of the engagement's firm. Members with role
    ``contributor`` / ``reviewer`` / ``observer`` cannot manage
    membership."""
    firm_id = await _load_session_firm(session_id)
    if firm_id is None:
        return False
    if await _is_firm_admin(firm_id, actor_id):
        return True
    membership = await _load_active(session_id, actor_id)
    return bool(membership) and str(membership["role"]) == EngagementRole.LEAD.value


async def _active_lead_id(session_id: UUID) -> UUID | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT user_id FROM engagement_memberships
             WHERE engagement_id = $1::uuid
               AND role = 'lead'
               AND removed_at IS NULL
             LIMIT 1
            """,
            session_id,
        )
    return row["user_id"] if row else None


async def _coerce_role(role: str | EngagementRole) -> EngagementRole | None:
    """Map string / enum into :class:`EngagementRole`. Returns None
    on unknown values."""
    if isinstance(role, EngagementRole):
        return role
    try:
        return EngagementRole(role)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


async def _audit(
    *,
    action: str,
    actor_user_id: UUID,
    session_id: UUID,
    target_user_id: UUID | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Best-effort audit row for every membership action. Failures
    are swallowed by :func:`append_event` so a flaky audit insert
    can't break a membership write (matches the W15 / W16 pattern)."""
    payload: dict[str, Any] = {"session_id": str(session_id)}
    if target_user_id is not None:
        payload["target_user_id"] = str(target_user_id)
    if extra:
        payload.update(extra)
    await append_event(
        action=action,
        actor_user_id=str(actor_user_id),
        resource_type="engagement",
        resource_id=str(session_id),
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Reviewer alignment with W15
# ---------------------------------------------------------------------------


async def _maybe_align_review_assignment(
    session_id: UUID, reviewer_user_id: UUID,
) -> bool:
    """When a member is assigned ``role=reviewer``, point
    ``sessions.review_assigned_to`` at them too — UNLESS the
    engagement is mid-cycle in ``in_review`` with a different
    reviewer already (changing the assignee mid-flight would
    surprise the partner). Returns True when the alignment fired."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT review_state, review_assigned_to
              FROM sessions WHERE id = $1::uuid
            """,
            session_id,
        )
        if not row:
            return False
        state = row["review_state"]
        current = row["review_assigned_to"]
        if state == "in_review" and current and current != reviewer_user_id:
            # Don't disturb an active review cycle.
            return False
        await conn.execute(
            "UPDATE sessions SET review_assigned_to = $2::uuid WHERE id = $1::uuid",
            session_id, reviewer_user_id,
        )
    return True


# ---------------------------------------------------------------------------
# Public API — assign / change / remove / list / get_lead
# ---------------------------------------------------------------------------


async def assign_member(
    session_id: UUID,
    user_id: UUID,
    role: str | EngagementRole,
    assigned_by: UUID,
) -> MembershipResult:
    """Add a member to an engagement (or re-activate a soft-removed
    one). Enforces every W17/D1 invariant up front."""
    role_enum = await _coerce_role(role)
    if role_enum is None:
        return MembershipResult(ok=False, status_code=400, reason=_INVALID_ROLE)

    firm_id = await _load_session_firm(session_id)
    if firm_id is None:
        return MembershipResult(ok=False, status_code=404, reason=_SESSION_NOT_FOUND)
    if not await _can_manage(session_id, assigned_by):
        return MembershipResult(ok=False, status_code=403, reason=_AUTHOR_GATE)
    if not await _is_firm_member(firm_id, user_id):
        return MembershipResult(ok=False, status_code=400, reason=_CROSS_FIRM)

    # Lead-uniqueness gate.
    if role_enum is EngagementRole.LEAD:
        existing_lead = await _active_lead_id(session_id)
        if existing_lead and str(existing_lead) != str(user_id):
            return MembershipResult(
                ok=False, status_code=409, reason=_LEAD_EXISTS,
                extra={"current_lead_user_id": str(existing_lead)},
            )

    async with acquire() as conn:
        # Upsert — re-activates a soft-removed row to the new role.
        row = await conn.fetchrow(
            """
            INSERT INTO engagement_memberships
                (engagement_id, user_id, role, added_by, removed_at)
            VALUES ($1::uuid, $2::uuid, $3, $4::uuid, NULL)
            ON CONFLICT (engagement_id, user_id) DO UPDATE
              SET role = EXCLUDED.role,
                  added_by = EXCLUDED.added_by,
                  removed_at = NULL
            RETURNING id, engagement_id, user_id, role,
                      added_by, added_at, removed_at
            """,
            session_id, user_id, role_enum.value, assigned_by,
        )
        if not row:
            return MembershipResult(ok=False, status_code=500, reason="insert returned no row")

    member = EngagementMember.from_row({**dict(row), "firm_id": firm_id})

    # W15 alignment — only on reviewer.
    aligned = False
    if role_enum is EngagementRole.REVIEWER:
        aligned = await _maybe_align_review_assignment(session_id, user_id)

    await _audit(
        action="engagement.member_assigned",
        actor_user_id=assigned_by,
        session_id=session_id,
        target_user_id=user_id,
        extra={"role": role_enum.value,
               "review_assigned_to_updated": aligned},
    )

    return MembershipResult(
        ok=True, member=member,
        extra={"review_assigned_to_updated": aligned},
    )


async def change_member_role(
    session_id: UUID,
    user_id: UUID,
    new_role: str | EngagementRole,
    actor_id: UUID,
) -> MembershipResult:
    """Change a member's role. Same authorisation + lead-uniqueness
    rules as :func:`assign_member`. Fires ``engagement.member_role_changed``
    (and ``engagement.lead_changed`` when the new role is LEAD)."""
    new_role_enum = await _coerce_role(new_role)
    if new_role_enum is None:
        return MembershipResult(ok=False, status_code=400, reason=_INVALID_ROLE)

    if not await _can_manage(session_id, actor_id):
        return MembershipResult(ok=False, status_code=403, reason=_AUTHOR_GATE)

    existing = await _load_active(session_id, user_id)
    if existing is None:
        return MembershipResult(ok=False, status_code=404, reason=_NOT_FOUND)
    old_role = str(existing["role"])
    if old_role == new_role_enum.value:
        return MembershipResult(
            ok=True,
            member=EngagementMember.from_row(existing),
            extra={"no_op": True},
        )

    # Lead uniqueness.
    if new_role_enum is EngagementRole.LEAD:
        existing_lead = await _active_lead_id(session_id)
        if existing_lead and str(existing_lead) != str(user_id):
            return MembershipResult(
                ok=False, status_code=409, reason=_LEAD_EXISTS,
                extra={"current_lead_user_id": str(existing_lead)},
            )

    # Demoting the only lead → orphan-guard. Reject — you must
    # promote a replacement first.
    if old_role == EngagementRole.LEAD.value and new_role_enum is not EngagementRole.LEAD:
        if not await _has_other_lead(session_id, user_id):
            return MembershipResult(
                ok=False, status_code=409, reason=_LEAD_REMOVAL,
            )

    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE engagement_memberships
               SET role = $3
             WHERE engagement_id = $1::uuid
               AND user_id = $2::uuid
               AND removed_at IS NULL
            RETURNING id, engagement_id, user_id, role,
                      added_by, added_at, removed_at
            """,
            session_id, user_id, new_role_enum.value,
        )
        if not row:
            return MembershipResult(ok=False, status_code=404, reason=_NOT_FOUND)

    member = EngagementMember.from_row(
        {**dict(row), "firm_id": existing["firm_id"]},
    )

    aligned = False
    if new_role_enum is EngagementRole.REVIEWER:
        aligned = await _maybe_align_review_assignment(session_id, user_id)

    await _audit(
        action="engagement.member_role_changed",
        actor_user_id=actor_id,
        session_id=session_id,
        target_user_id=user_id,
        extra={"old_role": old_role, "new_role": new_role_enum.value,
               "review_assigned_to_updated": aligned},
    )
    if new_role_enum is EngagementRole.LEAD:
        await _audit(
            action="engagement.lead_changed",
            actor_user_id=actor_id,
            session_id=session_id,
            target_user_id=user_id,
            extra={"new_lead_user_id": str(user_id)},
        )

    return MembershipResult(ok=True, member=member,
                            extra={"review_assigned_to_updated": aligned})


async def _has_other_lead(session_id: UUID, exclude_user_id: UUID) -> bool:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT 1 FROM engagement_memberships
             WHERE engagement_id = $1::uuid
               AND role = 'lead'
               AND removed_at IS NULL
               AND user_id <> $2::uuid
             LIMIT 1
            """,
            session_id, exclude_user_id,
        )
    return row is not None


async def remove_member(
    session_id: UUID,
    user_id: UUID,
    actor_id: UUID,
) -> MembershipResult:
    """Soft-remove a member. Lead removal requires a replacement
    lead to exist first (W17/D1 invariant). The row stays in the
    table; ``removed_at`` is set so the audit trail is intact."""
    if not await _can_manage(session_id, actor_id):
        return MembershipResult(ok=False, status_code=403, reason=_AUTHOR_GATE)
    existing = await _load_active(session_id, user_id)
    if existing is None:
        return MembershipResult(ok=False, status_code=404, reason=_NOT_FOUND)

    if str(existing["role"]) == EngagementRole.LEAD.value:
        if not await _has_other_lead(session_id, user_id):
            return MembershipResult(ok=False, status_code=409, reason=_LEAD_REMOVAL)

    async with acquire() as conn:
        await conn.execute(
            """
            UPDATE engagement_memberships
               SET removed_at = NOW()
             WHERE engagement_id = $1::uuid
               AND user_id = $2::uuid
               AND removed_at IS NULL
            """,
            session_id, user_id,
        )

    await _audit(
        action="engagement.member_removed",
        actor_user_id=actor_id,
        session_id=session_id,
        target_user_id=user_id,
        extra={"role": existing["role"]},
    )
    return MembershipResult(ok=True)


async def list_members(session_id: UUID) -> list[EngagementMember]:
    """Active members for an engagement, ordered lead-first then by
    assignment time (oldest first)."""
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT em.id, em.engagement_id, em.user_id, em.role,
                   em.added_by, em.added_at, em.removed_at,
                   s.firm_id
              FROM engagement_memberships em
              JOIN sessions s ON s.id = em.engagement_id
             WHERE em.engagement_id = $1::uuid
               AND em.removed_at IS NULL
             ORDER BY
                CASE em.role
                    WHEN 'lead'        THEN 0
                    WHEN 'reviewer'    THEN 1
                    WHEN 'contributor' THEN 2
                    WHEN 'observer'    THEN 3
                    ELSE 9
                END,
                em.added_at ASC
            """,
            session_id,
        )
    return [EngagementMember.from_row(r) for r in rows]


async def get_lead(session_id: UUID) -> EngagementMember | None:
    """Return the active lead row for a session (None when the
    invariant is broken — used by the W17/D1 backfill validator)."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT em.id, em.engagement_id, em.user_id, em.role,
                   em.added_by, em.added_at, em.removed_at,
                   s.firm_id
              FROM engagement_memberships em
              JOIN sessions s ON s.id = em.engagement_id
             WHERE em.engagement_id = $1::uuid
               AND em.role = 'lead'
               AND em.removed_at IS NULL
             LIMIT 1
            """,
            session_id,
        )
    return EngagementMember.from_row(row) if row else None


async def ensure_creator_is_lead(session_id: UUID, creator_id: UUID) -> MembershipResult:
    """Idempotent — used by the session-create flow to install the
    creator as the engagement lead. If the session already has a
    different active lead, returns ok=True with a no-op flag so the
    create flow doesn't fail on a re-run."""
    existing_lead = await _active_lead_id(session_id)
    if existing_lead is not None:
        if str(existing_lead) == str(creator_id):
            return MembershipResult(ok=True, extra={"no_op": True})
        # A different lead already exists — leave it alone but
        # surface the conflict for the caller's awareness.
        return MembershipResult(
            ok=True,
            extra={"no_op": True,
                   "existing_lead_user_id": str(existing_lead)},
        )
    firm_id = await _load_session_firm(session_id)
    if firm_id is None:
        return MembershipResult(ok=False, status_code=404, reason=_SESSION_NOT_FOUND)
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO engagement_memberships
                (engagement_id, user_id, role, added_by, removed_at)
            VALUES ($1::uuid, $2::uuid, 'lead', $2::uuid, NULL)
            ON CONFLICT (engagement_id, user_id) DO UPDATE
              SET role = 'lead', removed_at = NULL
            RETURNING id, engagement_id, user_id, role,
                      added_by, added_at, removed_at
            """,
            session_id, creator_id,
        )
    member = EngagementMember.from_row({**dict(row), "firm_id": firm_id})
    await _audit(
        action="engagement.member_assigned",
        actor_user_id=creator_id,
        session_id=session_id,
        target_user_id=creator_id,
        extra={"role": "lead", "auto_assigned_on_create": True},
    )
    return MembershipResult(ok=True, member=member,
                            extra={"auto_assigned_on_create": True})
