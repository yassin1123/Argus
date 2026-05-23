"""Comment API — Phase 4 / Week 16 / Day 2.

Eight endpoints exposing the W16/D1 service + the W16/D2 thread
assembly + mention parsing:

  POST   /api/sessions/{id}/comments               create root
  POST   /api/comments/{id}/replies                reply
  PATCH  /api/comments/{id}                        edit (author-only)
  DELETE /api/comments/{id}                        soft delete
  POST   /api/comments/{id}/resolve                resolve thread
  POST   /api/comments/{id}/unresolve              reopen
  GET    /api/sessions/{id}/comments               list threads
  GET    /api/sessions/{id}/comments/count         counts by anchor

Authorization: every endpoint requires firm-member access on the
session's firm. Cross-firm callers see a 404 (anti-enumeration —
the W5 pattern). Per W16/D1, edits are author-only and deletes
are author-or-admin; both rules live in
:mod:`core.comments.service` so we don't duplicate the check here
beyond mapping the service result to an HTTP code.

Mounted in :mod:`main` under two prefixes:

  - ``/api/sessions`` (the create + list + count routes)
  - ``/api/comments`` (the per-comment routes)

so a single router holds both prefixes via path-explicit
declarations. Audit logging hooks into every action — see
``_audit`` at the bottom.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from audit.queries import append_event
from auth.dependencies import get_current_user
from auth.permissions import can_read
from core.comments.anchors import AnchorType
from core.comments.mentions import emit_mention_events, parse_mentions
from core.comments.service import (
    create_comment,
    delete_comment,
    edit_comment,
    reply_to_comment,
    resolve_thread,
    unresolve_thread,
)
from core.comments.threads import (
    bulk_resolve_section,
    count_threads_by_anchor,
    get_threads_for_session,
    get_threads_grouped_for_overview,
)
from db.connection import acquire

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class CreateCommentBody(BaseModel):
    """Root-comment create body. ``anchor_ref`` is required by every
    anchor type except ``engagement`` (validated by the W16/D1
    service); the API just forwards it."""

    anchor_type: str = Field(..., min_length=1, max_length=32)
    anchor_ref: dict[str, Any] | None = Field(default=None)
    body: str = Field(..., min_length=1, max_length=8000)

    model_config = {"extra": "ignore"}


class ReplyBody(BaseModel):
    body: str = Field(..., min_length=1, max_length=8000)

    model_config = {"extra": "ignore"}


class EditBody(BaseModel):
    body: str = Field(..., min_length=1, max_length=8000)

    model_config = {"extra": "ignore"}


# ---------------------------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------------------------


async def _require_read_session(session_id: str, user: dict) -> None:
    """The comment endpoints all require at least engagement-read
    access. Cross-firm callers see 404, matching the W5/W15
    anti-enumeration pattern."""
    if not await can_read(session_id, user):
        raise HTTPException(status_code=404, detail="Session not found")


async def _load_comment_session(comment_id: str) -> tuple[str, str, str] | None:
    """Look up (session_id, firm_id, author_id) for a comment so the
    per-comment endpoints can run the engagement-read gate. None when
    the comment doesn't exist."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT session_id, firm_id, author_id
              FROM comments WHERE id = $1::uuid
            """,
            comment_id,
        )
    if not row:
        return None
    return str(row["session_id"]), str(row["firm_id"]), str(row["author_id"])


async def _list_firm_members(firm_id: str) -> list[dict[str, Any]]:
    """Return every member of a firm with the fields the mention
    parser needs: ``user_id``, ``email``, ``full_name``,
    ``created_at`` (for deterministic slug-collision ordering)."""
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT u.id AS user_id, u.email, u.full_name, fm.created_at
              FROM firm_memberships fm
              JOIN users u ON u.id = fm.user_id
             WHERE fm.firm_id = $1::uuid
             ORDER BY fm.created_at ASC, u.id ASC
            """,
            firm_id,
        )
    return [
        {
            "user_id": str(r["user_id"]),
            "email": r["email"],
            "full_name": r["full_name"] or "",
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Audit helper
# ---------------------------------------------------------------------------


async def _audit(
    *,
    action: str,
    user: dict,
    comment_id: str | None,
    session_id: str | None,
    anchor_type: str | None = None,
    anchor_ref: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Single audit-event shape for every comment action. Best-effort
    — :func:`append_event` swallows DB failures so the request still
    succeeds (auditing must not break the user)."""
    payload: dict[str, Any] = {}
    if session_id:
        payload["session_id"] = session_id
    if anchor_type:
        payload["anchor_type"] = anchor_type
    if anchor_ref is not None:
        payload["anchor_ref"] = anchor_ref
    if extra:
        payload.update(extra)
    await append_event(
        action=action,
        actor_user_id=user.get("user_id"),
        actor_email=user.get("email"),
        resource_type="comment",
        resource_id=comment_id,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Mention parsing (shared)
# ---------------------------------------------------------------------------


async def _resolve_mentions(firm_id: str, body: str) -> list[str]:
    """Run the body through the slug-based mention parser against
    firm members. Returns string UUIDs (the service stores them as a
    JSONB array of strings)."""
    if not body:
        return []
    members = await _list_firm_members(firm_id)
    return [str(uid) for uid in parse_mentions(body, members)]


# ---------------------------------------------------------------------------
# Create / Reply
# ---------------------------------------------------------------------------


@router.post("/sessions/{session_id}/comments")
async def create_root_comment_endpoint(
    session_id: str,
    body: CreateCommentBody,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Create a root comment anchored to a session target. Mentions
    are parsed from the body against the session-firm's members."""
    await _require_read_session(session_id, user)

    try:
        sid = UUID(session_id)
        aid = UUID(user["user_id"])
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid id: {e}") from e

    # Resolve mentions BEFORE the service call so the persisted row
    # already carries the resolved IDs.
    firm_row: dict[str, Any] | None
    async with acquire() as conn:
        firm_row = await conn.fetchrow(
            "SELECT firm_id FROM sessions WHERE id = $1::uuid", sid,
        )
    if not firm_row:
        raise HTTPException(status_code=404, detail="Session not found")
    mention_ids = await _resolve_mentions(str(firm_row["firm_id"]), body.body)

    result = await create_comment(
        sid, aid,
        body.anchor_type,
        body.anchor_ref or {},
        body.body,
        mentioned_user_ids=mention_ids or None,
    )
    if not result.ok:
        raise HTTPException(status_code=result.status_code, detail=result.reason)

    await _audit(
        action="comment.created",
        user=user,
        comment_id=result.comment_id,
        session_id=session_id,
        anchor_type=body.anchor_type,
        anchor_ref=body.anchor_ref,
        extra={"mention_count": len(mention_ids)} if mention_ids else None,
    )
    await emit_mention_events(
        comment_id=result.comment_id or "",
        session_id=session_id,
        author_id=str(aid),
        mentioned_user_ids=mention_ids,
    )
    return _comment_to_api(result.row)


@router.post("/comments/{comment_id}/replies")
async def reply_endpoint(
    comment_id: str,
    body: ReplyBody,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Reply to an existing comment. The service walks to the thread
    root + copies the anchor; the API gates engagement read first so
    cross-firm callers get a 404."""
    info = await _load_comment_session(comment_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    session_id, firm_id, _author = info
    await _require_read_session(session_id, user)

    try:
        cid = UUID(comment_id)
        aid = UUID(user["user_id"])
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid id: {e}") from e

    mention_ids = await _resolve_mentions(firm_id, body.body)

    result = await reply_to_comment(
        cid, aid, body.body, mentioned_user_ids=mention_ids or None,
    )
    if not result.ok:
        raise HTTPException(status_code=result.status_code, detail=result.reason)

    await _audit(
        action="comment.replied",
        user=user,
        comment_id=result.comment_id,
        session_id=session_id,
        extra={
            "parent_comment_id": comment_id,
            "mention_count": len(mention_ids),
        } if mention_ids else {"parent_comment_id": comment_id},
    )
    await emit_mention_events(
        comment_id=result.comment_id or "",
        session_id=session_id,
        author_id=str(aid),
        mentioned_user_ids=mention_ids,
    )
    return _comment_to_api(result.row)


# ---------------------------------------------------------------------------
# Edit / Delete
# ---------------------------------------------------------------------------


@router.patch("/comments/{comment_id}")
async def edit_comment_endpoint(
    comment_id: str,
    body: EditBody,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Edit a comment's body. Author-only — the service returns 403
    for any other actor."""
    info = await _load_comment_session(comment_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    session_id, _firm_id, _author = info
    await _require_read_session(session_id, user)

    try:
        cid = UUID(comment_id)
        aid = UUID(user["user_id"])
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid id: {e}") from e

    result = await edit_comment(cid, aid, body.body)
    if not result.ok:
        raise HTTPException(status_code=result.status_code, detail=result.reason)

    await _audit(
        action="comment.edited",
        user=user,
        comment_id=result.comment_id,
        session_id=session_id,
    )
    return _comment_to_api(result.row)


@router.delete("/comments/{comment_id}")
async def delete_comment_endpoint(
    comment_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Soft delete. Author OR firm admin. The row stays in the
    table for audit-trail integrity."""
    info = await _load_comment_session(comment_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    session_id, _firm_id, _author = info
    await _require_read_session(session_id, user)

    try:
        cid = UUID(comment_id)
        aid = UUID(user["user_id"])
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid id: {e}") from e

    result = await delete_comment(cid, aid)
    if not result.ok:
        raise HTTPException(status_code=result.status_code, detail=result.reason)

    await _audit(
        action="comment.deleted",
        user=user,
        comment_id=result.comment_id,
        session_id=session_id,
    )
    return {"ok": True, "comment_id": result.comment_id}


# ---------------------------------------------------------------------------
# Resolve / unresolve
# ---------------------------------------------------------------------------


@router.post("/comments/{comment_id}/resolve")
async def resolve_thread_endpoint(
    comment_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Mark a thread resolved. Root-only — the service returns 409
    when called on a reply."""
    info = await _load_comment_session(comment_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    session_id, _firm_id, _author = info
    await _require_read_session(session_id, user)

    try:
        cid = UUID(comment_id)
        aid = UUID(user["user_id"])
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid id: {e}") from e

    result = await resolve_thread(cid, aid)
    if not result.ok:
        raise HTTPException(status_code=result.status_code, detail=result.reason)

    await _audit(
        action="comment.resolved",
        user=user,
        comment_id=result.comment_id,
        session_id=session_id,
    )
    return {"ok": True, "comment_id": result.comment_id, "resolved": True}


@router.post("/comments/{comment_id}/unresolve")
async def unresolve_thread_endpoint(
    comment_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Reopen a resolved thread. Same root-only contract as resolve."""
    info = await _load_comment_session(comment_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    session_id, _firm_id, _author = info
    await _require_read_session(session_id, user)

    try:
        cid = UUID(comment_id)
        aid = UUID(user["user_id"])
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid id: {e}") from e

    result = await unresolve_thread(cid, aid)
    if not result.ok:
        raise HTTPException(status_code=result.status_code, detail=result.reason)

    await _audit(
        action="comment.unresolved",
        user=user,
        comment_id=result.comment_id,
        session_id=session_id,
    )
    return {"ok": True, "comment_id": result.comment_id, "resolved": False}


# ---------------------------------------------------------------------------
# List / count (workspace read path)
# ---------------------------------------------------------------------------


@router.get("/sessions/{session_id}/comments")
async def list_threads_endpoint(
    session_id: str,
    anchor_type: str | None = Query(default=None, max_length=32),
    resolved: bool | None = Query(default=None),
    author_id: str | None = Query(default=None, max_length=36),
    mentioning: str | None = Query(
        default=None, max_length=36,
        description="Filter to threads mentioning this user_id "
                    "(in the root or any reply).",
    ),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Every live thread on a session, optionally filtered by
    ``anchor_type``, ``resolved`` status, ``author_id``, or
    ``mentioning`` (the W16/D4 filter for the overview / mentions UI).
    """
    await _require_read_session(session_id, user)
    try:
        sid = UUID(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid session id: {e}") from e

    if anchor_type is not None:
        try:
            AnchorType(anchor_type)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"invalid anchor_type: {e}") from e

    threads = await get_threads_for_session(
        sid,
        anchor_type=anchor_type,
        resolved=resolved,
        author_id=author_id,
        mentioning_user_id=mentioning,
    )
    return {
        "session_id": session_id,
        "threads": [t.to_dict() for t in threads],
        "total": len(threads),
    }


@router.get("/sessions/{session_id}/comments/overview")
async def comments_overview_endpoint(
    session_id: str,
    resolved: bool | None = Query(default=None),
    author_id: str | None = Query(default=None, max_length=36),
    mentioning: str | None = Query(default=None, max_length=36),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """W16/D4 engagement-level overview — threads grouped by anchor
    (section → claim → artifact → text_range → engagement) with
    per-group resolved/unresolved counts. Powers the workspace
    "Discussion" tab."""
    await _require_read_session(session_id, user)
    try:
        sid = UUID(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid session id: {e}") from e
    return await get_threads_grouped_for_overview(
        sid,
        resolved=resolved,
        author_id=author_id,
        mentioning_user_id=mentioning,
    )


class ResolveSectionBody(BaseModel):
    section_path: str = Field(..., min_length=1, max_length=200)

    model_config = {"extra": "ignore"}


@router.post("/sessions/{session_id}/comments/resolve-section")
async def resolve_section_endpoint(
    session_id: str,
    body: ResolveSectionBody,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Mark every unresolved root thread anchored to
    ``section_path`` resolved. One DB round-trip flips the rows;
    a per-thread ``comment.resolved`` audit event is emitted for
    each so the bulk action is fully traceable
    (W16/D4 hard rule)."""
    await _require_read_session(session_id, user)
    try:
        sid = UUID(session_id)
        aid = UUID(user["user_id"])
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid id: {e}") from e

    result = await bulk_resolve_section(sid, body.section_path, aid)

    for cid in result["resolved_comment_ids"]:
        await _audit(
            action="comment.resolved",
            user=user,
            comment_id=cid,
            session_id=session_id,
            extra={"bulk": True, "section_path": body.section_path},
        )
    return result


@router.get("/sessions/{session_id}/comments/count")
async def comments_count_endpoint(
    session_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Counts grouped by anchor_type + per-section breakdown — used
    by the workspace section badges. Cheap (one aggregate query)."""
    await _require_read_session(session_id, user)
    try:
        sid = UUID(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid session id: {e}") from e
    return await count_threads_by_anchor(sid)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _comment_to_api(row: dict[str, Any] | None) -> dict[str, Any]:
    """Coerce the service's row dict into the API response shape.
    The service already JSON-decodes anchor_ref + mentioned_user_ids
    via :func:`core.comments.service._row_to_dict`; we just stringify
    UUIDs + timestamps so the response is JSON-clean."""
    if not row:
        return {}
    out = dict(row)
    for k in (
        "id", "session_id", "firm_id", "parent_comment_id",
        "author_id", "resolved_by",
    ):
        v = out.get(k)
        if v is not None and not isinstance(v, str):
            out[k] = str(v)
    for k in (
        "created_at", "updated_at", "edited_at", "deleted_at", "resolved_at",
    ):
        v = out.get(k)
        if v is not None and hasattr(v, "isoformat"):
            out[k] = v.isoformat()
    return out


__all__ = ["router"]
