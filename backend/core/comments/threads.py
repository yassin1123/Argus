"""Thread assembly — Phase 4 / Week 16 / Day 2.

The Day 1 service writes individual comment rows; this module pulls
them back as threads (root + ordered replies) for the workspace
read path. Orphan detection runs here too — we hydrate the live
session payload once per call and flag any text_range comment
whose quote has drifted (per W16/D1 :mod:`orphan`).

Thread ordering: root comments are returned in ascending
``created_at`` order (oldest first); replies within a thread the
same. That's the chronological-feed shape the workspace UI
expects, and it matches how Slack / Linear / Notion render
threaded comments.

Filtering: callers can scope by anchor (anchor_type or
anchor_type + anchor_ref), or by resolved status. Filters compose
— ``anchor_type=section, resolved=false`` returns only unresolved
section-anchored threads.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from db.connection import acquire

from .anchors import AnchorType
from .orphan import is_text_range_orphaned

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class CommentThread:
    """Workspace-facing thread shape.

    ``root`` is the root comment row (dict); ``replies`` are the
    chronological replies. ``resolved`` mirrors ``root['resolved']``
    so the UI doesn't have to peek into the root. ``orphaned`` is
    True when the root anchor is a text_range whose quote has
    drifted out of the live payload — only set for text_range
    anchors per W16/D1 hard rule.
    """

    root: dict[str, Any]
    replies: list[dict[str, Any]] = field(default_factory=list)
    resolved: bool = False
    orphaned: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "replies": self.replies,
            "resolved": self.resolved,
            "orphaned": self.orphaned,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _decode_row(row: Any) -> dict[str, Any]:
    """Coerce an asyncpg Record into a JSON-safe dict. JSONB columns
    arrive as strings under the default codec; we decode them here so
    the API layer can ship them straight through ``json.dumps`` and so
    the orphan detector reads structured anchor_ref data."""
    d = dict(row)
    for key in ("anchor_ref", "mentioned_user_ids"):
        v = d.get(key)
        if isinstance(v, str):
            try:
                d[key] = json.loads(v)
            except Exception:
                d[key] = None
    # Stringify UUIDs + timestamps for clean JSON.
    for key in (
        "id", "session_id", "firm_id", "parent_comment_id", "author_id",
        "resolved_by",
    ):
        v = d.get(key)
        if v is not None and not isinstance(v, str):
            d[key] = str(v)
    for key in ("created_at", "updated_at", "edited_at", "deleted_at",
                "resolved_at"):
        v = d.get(key)
        if v is not None and hasattr(v, "isoformat"):
            d[key] = v.isoformat()
    return d


async def _load_session_payload_for_orphan(session_id: UUID) -> dict[str, Any]:
    """Hydrate the merged reports + consulting_payload shape used by
    the orphan detector. Empty dict if no report — orphan returns False
    on missing anchor_ref / payload so a session with no report yet
    won't mass-flag every text_range comment."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT key_reasons, risks, counterarguments, next_steps, sources,
                   caveats, summary, consulting_payload
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_threads_for_session(
    session_id: UUID,
    *,
    anchor_type: str | AnchorType | None = None,
    resolved: bool | None = None,
    author_id: UUID | str | None = None,
    mentioning_user_id: UUID | str | None = None,
) -> list[CommentThread]:
    """Return every live comment thread for a session, optionally
    filtered. Soft-deleted rows are excluded.

    Filters: ``anchor_type`` matches the root comment's anchor_type;
    ``resolved`` matches the root comment's resolved flag (True for
    closed-only, False for open-only, None for all); ``author_id``
    matches root author; ``mentioning_user_id`` filters to threads
    whose root OR any reply mentions the user via @-slug
    (the JSONB containment query backed by the W16/D4 GIN index).
    """
    if isinstance(anchor_type, AnchorType):
        anchor_type_filter: str | None = anchor_type.value
    else:
        anchor_type_filter = anchor_type

    where = ["session_id = $1::uuid", "deleted_at IS NULL"]
    args: list[Any] = [session_id]
    if anchor_type_filter is not None:
        args.append(anchor_type_filter)
        where.append(f"anchor_type = ${len(args)}")
    if author_id is not None:
        args.append(str(author_id))
        where.append(f"author_id = ${len(args)}::uuid")

    sql = f"""
        SELECT id, session_id, firm_id, parent_comment_id, anchor_type,
               anchor_ref, body, mentioned_user_ids, author_id,
               resolved, resolved_by, resolved_at,
               created_at, updated_at, edited_at, deleted_at
          FROM comments
         WHERE {' AND '.join(where)}
         ORDER BY created_at ASC, id ASC
    """

    async with acquire() as conn:
        rows = await conn.fetch(sql, *args)

    roots: dict[str, dict[str, Any]] = {}
    replies_by_root: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        row = _decode_row(r)
        if row.get("parent_comment_id"):
            replies_by_root.setdefault(row["parent_comment_id"], []).append(row)
        else:
            roots[row["id"]] = row

    if resolved is not None:
        roots = {
            cid: r for cid, r in roots.items()
            if bool(r.get("resolved")) is bool(resolved)
        }

    if mentioning_user_id is not None:
        target = str(mentioning_user_id)

        def _mentions_target(row: dict[str, Any]) -> bool:
            ids = row.get("mentioned_user_ids") or []
            if not isinstance(ids, list):
                return False
            return target in (str(x) for x in ids)

        kept: dict[str, dict[str, Any]] = {}
        for rid, root in roots.items():
            if _mentions_target(root):
                kept[rid] = root
                continue
            # Reply-side match: keep the thread if any reply
            # mentions the user.
            replies = replies_by_root.get(rid, [])
            if any(_mentions_target(rp) for rp in replies):
                kept[rid] = root
        roots = kept

    if not roots:
        return []

    # Hydrate payload once per call for orphan detection — only
    # needed when at least one text_range root is present.
    needs_payload = any(
        r.get("anchor_type") == AnchorType.TEXT_RANGE.value for r in roots.values()
    )
    payload = await _load_session_payload_for_orphan(session_id) if needs_payload else {}

    threads: list[CommentThread] = []
    for root in roots.values():
        rid = root["id"]
        replies = replies_by_root.get(rid, [])
        orphaned = (
            is_text_range_orphaned(root, payload)
            if root.get("anchor_type") == AnchorType.TEXT_RANGE.value
            else False
        )
        threads.append(CommentThread(
            root=root,
            replies=replies,
            resolved=bool(root.get("resolved")),
            orphaned=orphaned,
        ))
    threads.sort(key=lambda t: t.root.get("created_at") or "")
    return threads


