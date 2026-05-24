"""Email transport adapter — Phase 4 / Week 18 / Day 3.

Two implementations behind one ABC:

  - :class:`CaptureEmailAdapter` — dev/test default. Stores every
    "sent" email in an in-memory list so tests can assert "this
    email would have been delivered" without standing up SMTP.
  - :class:`SmtpEmailAdapter` — production stub. Reads env config
    and connects to a real SMTP server. Not exercised in dev; the
    spec marks this as "wired when pilots start" — today's scope
    is the interface + the capture path.

Selection: ``ARGUS_EMAIL_ADAPTER`` env var. ``capture`` (default)
returns the singleton capture adapter; ``smtp`` returns an
SmtpEmailAdapter. Any unrecognised value falls back to capture
(non-fatal — we don't want a typo to crash the dispatcher).

The :func:`get_adapter` cache is intentionally process-wide; tests
that need a fresh capture can call :func:`reset_adapter_for_tests`.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EmailSendResult:
    """Return shape from :meth:`EmailAdapter.send`. ``ok`` is True
    only when the transport accepted the message; ``reason`` is the
    transport-level error on failure."""

    ok: bool
    transport: str        # 'capture' | 'smtp'
    message_id: str | None = None
    reason: str = ""


@dataclass
class CapturedEmail:
    """One captured email — the record of what would have been sent."""

    to_email: str
    subject: str
    html_body: str
    text_body: str
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Adapter ABC
# ---------------------------------------------------------------------------


class EmailAdapter(ABC):
    """Transport interface. Implementations decide whether to capture
    in memory (dev/test), POST to a transactional API, or open an
    SMTP session."""

    transport: str = "abstract"

    @abstractmethod
    async def send(
        self,
        *,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
        extra: dict[str, Any] | None = None,
    ) -> EmailSendResult:
        """Send (or capture) one email. Implementations should NEVER
        raise on transport errors — return ``EmailSendResult(ok=False,
        reason=...)`` so the delivery worker can flip the row's
        ``email_status`` to 'failed' without burying the actual
        cause in an exception trace."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Capture (dev/test default)
# ---------------------------------------------------------------------------


class CaptureEmailAdapter(EmailAdapter):
    """In-memory capture. Holds every "sent" email in
    :attr:`captured` so tests can introspect."""

    transport = "capture"

    def __init__(self) -> None:
        self.captured: list[CapturedEmail] = []

    async def send(
        self,
        *,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
        extra: dict[str, Any] | None = None,
    ) -> EmailSendResult:
        if not to_email:
            return EmailSendResult(
                ok=False, transport=self.transport,
                reason="no recipient email",
            )
        record = CapturedEmail(
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            extra=dict(extra or {}),
        )
        self.captured.append(record)
        return EmailSendResult(
            ok=True, transport=self.transport,
            message_id=f"capture-{len(self.captured)}",
        )

    def clear(self) -> None:
        self.captured.clear()


# ---------------------------------------------------------------------------
# SMTP (production stub)
# ---------------------------------------------------------------------------


class SmtpEmailAdapter(EmailAdapter):
    """Production transport stub. Reads SMTP_* env vars; the actual
    connect/send code is intentionally left unimplemented in v1 per
    the W18/D3 spec ("wired when pilots start") — we ship the
    interface + the dev capture path now so the rest of the
    pipeline doesn't have to change when a real transport lands.

    The unimplemented branch returns a clean
    ``EmailSendResult(ok=False, reason=...)`` so the delivery worker
    treats it as a transient failure and moves on rather than
    crashing.
    """

    transport = "smtp"

    def __init__(self) -> None:
        self.host = os.getenv("SMTP_HOST", "")
        self.port = int(os.getenv("SMTP_PORT", "587"))
        self.username = os.getenv("SMTP_USERNAME", "")
        self.password = os.getenv("SMTP_PASSWORD", "")
        self.from_email = os.getenv("SMTP_FROM", "notifications@argus.invalid")

    async def send(
        self,
        *,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
        extra: dict[str, Any] | None = None,
    ) -> EmailSendResult:
        if not self.host:
            return EmailSendResult(
                ok=False, transport=self.transport,
                reason="SMTP_HOST not configured; production transport not wired",
            )
        # Real smtplib send goes here when pilots ship. Until then,
        # surface the configuration gap explicitly so an operator
        # who set ARGUS_EMAIL_ADAPTER=smtp without finishing the
        # config gets a clear error in the delivery report.
        logger.warning(
            "SmtpEmailAdapter.send invoked but the production "
            "transport is not implemented in v1; treating as failure",
        )
        return EmailSendResult(
            ok=False, transport=self.transport,
            reason="SMTP transport not implemented in v1",
        )


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


_ADAPTER_CACHE: EmailAdapter | None = None


def _build_adapter() -> EmailAdapter:
    choice = os.getenv("ARGUS_EMAIL_ADAPTER", "capture").lower()
    if choice == "smtp":
        return SmtpEmailAdapter()
    if choice != "capture":
        logger.warning(
            "Unknown ARGUS_EMAIL_ADAPTER=%r — falling back to capture", choice,
        )
    return CaptureEmailAdapter()


def get_adapter() -> EmailAdapter:
    """Return the process-wide adapter singleton, building it on
    first access. Tests can swap it via
    :func:`reset_adapter_for_tests`."""
    global _ADAPTER_CACHE
    if _ADAPTER_CACHE is None:
        _ADAPTER_CACHE = _build_adapter()
    return _ADAPTER_CACHE


def reset_adapter_for_tests(adapter: EmailAdapter | None = None) -> EmailAdapter:
    """Replace the process-wide adapter. Pass an instance to use a
    specific adapter; pass nothing to clear the cache (the next
    :func:`get_adapter` rebuilds from env)."""
    global _ADAPTER_CACHE
    _ADAPTER_CACHE = adapter
    if _ADAPTER_CACHE is None:
        _ADAPTER_CACHE = _build_adapter()
    return _ADAPTER_CACHE


__all__ = [
    "CaptureEmailAdapter",
    "CapturedEmail",
    "EmailAdapter",
    "EmailSendResult",
    "SmtpEmailAdapter",
    "get_adapter",
    "reset_adapter_for_tests",
]
