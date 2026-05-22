"""Mention parsing — Phase 4 / Week 16 / Day 2.

Argus's users table has no ``username`` column, only ``email`` +
``full_name``. We canonicalise mentions to an email-prefix slug:
``Sarah.Kim@meridian.com`` → ``@sarah.kim``. The slug is what the
typer writes and what the autocomplete picker emits; the stored
form on the comment row is always the resolved user_id.

Slug rules:
  - lowercase the local-part of the email (the chunk before ``@``);
  - collapse any non-alphanumeric run into a single dot;
  - strip leading/trailing dots so ``..sarah.`` → ``sarah``.

Collision handling: when two firm members produce the same slug
(``sarah.kim@meridian.com`` and ``sarah.kim@brokerage.com`` on the
same firm), we append a deterministic numeric suffix to all but
the earliest member (``sarah.kim``, ``sarah.kim2``, …). The order
is the firm-member list order the caller passes in — the API
layer sorts by ``created_at, id`` so the suffix is stable across
renders.

What we DO NOT do today:
  - Full-name ``@"Quoted Name"`` matching. Single canonical form.
  - Deliver notifications. We emit an internal ``comment.mention``
    event per resolved mention so Week 18 can consume them.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable
from uuid import UUID

logger = logging.getLogger(__name__)


# Slug shape: lowercase alphanumerics, dots between runs. The mention
# token regex is intentionally generous on the input side (we let any
# ``@token`` reach the resolver) and strict on the canonical-form side
# (only the patterns slug_for_user emits will ever resolve).
_MENTION_TOKEN_RE = re.compile(r"@([a-z0-9][a-z0-9._-]{0,63})")


# ---------------------------------------------------------------------------
# Slug derivation
# ---------------------------------------------------------------------------


def slug_for_user(user: dict[str, Any]) -> str:
    """Derive the canonical mention slug for a single user.

    Reads ``user['email']`` (case-insensitive) and returns the dotted
    lowercase slug — same shape the parser matches and the autocomplete
    picker renders. Returns an empty string if the user has no email
    (defensive — the schema marks email NOT NULL but seed scripts can
    bypass that).
    """
    email = (user.get("email") or "").strip()
    if not email or "@" not in email:
        return ""
    local = email.split("@", 1)[0].lower()
    slug = re.sub(r"[^a-z0-9]+", ".", local).strip(".")
    return slug


@dataclass(frozen=True)
class _SlugEntry:
    """Internal: a single slug → user_id binding after collision
    suffixing. ``original`` is the un-suffixed slug (useful for the
    autocomplete picker); ``slug`` is what gets matched in bodies."""

    slug: str
    user_id: str
    original: str


def build_slug_index(firm_members: Iterable[dict[str, Any]]) -> dict[str, str]:
    """Build ``{slug: user_id}`` for an entire firm.

    Collisions are resolved by appending an incrementing numeric
    suffix to the second-and-later members with the same base slug.
    The order of ``firm_members`` decides who keeps the bare slug —
    the API layer sorts by ``(created_at, id)`` ascending so the
    earliest-joined member wins.

    Members without a derivable slug (no email) are skipped silently.
    """
    seen_counts: dict[str, int] = {}
    index: dict[str, str] = {}
    for m in firm_members:
        uid = m.get("user_id") or m.get("id")
        if not uid:
            continue
        base = slug_for_user(m)
        if not base:
            continue
        n = seen_counts.get(base, 0)
        seen_counts[base] = n + 1
        slug = base if n == 0 else f"{base}{n + 1}"
        index[slug] = str(uid)
    return index


# ---------------------------------------------------------------------------
# Mention parsing
# ---------------------------------------------------------------------------


def parse_mentions(
    body: str,
    firm_members: Iterable[dict[str, Any]],
) -> list[UUID]:
    """Extract @slug tokens from ``body`` and resolve to user_ids.

    Returns a de-duplicated list of UUIDs in the order they appear in
    the body. Tokens that don't match any firm member's slug are
    silently dropped — a typo (``@srah.kim``) just leaves the literal
    text and produces no mention.

    ``firm_members`` is an iterable of dicts with at least ``email``
    and ``user_id`` (or ``id``). Callers should pre-filter to members
    of the engagement's firm so cross-firm @-mentions are impossible.
    """
    if not body:
        return []
    index = build_slug_index(firm_members)
    if not index:
        return []
    out: list[UUID] = []
    seen: set[str] = set()
    for match in _MENTION_TOKEN_RE.finditer(body.lower()):
        slug = match.group(1)
        uid = index.get(slug)
        if not uid or uid in seen:
            continue
        try:
            out.append(UUID(uid))
        except (ValueError, TypeError):
            logger.debug("mention slug %r resolved to non-UUID %r", slug, uid)
            continue
        seen.add(uid)
    return out


# ---------------------------------------------------------------------------
# Mention event emission
# ---------------------------------------------------------------------------


async def emit_mention_events(
    *,
    comment_id: UUID | str,
    session_id: UUID | str,
    author_id: UUID | str,
    mentioned_user_ids: list[UUID] | list[str],
) -> None:
    """Append one ``comment.mention`` audit event per mentioned user.

    Today this is the only delivery mechanism — Week 18 will pick up
    these events to drive in-app + email notification. Emission is
    best-effort: failures are swallowed (auditing never breaks the
    request) and the comment-create call still succeeds.
    """
    if not mentioned_user_ids:
        return
    # Import here to avoid a module-load-time circular: audit.queries
    # imports from db.connection which the comments package also touches.
    from audit.queries import append_event

    for uid in mentioned_user_ids:
        try:
            await append_event(
                action="comment.mention",
                actor_user_id=str(author_id),
                resource_type="comment",
                resource_id=str(comment_id),
                payload={
                    "session_id": str(session_id),
                    "mentioned_user_id": str(uid),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("mention event emit failed for %s: %s", uid, exc)


__all__ = [
    "build_slug_index",
    "emit_mention_events",
    "parse_mentions",
    "slug_for_user",
]