async def get_threads_for_anchor(
    session_id: UUID,
    anchor_type: str | AnchorType,
    anchor_ref: dict[str, Any] | None = None,
) -> list[CommentThread]:
    """Return threads whose root matches a specific anchor.

    For ``section`` / ``claim`` / ``artifact`` / ``text_range`` you
    typically pass a key (``section_path``, ``claim_id``,
    ``artifact_id``, ``section_path``) inside ``anchor_ref`` to
    narrow further. The match is done in Python over the JSONB so
    callers can pass partial refs (e.g. ``{"section_path":
    "synergy_estimate"}`` matches every text_range or section
    comment anchored to that path, regardless of other fields).

    ``engagement`` anchors ignore ``anchor_ref`` per the W16/D1
    schema convention.
    """
    type_value = (
        anchor_type.value if isinstance(anchor_type, AnchorType) else str(anchor_type)
    )
    all_threads = await get_threads_for_session(session_id, anchor_type=type_value)

    if not anchor_ref or type_value == AnchorType.ENGAGEMENT.value:
        return all_threads

    def _matches(root: dict[str, Any]) -> bool:
        ref = root.get("anchor_ref") or {}
        if not isinstance(ref, dict):
            return False
        for key, want in anchor_ref.items():
            if ref.get(key) != want:
                return False
        return True

    return [t for t in all_threads if _matches(t.root)]


# ---------------------------------------------------------------------------
# Count helpers (badge surfaces)
# ---------------------------------------------------------------------------


