"""Comment CRUD + thread resolve service — Phase 4 / Week 16 / Day 1.

Service layer only — no API surface today. W16/D2 wires the
endpoints + the read-side hydration; W16/D3+ adds the frontend.

The service enforces five contracts per W16/D1 spec hard rules:

  - Replies inherit the root's anchor at insert time (the schema
    requires anchor_type / anchor_ref non-null on every row; the
    service copies from root → reply rather than burdening the API
    caller with the duplication).
  - Resolve operates on root comments only. Resolving a reply is
    rejected with a clean reason — the W16/D2 frontend should
    surface "resolve the thread, not the reply".
  - Edits are author-only. The service refuses edits from any
    other user.
  - Soft delete only. ``deleted_at`` is set; the row stays for
    audit-trail integrity.
  - Mentions are stored as user_id strings; delivery is W18.

Anchor validation runs at create-time only. The W16/D1 orphan
detector handles drift after a section is deepened — the comment
remains valid until then.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from db.connection import acquire

from .anchors import AnchorType, AnchorValidationResult, validate_anchor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class CommentResult:
    """Return shape from every service entry. ``ok`` is True only
    when the write actually committed; on failure ``status_code``
    + ``reason`` map to the appropriate HTTP code so the W16/D2 API
    layer can forward them directly."""

    ok: bool
    comment_id: str | None = None
    status_code: int = 200
    reason: str = ""
    row: dict[str, Any] | None = None


# Error shapes used as canonical reason strings. Keep short + safe
# for 4xx response bodies.
_NOT_FOUND = "comment not found"
_AUTHOR_ONLY = "edit is restricted to the comment author"
_DELETE_AUTHOR_OR_ADMIN = "delete is restricted to the comment author or a firm admin"
_REPLY_NOT_ROOT = "resolve operates on root comments only — resolve the thread, not the reply"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row: Any) -> dict[str, Any]:
    d = dict(row)
    for key in ("anchor_ref", "mentioned_user_ids"):
        v = d.get(key)
        if isinstance(v, str):
            try:
                d[key] = json.loads(v)
            except Exception:
                d[key] = None
    return d


async def _load_session_firm(session_id: UUID) -> UUID | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT firm_id FROM sessions WHERE id = $1::uuid", session_id,
        )
    return row["firm_id"] if row else None


async def _load_session_payload(session_id: UUID) -> dict[str, Any]:
    """Pull a merged ``reports`` + ``consulting_payload`` shape so
    the anchor validator can resolve section / claim references.
    Returns an empty dict if no report exists yet — the validator
    will then surface a clean reason."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT recommendation, confidence_level, summary, key_reasons, risks,
                   counterarguments, next_steps, sources, caveats, consulting_payload
              FROM reports WHERE session_id = $1::uuid
            """,
            session_id,
        )
    if not row:
        return {}
    out: dict[str, Any] = {}
    for k in row.keys():
        if k == "consulting_payload":
            continue
        v = row[k]
        if isinstance(v, str) and k in (
            "key_reasons", "risks", "counterarguments", "next_steps", "sources",
        ):
            try:
                v = json.loads(v)
                if isinstance(v, str):
                    # Tolerate the W13/D5 double-encoded payload edge case.
                    try:
                        v_inner = json.loads(v)
                        if isinstance(v_inner, (list, dict)):
                            v = v_inner
                    except Exception:
                        pass
            except Exception:
                pass
        out[k] = v
    cp = row["consulting_payload"]
    if isinstance(cp, str):
        try:
            cp = json.loads(cp)
        except Exception:
            cp = {}
    if isinstance(cp, dict):
        out.update(cp)
    return out


async def _load_session_artifacts(session_id: UUID) -> list[dict[str, Any]]:
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, artifact_type, format, status
              FROM export_artifacts
             WHERE session_id = $1::uuid
            """,
            session_id,
        )
    return [
        {"id": str(r["id"]), "artifact_type": r["artifact_type"],
         "format": r["format"], "status": r["status"]}
        for r in rows
    ]


