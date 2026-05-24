"""W15/W16/W17 → notifications wiring — Phase 4 / Week 18 / Day 2.

One narrow helper per domain action. Each helper:

  - Builds the right :class:`NotificationEvent`(s) with a stable
    ``dedup_key`` so cross-type collapse works deterministically.
  - Calls :func:`dispatch` / :func:`dispatch_batch`.
  - Catches every exception and logs it. **Notification failure
    never propagates** — the core action (comment / review /
    assignment) already committed by the time we got here, and
    the W18/D2 hard rule says "don't let a notification failure
    roll back the core action".

The dispatcher itself handles actor exclusion + preferences +
dedup. These helpers just bridge domain-shaped inputs (comment
rows, review records, assignment rows) into the typed event
shape.

Engagement metadata (title) is resolved on demand from the
sessions table; the title is denormalised onto the summary so
the inbox row stays human-readable even after the engagement
title changes upstream.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from db.connection import acquire

from .dispatcher import Notification, NotificationEvent, dispatch, dispatch_batch
from .types import NotificationType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Small DB helper
# ---------------------------------------------------------------------------


async def _load_engagement_title(session_id: UUID) -> str:
    try:
        async with acquire() as conn:
            row = await conn.fetchrow(
                "SELECT title FROM sessions WHERE id = $1::uuid", session_id,
            )
        return str(row["title"]) if row and row["title"] else ""
    except Exception as exc:  # noqa: BLE001
        logger.debug("wiring: engagement title lookup failed: %s", exc)
        return ""


async def _safe_dispatch(
    fn: str, events: list[NotificationEvent],
) -> list[Notification]:
    """Wrapper that swallows + logs every dispatcher exception so the
    core action's caller never sees one. Per W18/D2 hard rule.

    W18/D3: after the dispatcher persists the notification rows
    (with email_status='pending' for users whose pref enabled
    email), kick off inline email delivery for the new IDs. The
    delivery worker is also exception-safe; failures flip rows to
    'failed' rather than propagating."""
    try:
        if len(events) == 1:
            created = await dispatch(events[0])
        else:
            created = await dispatch_batch(events)
    except Exception as exc:  # noqa: BLE001
        logger.warning("notification wiring %s failed: %s", fn, exc)
        return []

    # Inline email delivery for any rows that landed in 'pending'.
    if created:
        try:
            pending_ids = [n.id for n in created if n.email_status == "pending"]
            if pending_ids:
                # Local import — keep the wiring module's import
                # cost low and avoid a circular at module load.
                from .email.delivery import deliver_for_ids
                await deliver_for_ids(pending_ids)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "notification wiring %s: inline email delivery failed: %s",
                fn, exc,
            )

    return created


# ---------------------------------------------------------------------------
# W16 — comments
# ---------------------------------------------------------------------------


async def notify_comment_created(
    *,
    session_id: UUID,
    firm_id: UUID,
    author_id: UUID,
    comment_id: str,
    body: str,
    anchor_ref: dict[str, Any] | None,
    mentioned_user_ids: list[str] | None,
) -> list[Notification]:
    """Root comment: fire one MENTION event per @-tagged user.
    No COMMENT_REPLY here — there's no parent yet."""
    mention_ids = mentioned_user_ids or []
    if not mention_ids:
        return []
    title = await _load_engagement_title(session_id)
    section_path = (anchor_ref or {}).get("section_path")
    event = NotificationEvent(
        notification_type=NotificationType.MENTION,
        session_id=session_id, firm_id=firm_id, actor_id=author_id,
        source_ref={"comment_id": comment_id},
        dedup_key=f"comment:{comment_id}",
        context={
            "mentioned_user_ids": mention_ids,
            "engagement_title": title,
            "section_path": section_path,
            "body_preview": (body or "")[:120],
        },
    )
    return await _safe_dispatch("notify_comment_created", [event])


