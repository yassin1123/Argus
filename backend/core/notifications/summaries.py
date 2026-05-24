"""Notification summary rendering — Phase 4 / Week 18 / Day 1.

One human-readable line per notification type. ``render_summary`` is
deliberately data-in, string-out — the dispatcher passes the actor
name + a context dict and gets a sentence back. No I18n today (the
Argus surface is English-only); when localisation lands the summary
strings move into a catalog and the dispatcher passes a locale.
"""

from __future__ import annotations

from typing import Any

from .types import NotificationType


def _engagement_label(context: dict[str, Any]) -> str:
    return str(context.get("engagement_title") or "an engagement")


def _section_label(context: dict[str, Any]) -> str:
    sp = context.get("section_path")
    return f" · {sp}" if sp else ""


def _truncate(s: str | None, n: int = 80) -> str:
    if not s:
        return ""
    s = s.strip()
    return s if len(s) <= n else f"{s[:n].rstrip()}…"


def render_summary(
    notification_type: NotificationType | str,
    actor_name: str,
    context: dict[str, Any],
) -> str:
    """Return a single-line summary suitable for the inbox row.

    ``context`` is the open-ended bag the dispatcher carries through
    from the source event. Per-type fields used:

      - ``engagement_title`` — the session title (always nice to surface).
      - ``section_path`` — for section / claim / text_range anchors.
      - ``body_preview`` — for MENTION / COMMENT_REPLY.
      - ``severity`` — for CHANGES_REQUESTED.
      - ``task_title`` — for TASK_ASSIGNED.
    """
    t = (notification_type if isinstance(notification_type, NotificationType)
         else NotificationType(notification_type))
    actor = actor_name or "Someone"
    eng = _engagement_label(context)
    sec = _section_label(context)
    body = _truncate(context.get("body_preview"))

    if t is NotificationType.MENTION:
        suffix = f": “{body}”" if body else ""
        return f"{actor} mentioned you in a comment on {eng}{sec}{suffix}"
    if t is NotificationType.COMMENT_REPLY:
        suffix = f": “{body}”" if body else ""
        return f"{actor} replied on a thread you're in — {eng}{sec}{suffix}"
    if t is NotificationType.ENGAGEMENT_ASSIGNED:
        role = context.get("role")
        role_part = f" as {role}" if role else ""
        return f"{actor} added you to {eng}{role_part}"
    if t is NotificationType.SECTION_ASSIGNED:
        return f"{actor} assigned you {context.get('section_path') or 'a section'} on {eng}"
    if t is NotificationType.SECTION_NEEDS_REVIEW:
        return (
            f"{actor} marked {context.get('section_path') or 'a section'} "
            f"as needs review on {eng}"
        )
    if t is NotificationType.TASK_ASSIGNED:
        title = context.get("task_title") or "a task"
        return f"{actor} assigned you “{_truncate(title)}” on {eng}"
    if t is NotificationType.REVIEW_REQUESTED:
        return f"{actor} submitted {eng} for your review"
    if t is NotificationType.CHANGES_REQUESTED:
        sev = context.get("severity")
        sev_part = f" [{sev}]" if sev else ""
        return f"{actor} requested changes on {eng}{sev_part}"
    if t is NotificationType.REVIEW_APPROVED:
        return f"{actor} approved {eng}"
    # Unknown type — surface a safe fallback rather than crash.
    return f"{actor} triggered {str(t)} on {eng}"


__all__ = ["render_summary"]
