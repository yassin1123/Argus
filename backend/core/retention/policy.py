"""Retention policy + sweep — Phase 5 / Week 23 / Day 2.

Per-firm configurable retention windows. The sweep flags
expired engagements, notifies the firm_admin, waits out a grace
period, then triggers a purge.

Spec-honoured invariants:

  - Default is ``retention_days = NULL`` → keep indefinitely.
    Firms opt-in. No firm's data is auto-deleted out from under
    them just because they didn't read the docs.
  - Nothing vanishes silently. The sweep makes three passes for
    every expired engagement:
      1. flag — set ``retention_flagged_at`` + send a
         ``RETENTION_PURGE_SCHEDULED`` notification to firm_admin
      2. grace — DEFAULT_RETENTION_GRACE_DAYS (14 days) before
         the purge actually runs
      3. purge — call :func:`core.retention.deletion.purge_engagement`
         with ``reason="retention_sweep"``
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from db.connection import acquire

logger = logging.getLogger(__name__)


DEFAULT_RETENTION_GRACE_DAYS = 14
# Two weeks between flag + actual purge. Long enough for a
# firm_admin to extend / cancel; short enough that data doesn't
# linger past expiry indefinitely.


# ---------------------------------------------------------------------------
# Per-firm config
# ---------------------------------------------------------------------------


async def set_firm_retention_days(
    firm_id: str | UUID, retention_days: int | None,
) -> None:
    """Set the per-firm retention window. ``None`` = keep
    indefinitely (the default)."""
    if retention_days is not None:
        if not isinstance(retention_days, int) or retention_days < 7:
            raise ValueError(
                "retention_days must be None or an integer >= 7 "
                "(seven-day minimum prevents accidental same-day "
                f"purges); got {retention_days!r}"
            )
    async with acquire() as conn:
        await conn.execute(
            "UPDATE firms SET retention_days = $2 WHERE id = $1::uuid",
            str(firm_id), retention_days,
        )


async def get_firm_retention_days(firm_id: str | UUID) -> int | None:
    try:
        async with acquire() as conn:
            row = await conn.fetchrow(
                "SELECT retention_days FROM firms WHERE id = $1::uuid",
                str(firm_id),
            )
    except Exception as e:  # noqa: BLE001
        logger.debug("firm retention read failed: %s", e)
        return None
    if not row:
        return None
    val = row["retention_days"]
    return int(val) if val is not None else None


# ---------------------------------------------------------------------------
# Sweep decision logic — pure function, no DB
# ---------------------------------------------------------------------------


@dataclass
class RetentionDecision:
    """The action the sweep takes for one engagement."""

    session_id: str
    firm_id: str
    action: str          # "noop" | "flag" | "purge"
    reason: str
    age_days: float
    retention_days: int | None
    grace_expires_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def decide_retention_action(
    *,
    session_id: str,
    firm_id: str,
    updated_at: datetime,
    retention_days: int | None,
    retention_flagged_at: datetime | None,
    grace_expires_at: datetime | None,
    now: datetime | None = None,
    grace_days: int = DEFAULT_RETENTION_GRACE_DAYS,
) -> RetentionDecision:
    """Decide what the sweep should do for one engagement.

    Three outcomes:
      - ``noop``   — not yet past the retention window
      - ``flag``   — past the window, not yet flagged; flag +
                    schedule grace
      - ``purge``  — flagged, grace expired; call purge_engagement
    """
    now = now or datetime.now(tz=timezone.utc)
    if retention_days is None:
        return RetentionDecision(
            session_id=session_id, firm_id=firm_id,
            action="noop",
            reason="firm retention_days is NULL (keep indefinitely)",
            age_days=0.0, retention_days=None,
        )

    age_seconds = max(0.0, (now - updated_at).total_seconds())
    age_days = age_seconds / 86400.0
    if age_days < retention_days:
        return RetentionDecision(
            session_id=session_id, firm_id=firm_id,
            action="noop",
            reason=(
                f"age {age_days:.1f}d < retention window "
                f"{retention_days}d"
            ),
            age_days=age_days,
            retention_days=retention_days,
        )

    # Past the window. Either flag (first pass) or purge (after grace).
    if retention_flagged_at is None:
        new_grace = now + timedelta(days=grace_days)
        return RetentionDecision(
            session_id=session_id, firm_id=firm_id,
            action="flag",
            reason=(
                f"age {age_days:.1f}d >= retention window "
                f"{retention_days}d; flag + {grace_days}d grace"
            ),
            age_days=age_days,
            retention_days=retention_days,
            grace_expires_at=new_grace.isoformat(),
        )

    # Already flagged. Has the grace expired?
    if grace_expires_at is None or now < grace_expires_at:
        remaining = (
            (grace_expires_at - now).total_seconds() / 86400.0
            if grace_expires_at else float(grace_days)
        )
        return RetentionDecision(
            session_id=session_id, firm_id=firm_id,
            action="noop",
            reason=(
                f"already flagged; grace expires in {remaining:.1f}d"
            ),
            age_days=age_days,
            retention_days=retention_days,
            grace_expires_at=(
                grace_expires_at.isoformat() if grace_expires_at else None
            ),
        )

    return RetentionDecision(
        session_id=session_id, firm_id=firm_id,
        action="purge",
        reason=(
            f"flagged + grace expired; purge approved (reason="
            f"retention_sweep)"
        ),
        age_days=age_days,
        retention_days=retention_days,
        grace_expires_at=grace_expires_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# DB sweep
# ---------------------------------------------------------------------------


async def list_expired_sessions(
    grace_days: int = DEFAULT_RETENTION_GRACE_DAYS,
    *,
    now: datetime | None = None,
) -> list[RetentionDecision]:
    """Walk every firm with a non-NULL retention_days, evaluate
    each session against the policy, return the decisions. The
    sweep runner consumes this list + executes the flag / purge
    actions."""
    now = now or datetime.now(tz=timezone.utc)
    decisions: list[RetentionDecision] = []
    try:
        async with acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT s.id, s.firm_id, s.updated_at,
                       s.retention_flagged_at,
                       s.retention_grace_expires_at,
                       f.retention_days
                  FROM sessions s
                  JOIN firms f ON f.id = s.firm_id
                 WHERE f.retention_days IS NOT NULL
                """
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("retention sweep query failed: %s", e)
        return []
    for r in rows:
        decisions.append(decide_retention_action(
            session_id=str(r["id"]),
            firm_id=str(r["firm_id"]),
            updated_at=r["updated_at"],
            retention_days=r["retention_days"],
            retention_flagged_at=r["retention_flagged_at"],
            grace_expires_at=r["retention_grace_expires_at"],
            now=now, grace_days=grace_days,
        ))
    return decisions


