"""Notification type enum + priority ordering — Phase 4 / Week 18 / Day 1.

Nine types covering the W15 + W16 + W17 surfaces. ``TYPE_PRIORITY``
is the ordering used by the dispatcher when collapsing
multi-path duplicates (e.g., a user who's BOTH @-mentioned AND a
thread participant in the same comment — the higher priority wins).

Priority is intentionally subjective consulting-firm prioritisation,
not a graph-theoretic invariant. A change request from the partner
is more urgent than someone replying to a comment; a direct
@-mention is more urgent than being a passive thread participant.
"""

from __future__ import annotations

from enum import Enum


class NotificationType(str, Enum):
    # W16 — comments / mentions
    MENTION = "mention"
    COMMENT_REPLY = "comment_reply"
    # W17 — membership + ownership
    ENGAGEMENT_ASSIGNED = "engagement_assigned"
    SECTION_ASSIGNED = "section_assigned"
    SECTION_NEEDS_REVIEW = "section_needs_review"
    TASK_ASSIGNED = "task_assigned"
    # W15 — review workflow
    REVIEW_REQUESTED = "review_requested"
    CHANGES_REQUESTED = "changes_requested"
    REVIEW_APPROVED = "review_approved"


# Higher number = higher priority. Used by ``dispatch_batch`` to pick
# the winning event when the same recipient qualifies via multiple
# events with the same ``source_ref``.
TYPE_PRIORITY: dict[NotificationType, int] = {
    NotificationType.MENTION:              100,  # personal call-out is the loudest
    NotificationType.CHANGES_REQUESTED:     90,  # partner action gating delivery
    NotificationType.REVIEW_REQUESTED:      85,  # reviewer's queue
    NotificationType.REVIEW_APPROVED:       80,
    NotificationType.SECTION_NEEDS_REVIEW:  70,
    NotificationType.ENGAGEMENT_ASSIGNED:   60,
    NotificationType.SECTION_ASSIGNED:      50,
    NotificationType.TASK_ASSIGNED:         40,
    NotificationType.COMMENT_REPLY:         20,  # ambient, lowest of the lot
}


def priority_of(notification_type: NotificationType | str) -> int:
    """Return the priority score for a type, defaulting to 0 for
    unknown values (so a new type added without priority entry sorts
    lowest rather than crashing the dispatcher)."""
    if isinstance(notification_type, NotificationType):
        return TYPE_PRIORITY.get(notification_type, 0)
    try:
        return TYPE_PRIORITY.get(NotificationType(notification_type), 0)
    except ValueError:
        return 0


__all__ = ["NotificationType", "TYPE_PRIORITY", "priority_of"]
