"""Default notification preferences — Phase 4 / Week 18 / Day 1.

Per-type (in_app, email) tuple. The dispatcher reads
``notification_preferences`` first; when no row exists for
``(user_id, notification_type)`` it falls back to these defaults.

Design choice (matches the spec):

  - High-signal types (mention, review_requested, changes_requested,
    review_approved) → both in_app + email.
  - Lower-signal types (section_assigned, section_needs_review,
    comment_reply, task_assigned) → in_app only by default; users
    can opt into email per type if they want.
  - engagement_assigned → both (rare event, worth an email).

In-app is on for every type by default — the inbox is supposed to
be complete. Email defaults intentionally err quieter; W18/D3 will
ship the actual sender and we don't want to spam every user on
day one.
"""

from __future__ import annotations

from .types import NotificationType


# (in_app, email)
DEFAULT_PREFERENCES: dict[NotificationType, tuple[bool, bool]] = {
    # High-signal — both channels on.
    NotificationType.MENTION:              (True, True),
    NotificationType.REVIEW_REQUESTED:     (True, True),
    NotificationType.CHANGES_REQUESTED:    (True, True),
    NotificationType.REVIEW_APPROVED:      (True, True),
    NotificationType.ENGAGEMENT_ASSIGNED:  (True, True),
    # Lower-signal — in-app only by default.
    NotificationType.SECTION_ASSIGNED:     (True, False),
    NotificationType.SECTION_NEEDS_REVIEW: (True, False),
    NotificationType.COMMENT_REPLY:        (True, False),
    NotificationType.TASK_ASSIGNED:        (True, False),
}


def default_preference(
    notification_type: NotificationType | str,
) -> tuple[bool, bool]:
    """Return ``(in_app, email)`` for a notification type, falling
    back to ``(True, False)`` (in-app on, email off) for unknown
    types so a newly-added type still notifies in-app while we
    decide whether email's appropriate."""
    if isinstance(notification_type, NotificationType):
        return DEFAULT_PREFERENCES.get(notification_type, (True, False))
    try:
        return DEFAULT_PREFERENCES.get(
            NotificationType(notification_type), (True, False),
        )
    except ValueError:
        return (True, False)


__all__ = ["DEFAULT_PREFERENCES", "default_preference"]