async def _load_comment(comment_id: UUID) -> dict[str, Any] | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, session_id, firm_id, parent_comment_id, anchor_type,
                   anchor_ref, body, mentioned_user_ids, author_id,
                   resolved, resolved_by, resolved_at,
                   created_at, updated_at, edited_at, deleted_at
              FROM comments WHERE id = $1::uuid
            """,
            comment_id,
        )
    return _row_to_dict(row) if row else None


async def _actor_is_firm_admin(firm_id: UUID, actor_id: UUID) -> bool:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT role FROM firm_memberships
             WHERE firm_id = $1::uuid AND user_id = $2::uuid
            """,
            firm_id, actor_id,
        )
    return bool(row) and str(row["role"]).lower() == "admin"


def _serialise_mentions(mentions: list[str] | None) -> str:
    """Coerce mentioned_user_ids into a JSON-encoded list of stripped
    strings (drops blanks). Idempotent — re-serialising the result
    yields the same bytes."""
    if not mentions:
        return "[]"
    out: list[str] = []
    for m in mentions:
        if not isinstance(m, str):
            continue
        s = m.strip()
        if s and s not in out:
            out.append(s)
    return json.dumps(out)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


async def create_comment(
    session_id: UUID,
    author_id: UUID,
    anchor_type: AnchorType | str,
    anchor_ref: dict[str, Any] | None,
    body: str,
    mentioned_user_ids: list[str] | None = None,
) -> CommentResult:
    """Create a root (thread-starting) comment anchored to a session
    target. Returns ``CommentResult`` with the row + a structured
    error on validation / auth failure.
    """
    if not body or not body.strip():
        return CommentResult(ok=False, status_code=400, reason="body cannot be empty")

    firm_id = await _load_session_firm(session_id)
    if firm_id is None:
        return CommentResult(ok=False, status_code=404, reason="session not found")

    payload = await _load_session_payload(session_id)
    artifacts = await _load_session_artifacts(session_id)
    auth: AnchorValidationResult = validate_anchor(
        anchor_type, anchor_ref, payload=payload, artifacts=artifacts,
    )
    if not auth.ok:
        return CommentResult(ok=False, status_code=400, reason=auth.reason)

    anchor_type_value = (
        anchor_type.value if isinstance(anchor_type, AnchorType) else str(anchor_type)
    )

    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO comments (
                session_id, firm_id, parent_comment_id,
                anchor_type, anchor_ref, body, mentioned_user_ids,
                author_id
            ) VALUES (
                $1::uuid, $2::uuid, NULL,
                $3, $4::jsonb, $5, $6::jsonb,
                $7::uuid
            )
            RETURNING id, session_id, firm_id, parent_comment_id, anchor_type,
                      anchor_ref, body, mentioned_user_ids, author_id,
                      resolved, resolved_by, resolved_at,
                      created_at, updated_at, edited_at, deleted_at
            """,
            session_id, firm_id,
            anchor_type_value,
            json.dumps(anchor_ref or {}),
            body.strip(),
            _serialise_mentions(mentioned_user_ids),
            author_id,
        )
    row_dict = _row_to_dict(row)

    # W18/D2: dispatch notifications for any @-mentions. Best-effort
    # — :func:`notify_comment_created` swallows + logs exceptions so
    # a flaky notification path never rolls back a committed comment.
    from core.notifications.wiring import notify_comment_created
    await notify_comment_created(
        session_id=session_id, firm_id=firm_id, author_id=author_id,
        comment_id=str(row["id"]),
        body=body,
        anchor_ref=anchor_ref or {},
        mentioned_user_ids=row_dict.get("mentioned_user_ids") or [],
    )

    return CommentResult(ok=True, comment_id=str(row["id"]), row=row_dict)


# ---------------------------------------------------------------------------
# Reply
# ---------------------------------------------------------------------------


async def reply_to_comment(
    parent_comment_id: UUID,
    author_id: UUID,
    body: str,
    mentioned_user_ids: list[str] | None = None,
) -> CommentResult:
    """Add a reply to an existing comment. Replies inherit the
    root's anchor (anchor_type + anchor_ref) at insert time — the
    schema requires both columns non-null on every row, so the
    service does the inheritance rather than the caller.

    If the target itself is a reply, we walk back to the root so the
    inheritance pulls from the canonical thread anchor.
    """
    if not body or not body.strip():
        return CommentResult(ok=False, status_code=400, reason="body cannot be empty")

    parent = await _load_comment(parent_comment_id)
    if parent is None or parent.get("deleted_at"):
        return CommentResult(ok=False, status_code=404, reason=_NOT_FOUND)

    # If parent is itself a reply, walk to the root.
    root = parent
    while root.get("parent_comment_id"):
        next_parent_id = root["parent_comment_id"]
        next_parent = await _load_comment(
            UUID(str(next_parent_id)) if not isinstance(next_parent_id, UUID) else next_parent_id,
        )
        if next_parent is None:
            break
        root = next_parent

    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO comments (
                session_id, firm_id, parent_comment_id,
                anchor_type, anchor_ref, body, mentioned_user_ids,
                author_id
            ) VALUES (
                $1::uuid, $2::uuid, $3::uuid,
                $4, $5::jsonb, $6, $7::jsonb,
                $8::uuid
            )
            RETURNING id, session_id, firm_id, parent_comment_id, anchor_type,
                      anchor_ref, body, mentioned_user_ids, author_id,
                      resolved, resolved_by, resolved_at,
                      created_at, updated_at, edited_at, deleted_at
            """,
            parent["session_id"], parent["firm_id"], root["id"],
            root["anchor_type"], json.dumps(root.get("anchor_ref") or {}),
            body.strip(),
            _serialise_mentions(mentioned_user_ids),
            author_id,
        )
    row_dict = _row_to_dict(row)

    # W18/D2: dispatch both COMMENT_REPLY (for thread participants)
    # AND MENTION (for any @-tagged users in the reply). dispatch_batch
    # collapses to one notification per recipient via dedup_key —
    # MENTION wins on priority when a participant is also mentioned.
    from core.notifications.wiring import notify_comment_replied
    await notify_comment_replied(
        session_id=parent["session_id"] if isinstance(parent["session_id"], UUID)
                    else UUID(str(parent["session_id"])),
        firm_id=parent["firm_id"] if isinstance(parent["firm_id"], UUID)
                 else UUID(str(parent["firm_id"])),
        author_id=author_id,
        comment_id=str(row["id"]),
        root_comment_id=str(root["id"]),
        body=body,
        anchor_ref=root.get("anchor_ref") or {},
        mentioned_user_ids=row_dict.get("mentioned_user_ids") or [],
    )

    return CommentResult(ok=True, comment_id=str(row["id"]), row=row_dict)


