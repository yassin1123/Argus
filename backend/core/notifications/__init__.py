"""Notification engine — Phase 4 / Week 18.

  Day 1 ships the dispatcher core (this package). Day 2 wires
  W15 / W16 / W17 signals into ``dispatch``. Day 3 swaps the
  email_status='pending' rows for actual email sends. Day 4
  builds the frontend inbox.

Public surface:

  - :class:`NotificationType` — the typed enum (W15 + W16 + W17 events).
  - :func:`default_preference` — per-type (in_app, email) default.
  - :func:`resolve_recipients` — per-type recipient resolver.
  - :func:`render_summary` — human-readable line.
  - :class:`NotificationEvent` / :class:`Notification` — request /
    persisted shapes.
  - :func:`dispatch` / :func:`dispatch_batch` — the entry points.
"""

from .defaults import DEFAULT_PREFERENCES, default_preference
from .dispatcher import (
    Notification,
    NotificationEvent,
    dispatch,
    dispatch_batch,
    mark_read,
)
from .recipients import resolve_recipients
from .summaries import render_summary
from .types import NotificationType, TYPE_PRIORITY
from .wiring import (
    notify_comment_created,
    notify_comment_replied,
    notify_engagement_member_assigned,
    notify_review_transition,
    notify_section_assigned,
    notify_section_needs_review,
    notify_task_assigned,
)

__all__ = [
    "DEFAULT_PREFERENCES",
    "Notification",
    "NotificationEvent",
    "NotificationType",
    "TYPE_PRIORITY",
    "default_preference",
    "dispatch",
    "dispatch_batch",
    "mark_read",
    "notify_comment_created",
    "notify_comment_replied",
    "notify_engagement_member_assigned",
    "notify_review_transition",
    "notify_section_assigned",
    "notify_section_needs_review",
    "notify_task_assigned",
    "render_summary",
    "resolve_recipients",
]
