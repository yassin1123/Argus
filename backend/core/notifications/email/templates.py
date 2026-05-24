"""Notification email templates — Phase 4 / Week 18 / Day 3.

One slim renderer for every notification type. The output is
intentionally short — notification emails are signals, not memos —
and uses the firm's branding (W10's ``firms.branding`` JSONB) for
the header band + footer text.

Per the spec we did NOT reuse the W13 ``EmailBuilder`` here:
W13 produces full memo-shaped emails (one-pager-style with
recommendation + reasons + sources). Notification emails are
two-line postcards. Inlining a tiny template here keeps the diff
small and avoids dragging the memo-renderer's dependencies into
the notification path.

The "View in Argus" link points at the workspace UI; the path is
type-aware (section anchor, claim anchor, review tab, …). When
``ARGUS_BASE_URL`` is unset we fall back to localhost — fine for
dev / capture-adapter tests; the env var must be set when the
SMTP adapter ships.
"""

from __future__ import annotations

import html
import os
from dataclasses import dataclass
from typing import Any

from core.notifications.dispatcher import Notification
from core.notifications.types import NotificationType


@dataclass
class RenderedEmail:
    subject: str
    html_body: str
    text_body: str


# ---------------------------------------------------------------------------
# Link rendering
# ---------------------------------------------------------------------------


def _base_url() -> str:
    # Strip trailing slash so concatenation is predictable.
    return (os.getenv("ARGUS_BASE_URL", "http://localhost:3000") or "").rstrip("/")


def action_link(notif: Notification) -> str:
    """Deep link into the workspace for this notification. Per type:

      - MENTION / COMMENT_REPLY → ``/sessions/{sid}#comment-{comment_id}``
      - SECTION_* → ``/sessions/{sid}#section-{section_path}``
      - TASK_ASSIGNED → ``/sessions/{sid}#task-{task_id}``
      - ENGAGEMENT_ASSIGNED → ``/sessions/{sid}``
      - REVIEW_* → ``/sessions/{sid}`` (the workspace's W15 surface
        lives on the same page)
    """
    base = _base_url()
    sid = notif.session_id or ""
    sref = notif.source_ref or {}
    ntype = notif.notification_type
    if not sid:
        return base or "/"

    if ntype in (NotificationType.MENTION.value, NotificationType.COMMENT_REPLY.value):
        comment_id = sref.get("comment_id")
        if comment_id:
            return f"{base}/sessions/{sid}#comment-{comment_id}"
    if ntype in (NotificationType.SECTION_ASSIGNED.value,
                  NotificationType.SECTION_NEEDS_REVIEW.value):
        section_path = sref.get("section_path")
        if section_path:
            return f"{base}/sessions/{sid}#section-{section_path}"
    if ntype == NotificationType.TASK_ASSIGNED.value:
        task_id = sref.get("task_id")
        if task_id:
            return f"{base}/sessions/{sid}#task-{task_id}"
    return f"{base}/sessions/{sid}"


# ---------------------------------------------------------------------------
# Per-type subject lines
# ---------------------------------------------------------------------------


_SUBJECTS: dict[str, str] = {
    NotificationType.MENTION.value:               "You were mentioned on Argus",
    NotificationType.COMMENT_REPLY.value:         "New reply on a thread you're in",
    NotificationType.ENGAGEMENT_ASSIGNED.value:   "You were added to an engagement",
    NotificationType.SECTION_ASSIGNED.value:      "A section was assigned to you",
    NotificationType.SECTION_NEEDS_REVIEW.value:  "A section needs review",
    NotificationType.TASK_ASSIGNED.value:         "A new task was assigned to you",
    NotificationType.REVIEW_REQUESTED.value:      "An engagement needs your review",
    NotificationType.CHANGES_REQUESTED.value:     "Changes requested on your engagement",
    NotificationType.REVIEW_APPROVED.value:       "Your engagement was approved",
}


def _subject_for(notif: Notification) -> str:
    return _SUBJECTS.get(notif.notification_type, "Argus notification")


# ---------------------------------------------------------------------------
# Branding helpers
# ---------------------------------------------------------------------------


def _branding(firm_branding: dict[str, Any] | None) -> dict[str, str]:
    """Pull the W10 firm-branding fields with sensible defaults so the
    template renders even when a firm hasn't populated branding."""
    b = firm_branding or {}
    return {
        "primary_color": str(b.get("primary_color") or "#111827"),
        "secondary_color": str(b.get("secondary_color") or "#6b7280"),
        "font_family": str(b.get("font_family") or "Inter, system-ui, sans-serif"),
        "footer_text": str(b.get("footer_text") or "Sent by Argus on behalf of your firm."),
        "logo_url": str(b.get("logo_url") or ""),
    }


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


_HTML_SHELL = """\
<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>{subject}</title>
</head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:{font_family};color:#111827;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:24px 0;">
<tr><td align="center">
<table role="presentation" width="560" cellpadding="0" cellspacing="0"
       style="background:#ffffff;border-radius:8px;overflow:hidden;
              box-shadow:0 1px 3px rgba(0,0,0,0.06);">
<tr><td style="padding:14px 20px;background:{primary_color};color:#ffffff;
                font-size:13px;font-weight:600;letter-spacing:0.4px;
                text-transform:uppercase;">
{header}
</td></tr>
<tr><td style="padding:24px 24px 16px;font-size:15px;line-height:1.5;">
<p style="margin:0 0 14px;">{summary}</p>
<p style="margin:18px 0 0;">
<a href="{action_url}" data-testid="view-in-argus"
   style="display:inline-block;padding:8px 16px;background:{primary_color};
          color:#ffffff;text-decoration:none;border-radius:6px;font-size:13px;
          font-weight:600;">View in Argus</a>
</p>
</td></tr>
<tr><td style="padding:14px 24px 18px;border-top:1px solid #e5e7eb;
                font-size:11px;color:{secondary_color};line-height:1.5;">
{footer_text}<br>
You can change which notifications you receive in your Argus preferences.
</td></tr>
</table></td></tr></table>
</body></html>
"""


_TEXT_SHELL = """\
{summary}

View in Argus: {action_url}

---
{footer_text}
You can change which notifications you receive in your Argus preferences.
"""


def render_email_for_notification(
    notif: Notification,
    *,
    firm_branding: dict[str, Any] | None = None,
    firm_name: str | None = None,
) -> RenderedEmail:
    """Render the subject + HTML + plain-text bodies for one
    notification row. Branded with the firm's colours + footer when
    supplied; falls back to safe defaults when not."""
    branding = _branding(firm_branding)
    subject = _subject_for(notif)
    action_url = action_link(notif)
    header = html.escape((firm_name or "Argus")).upper()

    html_body = _HTML_SHELL.format(
        subject=html.escape(subject),
        header=header,
        summary=html.escape(notif.summary),
        action_url=html.escape(action_url, quote=True),
        primary_color=branding["primary_color"],
        secondary_color=branding["secondary_color"],
        font_family=branding["font_family"],
        footer_text=html.escape(branding["footer_text"]),
    )
    text_body = _TEXT_SHELL.format(
        summary=notif.summary,
        action_url=action_url,
        footer_text=branding["footer_text"],
    )
    return RenderedEmail(subject=subject, html_body=html_body, text_body=text_body)


__all__ = ["RenderedEmail", "action_link", "render_email_for_notification"]