async def count_threads_by_anchor(
    session_id: UUID,
) -> dict[str, dict[str, int]]:
    """Counts of root threads grouped by anchor_type + a per-section
    breakdown. Powers the workspace section badges ("3 comments on
    synergy_estimate, 1 unresolved").

    Returns::

        {
          "by_anchor_type": {"section": 4, "claim": 2, ...},
          "by_section_path": {"synergy_estimate": 3, "risks[0]": 1},
          "unresolved_total": 5,
          "total": 8,
        }
    """
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT anchor_type, anchor_ref, resolved
              FROM comments
             WHERE session_id = $1::uuid
               AND parent_comment_id IS NULL
               AND deleted_at IS NULL
            """,
            session_id,
        )

    by_anchor: dict[str, int] = {}
    by_section: dict[str, int] = {}
    unresolved = 0
    total = 0
    for r in rows:
        total += 1
        at = str(r["anchor_type"])
        by_anchor[at] = by_anchor.get(at, 0) + 1
        if not r["resolved"]:
            unresolved += 1
        ref = r["anchor_ref"]
        if isinstance(ref, str):
            try:
                ref = json.loads(ref)
            except Exception:
                ref = None
        if isinstance(ref, dict):
            sp = ref.get("section_path")
            if isinstance(sp, str) and sp:
                by_section[sp] = by_section.get(sp, 0) + 1

    return {
        "by_anchor_type": by_anchor,
        "by_section_path": by_section,
        "unresolved_total": unresolved,
        "total": total,
    }


# ---------------------------------------------------------------------------
# W16/D4 — grouped overview, bulk resolve, cross-engagement mentions
# ---------------------------------------------------------------------------


_OVERVIEW_GROUP_ORDER = ["section", "claim", "artifact", "text_range", "engagement"]


def _anchor_group_key(root: dict[str, Any]) -> tuple[str, str]:
    """Build a stable (group_key, group_label) for the overview
    grouping. Threads anchored to the same section_path / claim_id /
    artifact_id collapse into one group; engagement-anchored threads
    share the "engagement" bucket."""
    at = str(root.get("anchor_type") or "")
    ref = root.get("anchor_ref") if isinstance(root.get("anchor_ref"), dict) else {}
    ref = ref or {}
    if at == "section":
        sp = str(ref.get("section_path") or "")
        return (f"section:{sp}", f"Section: {sp}" if sp else "Section: ?")
    if at == "claim":
        cid = str(ref.get("claim_id") or "")
        return (f"claim:{cid}", f"Claim: {cid}" if cid else "Claim: ?")
    if at == "artifact":
        aid = str(ref.get("artifact_id") or "")
        short = aid[:8] if aid else "?"
        return (f"artifact:{aid}", f"Artifact: {short}")
    if at == "text_range":
        sp = str(ref.get("section_path") or "")
        return (f"text_range:{sp}", f"Text range — {sp}" if sp else "Text range")
    return ("engagement", "General")


async def get_threads_grouped_for_overview(
    session_id: UUID,
    *,
    resolved: bool | None = None,
    author_id: UUID | str | None = None,
    mentioning_user_id: UUID | str | None = None,
) -> dict[str, Any]:
    """W16/D4 engagement-level overview shape: threads grouped by
    anchor with metadata for the workspace "Discussion" tab.

    Returns::

        {
          "groups": [
            {"key": "section:synergy_estimate",
             "label": "Section: synergy_estimate",
             "anchor_type": "section",
             "anchor_ref": {"section_path": "synergy_estimate"},
             "threads": [<CommentThread>, …],
             "unresolved": 2, "total": 3},
            …
          ],
          "unresolved_total": 5,
          "total": 8,
        }

    Group order: section → claim → artifact → text_range → engagement.
    Within a group, threads are in chronological-asc order (same as
    :func:`get_threads_for_session`).
    """
    threads = await get_threads_for_session(
        session_id,
        resolved=resolved,
        author_id=author_id,
        mentioning_user_id=mentioning_user_id,
    )

    grouped: dict[str, dict[str, Any]] = {}
    for t in threads:
        key, label = _anchor_group_key(t.root)
        bucket = grouped.setdefault(key, {
            "key": key,
            "label": label,
            "anchor_type": t.root.get("anchor_type"),
            "anchor_ref": t.root.get("anchor_ref"),
            "threads": [],
            "unresolved": 0,
            "total": 0,
        })
        bucket["threads"].append(t.to_dict())
        bucket["total"] += 1
        if not t.resolved:
            bucket["unresolved"] += 1

    def _sort_key(g: dict[str, Any]) -> tuple[int, str]:
        at = str(g.get("anchor_type") or "engagement")
        rank = _OVERVIEW_GROUP_ORDER.index(at) if at in _OVERVIEW_GROUP_ORDER else 99
        return (rank, str(g.get("label") or ""))

    ordered = sorted(grouped.values(), key=_sort_key)
    return {
        "groups": ordered,
        "unresolved_total": sum(g["unresolved"] for g in ordered),
        "total": sum(g["total"] for g in ordered),
    }


async def bulk_resolve_section(
    session_id: UUID,
    section_path: str,
    actor_id: UUID,
) -> dict[str, Any]:
    """Mark every unresolved root comment anchored to ``section_path``
    resolved in one DB round-trip. Returns the list of root comment
    IDs that flipped so the API layer can emit a per-thread audit
    event (per W16/D4 hard rule: bulk resolve does NOT skip audit).
    Already-resolved or soft-deleted threads are left untouched.
    """
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            UPDATE comments
               SET resolved = TRUE,
                   resolved_by = $2::uuid,
                   resolved_at = NOW(),
                   updated_at = NOW()
             WHERE session_id = $1::uuid
               AND parent_comment_id IS NULL
               AND deleted_at IS NULL
               AND resolved = FALSE
               AND anchor_type = 'section'
               AND anchor_ref ->> 'section_path' = $3
            RETURNING id
            """,
            session_id, actor_id, section_path,
        )
    resolved_ids = [str(r["id"]) for r in rows]
    return {
        "section_path": section_path,
        "resolved_count": len(resolved_ids),
        "resolved_comment_ids": resolved_ids,
    }