async def notify_comment_replied(
    *,
    session_id: UUID,
    firm_id: UUID,
    author_id: UUID,
    comment_id: str,
    root_comment_id: str,
    body: str,
    anchor_ref: dict[str, Any] | None,
    mentioned_user_ids: list[str] | None,
) -> list[Notification]:
    """Reply: fire COMMENT_REPLY for thread participants + (if any
    mentions) MENTION for the tagged users. dispatch_batch collapses
    via dedup_key=comment:<reply_id> so a participant who's also
    mentioned only gets one notification (MENTION wins)."""
    title = await _load_engagement_title(session_id)
    section_path = (anchor_ref or {}).get("section_path")
    body_preview = (body or "")[:120]
    dedup_key = f"comment:{comment_id}"

    events: list[NotificationEvent] = [
        NotificationEvent(
            notification_type=NotificationType.COMMENT_REPLY,
            session_id=session_id, firm_id=firm_id, actor_id=author_id,
            source_ref={"comment_id": comment_id,
                         "root_comment_id": root_comment_id},
            dedup_key=dedup_key,
            context={
                "root_comment_id": root_comment_id,
                "engagement_title": title,
                "section_path": section_path,
                "body_preview": body_preview,
            },
        ),
    ]
    mention_ids = mentioned_user_ids or []
    if mention_ids:
        events.append(NotificationEvent(
            notification_type=NotificationType.MENTION,
            session_id=session_id, firm_id=firm_id, actor_id=author_id,
            source_ref={"comment_id": comment_id},
            dedup_key=dedup_key,
            context={
                "mentioned_user_ids": mention_ids,
                "engagement_title": title,
                "section_path": section_path,
                "body_preview": body_preview,
            },
        ))
    return await _safe_dispatch("notify_comment_replied", events)


# ---------------------------------------------------------------------------
# W15 — review workflow
# ---------------------------------------------------------------------------


# Map ReviewAction.value → NotificationType. Actions that don't
# have a notification surface (reopen, mark_delivered, auto_revert)
# are absent from the map; the wiring helper no-ops cleanly on
# them. ``resubmit`` is treated as a fresh REVIEW_REQUESTED
# because the reviewer needs to know the work is back in their
# queue — same surface as the initial submission.
_REVIEW_NOTIFICATION: dict[str, NotificationType] = {
    "submit_for_review": NotificationType.REVIEW_REQUESTED,
    "resubmit":          NotificationType.REVIEW_REQUESTED,
    "request_changes":   NotificationType.CHANGES_REQUESTED,
    "approve":           NotificationType.REVIEW_APPROVED,
}


async def notify_review_transition(
    *,
    session_id: UUID,
    firm_id: UUID,
    actor_id: UUID,
    action: str,
    review_record_id: str | None,
    feedback: dict[str, Any] | None = None,
) -> list[Notification]:
    """Wire a W15 review transition. ``action`` is the ReviewAction's
    string value (e.g. ``submit_for_review``); unmapped actions
    no-op."""
    notif_type = _REVIEW_NOTIFICATION.get(action)
    if notif_type is None:
        return []
    title = await _load_engagement_title(session_id)
    severity = (feedback or {}).get("severity") if isinstance(feedback, dict) else None
    event = NotificationEvent(
        notification_type=notif_type,
        session_id=session_id, firm_id=firm_id, actor_id=actor_id,
        source_ref={"review_record_id": review_record_id} if review_record_id
                    else {"session_id": str(session_id)},
        dedup_key=f"review:{review_record_id or session_id}",
        context={
            "engagement_title": title,
            "severity": severity,
        },
    )
    return await _safe_dispatch("notify_review_transition", [event])


# ---------------------------------------------------------------------------
# W17 — membership / sections / tasks
# ---------------------------------------------------------------------------


