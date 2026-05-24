"""Email delivery for notifications — Phase 4 / Week 18 / Day 3.

Three pieces:

  - :mod:`.adapter`   — swappable transport (capture for dev/test,
                         SMTP stub for production).
  - :mod:`.templates` — per-type subject + branded HTML + plain text.
  - :mod:`.delivery`  — picks up notifications with
                         ``email_status='pending'``, renders, sends,
                         flips status to ``sent`` / ``failed``.
"""

from .adapter import (
    CaptureEmailAdapter,
    CapturedEmail,
    EmailAdapter,
    EmailSendResult,
    SmtpEmailAdapter,
    get_adapter,
    reset_adapter_for_tests,
)
from .delivery import DeliveryReport, deliver_for_ids, deliver_pending_emails
from .templates import RenderedEmail, action_link, render_email_for_notification

__all__ = [
    "CaptureEmailAdapter",
    "CapturedEmail",
    "DeliveryReport",
    "EmailAdapter",
    "EmailSendResult",
    "RenderedEmail",
    "SmtpEmailAdapter",
    "action_link",
    "deliver_for_ids",
    "deliver_pending_emails",
    "get_adapter",
    "render_email_for_notification",
    "reset_adapter_for_tests",
]