async def mark_flagged(
    session_id: str | UUID, grace_expires_at: datetime,
) -> None:
    async with acquire() as conn:
        await conn.execute(
            """
            UPDATE sessions
               SET retention_flagged_at = NOW(),
                   retention_grace_expires_at = $2
             WHERE id = $1::uuid
            """,
            str(session_id), grace_expires_at,
        )


# ---------------------------------------------------------------------------
# Firm-admin notification (W18 reuse)
# ---------------------------------------------------------------------------


async def notify_firm_admins_of_purge_schedule(
    *,
    firm_id: str | UUID,
    session_id: str | UUID,
    grace_expires_at: datetime,
) -> int:
    """Send a notification to every firm_admin of the firm.
    Returns the number of notifications dispatched. Best-effort —
    a notification-system failure does NOT block the flag.
    """
    # Retention notifications are a system event, not a user-
    # triggered one — we INSERT directly into the notifications
    # table rather than going through the W18 dispatcher (which
    # needs a real actor_id + recipient-resolution machinery).
    delivered = 0
    import json as _json
    from core.notifications.types import NotificationType
    nt = NotificationType.RETENTION_PURGE_SCHEDULED.value
    summary = (
        f"Engagement scheduled for retention purge at "
        f"{grace_expires_at.isoformat()}"
    )
    try:
        async with acquire() as conn:
            admin_rows = await conn.fetch(
                """
                SELECT user_id FROM firm_memberships
                 WHERE firm_id = $1::uuid AND role = 'admin'
                """,
                str(firm_id),
            )
            for r in admin_rows:
                try:
                    await conn.execute(
                        """
                        INSERT INTO notifications
                            (recipient_id, firm_id, notification_type,
                             session_id, source_ref, actor_id, summary,
                             read, email_status)
                        VALUES
                            ($1::uuid, $2::uuid, $3,
                             $4::uuid, $5::jsonb, NULL, $6,
                             FALSE, 'skipped')
                        """,
                        r["user_id"], str(firm_id), nt,
                        str(session_id),
                        _json.dumps({
                            "grace_expires_at": grace_expires_at.isoformat(),
                            "purge_reason": "retention_sweep",
                        }),
                        summary,
                    )
                    delivered += 1
                except Exception as e:  # noqa: BLE001
                    logger.debug(
                        "retention notify insert skipped for user %s: %s",
                        r["user_id"], e,
                    )
    except Exception as e:  # noqa: BLE001
        logger.warning("retention notify failed: %s", e)
    return delivered


__all__ = [
    "DEFAULT_RETENTION_GRACE_DAYS",
    "RetentionDecision",
    "decide_retention_action",
    "get_firm_retention_days",
    "list_expired_sessions",
    "mark_flagged",
    "notify_firm_admins_of_purge_schedule",
    "set_firm_retention_days",
]