async def notify_engagement_member_assigned(
    *,
    session_id: UUID,
    firm_id: UUID,
    actor_id: UUID,
    assigned_user_id: UUID,
    role: str,
) -> list[Notification]:
    title = await _load_engagement_title(session_id)
    event = NotificationEvent(
        notification_type=NotificationType.ENGAGEMENT_ASSIGNED,
        session_id=session_id, firm_id=firm_id, actor_id=actor_id,
        source_ref={"engagement_id": str(session_id), "role": role},
        dedup_key=f"membership:{session_id}:{assigned_user_id}",
        context={
            "assigned_to": str(assigned_user_id),
            "engagement_title": title,
            "role": role,
        },
    )
    return await _safe_dispatch("notify_engagement_member_assigned", [event])


async def notify_section_assigned(
    *,
    session_id: UUID,
    firm_id: UUID,
    actor_id: UUID,
    section_path: str,
    assigned_user_id: UUID,
) -> list[Notification]:
    title = await _load_engagement_title(session_id)
    event = NotificationEvent(
        notification_type=NotificationType.SECTION_ASSIGNED,
        session_id=session_id, firm_id=firm_id, actor_id=actor_id,
        source_ref={"section_path": section_path},
        dedup_key=f"section_assign:{session_id}:{section_path}:{assigned_user_id}",
        context={
            "assigned_to": str(assigned_user_id),
            "section_path": section_path,
            "engagement_title": title,
        },
    )
    return await _safe_dispatch("notify_section_assigned", [event])


async def notify_section_needs_review(
    *,
    session_id: UUID,
    firm_id: UUID,
    actor_id: UUID,
    section_path: str,
) -> list[Notification]:
    """Fires when a section's status flips to needs_review. Targets
    the engagement lead (per W18/D1 recipient resolver). Actor
    exclusion means the owner who flipped the status won't get a
    notification when they ARE the lead."""
    title = await _load_engagement_title(session_id)
    event = NotificationEvent(
        notification_type=NotificationType.SECTION_NEEDS_REVIEW,
        session_id=session_id, firm_id=firm_id, actor_id=actor_id,
        source_ref={"section_path": section_path},
        dedup_key=f"section_needs_review:{session_id}:{section_path}",
        context={
            "section_path": section_path,
            "engagement_title": title,
        },
    )
    return await _safe_dispatch("notify_section_needs_review", [event])


async def notify_version_restored(
    *,
    session_id: UUID,
    firm_id: UUID,
    actor_id: UUID,
    restored_version_number: int,
    new_version_number: int,
    reverted_from_approved: bool,
) -> list[Notification]:
    """W19/D2: notify the engagement lead that a prior version was
    restored. The recipient resolver returns the lead; actor
    exclusion means a lead restoring their own engagement won't
    notify themselves."""
    title = await _load_engagement_title(session_id)
    event = NotificationEvent(
        notification_type=NotificationType.VERSION_RESTORED,
        session_id=session_id, firm_id=firm_id, actor_id=actor_id,
        source_ref={
            "restored_version_number": restored_version_number,
            "new_version_number": new_version_number,
        },
        dedup_key=f"version_restored:{session_id}:{new_version_number}",
        context={
            "engagement_title": title,
            "restored_version_number": restored_version_number,
            "reverted_from_approved": reverted_from_approved,
        },
    )
    return await _safe_dispatch("notify_version_restored", [event])


async def notify_task_assigned(
    *,
    session_id: UUID,
    firm_id: UUID,
    actor_id: UUID,
    task_id: str,
    task_title: str,
    assigned_user_id: UUID,
) -> list[Notification]:
    title = await _load_engagement_title(session_id)
    event = NotificationEvent(
        notification_type=NotificationType.TASK_ASSIGNED,
        session_id=session_id, firm_id=firm_id, actor_id=actor_id,
        source_ref={"task_id": task_id},
        dedup_key=f"task:{task_id}",
        context={
            "assigned_to": str(assigned_user_id),
            "task_title": task_title,
            "engagement_title": title,
        },
    )
    return await _safe_dispatch("notify_task_assigned", [event])


__all__ = [
    "notify_comment_created",
    "notify_comment_replied",
    "notify_engagement_member_assigned",
    "notify_review_transition",
    "notify_section_assigned",
    "notify_section_needs_review",
    "notify_task_assigned",
    "notify_version_restored",
]