async def list_mentions_for_user(
    user_id: UUID,
    *,
    firm_id: UUID | None = None,
    unresolved_only: bool = False,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Cross-engagement "my mentions" — every live thread root OR
    reply that @-mentions the given user, optionally constrained to
    a single firm (the API layer always passes the requester's
    firm_id so cross-firm leakage is impossible per W16/D4 hard rule).
    """
    where = [
        "deleted_at IS NULL",
        "mentioned_user_ids @> $1::jsonb",
    ]
    args: list[Any] = [json.dumps([str(user_id)])]
    if firm_id is not None:
        args.append(str(firm_id))
        where.append(f"firm_id = ${len(args)}::uuid")
    if unresolved_only:
        # Apply on the ROOT only; replies inherit resolution state
        # from their root in the API layer.
        where.append(
            "(parent_comment_id IS NOT NULL OR resolved = FALSE)"
        )
    args.append(int(limit))
    limit_token = f"${len(args)}"

    sql = f"""
        SELECT id, session_id, firm_id, parent_comment_id, anchor_type,
               anchor_ref, body, mentioned_user_ids, author_id,
               resolved, resolved_by, resolved_at,
               created_at, updated_at, edited_at, deleted_at
          FROM comments
         WHERE {' AND '.join(where)}
         ORDER BY created_at DESC, id DESC
         LIMIT {limit_token}
    """
    async with acquire() as conn:
        rows = await conn.fetch(sql, *args)
    return [_decode_row(r) for r in rows]


async def count_unresolved_for_session(session_id: UUID) -> dict[str, int]:
    """Two-number summary used by the review endpoint's
    ``comments`` block — ``{unresolved, total}``. Cheap (single
    aggregate query, no JOIN, no JSONB unpack)."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
              COUNT(*) FILTER (WHERE resolved = FALSE) AS unresolved,
              COUNT(*) AS total
              FROM comments
             WHERE session_id = $1::uuid
               AND parent_comment_id IS NULL
               AND deleted_at IS NULL
            """,
            session_id,
        )
    return {
        "unresolved": int(row["unresolved"] or 0),
        "total": int(row["total"] or 0),
    }


__all__ = [
    "CommentThread",
    "bulk_resolve_section",
    "count_threads_by_anchor",
    "get_threads_grouped_for_overview",
    "list_mentions_for_user",
    "count_unresolved_for_session",
    "get_threads_for_anchor",
    "get_threads_for_session",
]
