"""Notification email delivery — Phase 4 / Week 18 / Day 3.

Two entry points:

  - :func:`deliver_pending_emails` — scans for every notification
    with ``email_status='pending'`` and processes the batch.
  - :func:`deliver_for_ids` — process a specific list of IDs (the
    inline post-dispatch path: the wiring helpers hand the newly-
    created notification IDs straight in so the recipient sees the
    email immediately rather than on the next scheduler tick).

Both are idempotent: rows whose ``email_status`` is already
``sent``/``skipped``/``failed`` are no-ops on a re-run, so a wedged
worker that re-processes the same batch can't double-send.

Per W18/D3 hard rule "don't send emails for notifications where the
user disabled the email channel": the dispatcher already flips the
status to ``skipped`` on row creation when the user's pref is
email=false. We re-check here as a belt-and-braces guard
(``WHERE email_status = 'pending'`` filters at the SQL layer).

Digest batching ("here are your 5 notifications from today") is
intentionally NOT built in v1 — the spec marks it Phase 5. The
worker's shape supports it: a future scheduled run can collect
pending rows per recipient and emit one digest instead of N
per-notification emails.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from db.connection import acquire

from .adapter import EmailSendResult, get_adapter
from .templates import render_email_for_notification
from ..dispatcher import Notification

logger = logging.getLogger(__name__)


@dataclass
class DeliveryReport:
    """One run's outcome — used by tests + the scheduled worker's
    log line."""

    attempted: int = 0
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "sent": self.sent,
            "failed": self.failed,
            "skipped": self.skipped,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _fetch_pending(
    notification_ids: list[UUID] | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Pull notifications with email_status='pending' (optionally
    constrained to a specific id list) joined with the recipient
    email + firm branding. One round-trip."""
    if notification_ids:
        sql = """
            SELECT n.id, n.recipient_id, n.firm_id, n.notification_type,
                   n.session_id, n.source_ref, n.actor_id, n.summary,
                   n.read, n.read_at, n.created_at, n.email_status,
                   u.email AS recipient_email, u.full_name AS recipient_name,
                   f.name AS firm_name, f.branding AS firm_branding
              FROM notifications n
              JOIN users u ON u.id = n.recipient_id
              JOIN firms f ON f.id = n.firm_id
             WHERE n.email_status = 'pending'
               AND n.id = ANY($1::uuid[])
             ORDER BY n.created_at ASC
             LIMIT $2
        """
        args: list[Any] = [list(notification_ids), int(limit)]
    else:
        sql = """
            SELECT n.id, n.recipient_id, n.firm_id, n.notification_type,
                   n.session_id, n.source_ref, n.actor_id, n.summary,
                   n.read, n.read_at, n.created_at, n.email_status,
                   u.email AS recipient_email, u.full_name AS recipient_name,
                   f.name AS firm_name, f.branding AS firm_branding
              FROM notifications n
              JOIN users u ON u.id = n.recipient_id
              JOIN firms f ON f.id = n.firm_id
             WHERE n.email_status = 'pending'
             ORDER BY n.created_at ASC
             LIMIT $1
        """
        args = [int(limit)]
    async with acquire() as conn:
        rows = await conn.fetch(sql, *args)
    return [dict(r) for r in rows]


async def _mark_status(
    notification_id: str, status: str,
) -> None:
    """Flip a notification's email_status. Idempotent — the
    delivery worker won't pick this row up again until status
    returns to ``pending``."""
    try:
        async with acquire() as conn:
            await conn.execute(
                """
                UPDATE notifications
                   SET email_status = $2
                 WHERE id = $1::uuid
                """,
                notification_id, status,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "delivery: failed to mark %s as %s: %s",
            notification_id, status, exc,
        )


# ---------------------------------------------------------------------------
# Per-row delivery
# ---------------------------------------------------------------------------


async def _deliver_one(row: dict[str, Any], report: DeliveryReport) -> None:
    report.attempted += 1
    notif = Notification.from_row(row)
    recipient_email = row.get("recipient_email") or ""
    if not recipient_email:
        report.skipped += 1
        # No recipient email — mark skipped so we don't keep
        # retrying. The notification still lives in the inbox.
        await _mark_status(notif.id, "skipped")
        report.errors.append(
            f"{notif.id}: recipient has no email address"
        )
        return

    branding = row.get("firm_branding")
    if isinstance(branding, str):
        import json as _json
        try:
            branding = _json.loads(branding)
        except Exception:
            branding = None
    firm_name = row.get("firm_name") or None

    rendered = render_email_for_notification(
        notif, firm_branding=branding if isinstance(branding, dict) else None,
        firm_name=firm_name,
    )

    adapter = get_adapter()
    try:
        result: EmailSendResult = await adapter.send(
            to_email=recipient_email,
            subject=rendered.subject,
            html_body=rendered.html_body,
            text_body=rendered.text_body,
            extra={
                "notification_id": notif.id,
                "notification_type": notif.notification_type,
                "recipient_name": row.get("recipient_name") or "",
            },
        )
    except Exception as exc:  # noqa: BLE001
        # The adapter ABC asks implementations not to raise, but
        # belt-and-braces — a custom adapter that violates the
        # contract still shouldn't crash the worker.
        result = EmailSendResult(
            ok=False, transport="unknown", reason=f"adapter raised: {exc}",
        )

    if result.ok:
        report.sent += 1
        await _mark_status(notif.id, "sent")
    else:
        report.failed += 1
        report.errors.append(f"{notif.id}: {result.reason}")
        await _mark_status(notif.id, "failed")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def deliver_pending_emails(limit: int = 200) -> DeliveryReport:
    """Process every notification with ``email_status='pending'``.
    Used by the (future) scheduled worker."""
    report = DeliveryReport()
    rows = await _fetch_pending(limit=limit)
    for row in rows:
        await _deliver_one(row, report)
    return report


async def deliver_for_ids(
    notification_ids: list[str | UUID],
) -> DeliveryReport:
    """Deliver a specific batch of newly-created notifications.
    Called inline by the wiring helpers so the recipient sees the
    email without waiting for the next scheduler tick. Idempotent —
    IDs whose ``email_status`` is no longer 'pending' are skipped
    by the underlying query."""
    report = DeliveryReport()
    if not notification_ids:
        return report
    ids: list[UUID] = []
    for nid in notification_ids:
        try:
            ids.append(nid if isinstance(nid, UUID) else UUID(str(nid)))
        except (ValueError, TypeError):
            continue
    if not ids:
        return report
    rows = await _fetch_pending(notification_ids=ids)
    for row in rows:
        await _deliver_one(row, report)
    return report


__all__ = ["DeliveryReport", "deliver_for_ids", "deliver_pending_emails"]