# ---------------------------------------------------------------------------
# Edit
# ---------------------------------------------------------------------------


async def edit_comment(
    comment_id: UUID,
    author_id: UUID,
    new_body: str,
) -> CommentResult:
    """Edit a comment's body. Author-only (per W16/D1 hard rule).
    Sets ``edited_at`` + ``updated_at`` to NOW(); body is trimmed."""
    if not new_body or not new_body.strip():
        return CommentResult(ok=False, status_code=400, reason="body cannot be empty")

    existing = await _load_comment(comment_id)
    if existing is None or existing.get("deleted_at"):
        return CommentResult(ok=False, status_code=404, reason=_NOT_FOUND)
    if str(existing["author_id"]) != str(author_id):
        return CommentResult(ok=False, status_code=403, reason=_AUTHOR_ONLY)

    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE comments
               SET body = $2,
                   edited_at = NOW(),
                   updated_at = NOW()
             WHERE id = $1::uuid
            RETURNING id, session_id, firm_id, parent_comment_id, anchor_type,
                      anchor_ref, body, mentioned_user_ids, author_id,
                      resolved, resolved_by, resolved_at,
                      created_at, updated_at, edited_at, deleted_at
            """,
            comment_id, new_body.strip(),
        )
    return CommentResult(ok=True, comment_id=str(row["id"]), row=_row_to_dict(row))


# ---------------------------------------------------------------------------
# Delete (soft)
# ---------------------------------------------------------------------------


async def delete_comment(
    comment_id: UUID,
    actor_id: UUID,
) -> CommentResult:
    """Soft delete — sets ``deleted_at = NOW()``; the row stays
    for audit. Author OR firm admin can delete (per W16/D1 spec:
    "author-only" is too strict for admin moderation needs)."""
    existing = await _load_comment(comment_id)
    if existing is None or existing.get("deleted_at"):
        return CommentResult(ok=False, status_code=404, reason=_NOT_FOUND)
    if str(existing["author_id"]) != str(actor_id):
        is_admin = await _actor_is_firm_admin(
            UUID(str(existing["firm_id"])) if not isinstance(existing["firm_id"], UUID) else existing["firm_id"],
            actor_id,
        )
        if not is_admin:
            return CommentResult(ok=False, status_code=403, reason=_DELETE_AUTHOR_OR_ADMIN)

    async with acquire() as conn:
        await conn.execute(
            "UPDATE comments SET deleted_at = NOW(), updated_at = NOW() WHERE id = $1::uuid",
            comment_id,
        )
    return CommentResult(ok=True, comment_id=str(comment_id))


# ---------------------------------------------------------------------------
# Thread resolve / unresolve
# ---------------------------------------------------------------------------


async def resolve_thread(
    root_comment_id: UUID,
    actor_id: UUID,
) -> CommentResult:
    """Mark a thread resolved. Operates on the root only — resolving
    a reply is rejected with 409 per W16/D1 hard rule. Any firm
    member who can read the engagement is allowed (auth happens at
    the W16/D2 API layer via can_read; this is the service-level
    structural check only)."""
    existing = await _load_comment(root_comment_id)
    if existing is None or existing.get("deleted_at"):
        return CommentResult(ok=False, status_code=404, reason=_NOT_FOUND)
    if existing.get("parent_comment_id"):
        return CommentResult(ok=False, status_code=409, reason=_REPLY_NOT_ROOT)

    async with acquire() as conn:
        await conn.execute(
            """
            UPDATE comments
               SET resolved = TRUE,
                   resolved_by = $2::uuid,
                   resolved_at = NOW(),
                   updated_at = NOW()
             WHERE id = $1::uuid
            """,
            root_comment_id, actor_id,
        )
    return CommentResult(ok=True, comment_id=str(root_comment_id))


async def unresolve_thread(
    root_comment_id: UUID,
    actor_id: UUID,
) -> CommentResult:
    """Reopen a resolved thread. Same rules as ``resolve_thread`` —
    root-only, any firm member with engagement read access (API
    layer enforces that)."""
    existing = await _load_comment(root_comment_id)
    if existing is None or existing.get("deleted_at"):
        return CommentResult(ok=False, status_code=404, reason=_NOT_FOUND)
    if existing.get("parent_comment_id"):
        return CommentResult(ok=False, status_code=409, reason=_REPLY_NOT_ROOT)

    async with acquire() as conn:
        await conn.execute(
            """
            UPDATE comments
               SET resolved = FALSE,
                   resolved_by = NULL,
                   resolved_at = NULL,
                   updated_at = NOW()
             WHERE id = $1::uuid
            """,
            root_comment_id,
        )
    return CommentResult(ok=True, comment_id=str(root_comment_id))


__all__ = [
    "CommentResult",
    "create_comment",
    "delete_comment",
    "edit_comment",
    "reply_to_comment",
    "resolve_thread",
    "unresolve_thread",
]
