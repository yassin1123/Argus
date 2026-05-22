"""Phase 4 / Week 16 / Day 1 — comment schema + anchoring + CRUD service tests.

Ten tests per spec. Two layers:

  - **Anchor + orphan logic tests** — pure functions, no DB needed.
  - **Service CRUD tests** — use an in-process fake of asyncpg's
    ``acquire()`` connection so the SQL paths exercise without a
    live Postgres. The shape mirrors what the W15/D2 service tests
    use (``test_review_api.py`` test 7 + 10 followed the same
    pattern).

The fake DB is a dict-shaped store (``comments`` table only, plus a
session→firm lookup, a session_id→payload lookup, and a session→artifacts
lookup). Every SQL string the service emits is matched on keywords
so each handler routes to the right in-memory operation.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest import mock

import pytest

from core.comments import service as cmt_service
from core.comments.anchors import (
    AnchorType,
    AnchorValidationResult,
    validate_anchor,
)
from core.comments.orphan import is_text_range_orphaned


# ---------------------------------------------------------------------------
# In-memory DB fake
# ---------------------------------------------------------------------------


def _patch_db(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace acquire() with a context manager that hands back a
    fake connection. The fake routes every SQL string the service
    issues by keyword-match into the in-memory store, which is the
    cleanest pattern that doesn't require a live Postgres."""

    store: dict[str, Any] = {
        "comments": {},        # id -> row dict
        "sessions": {},        # session_id -> {firm_id, payload, artifacts}
        "memberships": {},     # (firm_id, user_id) -> role
    }

    async def fetchrow(sql: str, *args: Any) -> dict[str, Any] | None:
        s = " ".join(sql.split())
        if "FROM sessions WHERE id" in s:
            sid = str(args[0])
            sess = store["sessions"].get(sid)
            if sess is None:
                return None
            return {"firm_id": sess["firm_id"]}
        if "FROM reports WHERE session_id" in s:
            sid = str(args[0])
            sess = store["sessions"].get(sid)
            if sess is None:
                return None
            payload = sess.get("payload") or {}
            row = {k: payload.get(k) for k in (
                "recommendation", "confidence_level", "summary",
                "key_reasons", "risks", "counterarguments", "next_steps",
                "sources", "caveats",
            )}
            row["consulting_payload"] = payload.get("consulting_payload", {})
            return row
        if "FROM comments WHERE id" in s:
            cid = str(args[0])
            return store["comments"].get(cid)
        if "FROM firm_memberships" in s:
            firm_id, user_id = str(args[0]), str(args[1])
            role = store["memberships"].get((firm_id, user_id))
            return {"role": role} if role else None
        if "INSERT INTO comments" in s and "RETURNING" in s:
            # CREATE binds 7 args (parent_comment_id is hardcoded NULL
            # in the SQL); REPLY binds 8 args with parent_id at arg[2].
            new_id = str(uuid.uuid4())
            now = datetime.now(tz=timezone.utc)
            session_id = str(args[0])
            firm_id = str(args[1])
            if len(args) == 8:
                parent_id = args[2]
                anchor_type = args[3]
                anchor_ref_json = args[4]
                body = args[5]
                mentions_json = args[6]
                author_id = str(args[7])
            else:
                parent_id = None
                anchor_type = args[2]
                anchor_ref_json = args[3]
                body = args[4]
                mentions_json = args[5]
                author_id = str(args[6])
            row = {
                "id": new_id,
                "session_id": session_id,
                "firm_id": firm_id,
                "parent_comment_id": str(parent_id) if parent_id else None,
                "anchor_type": anchor_type,
                "anchor_ref": json.loads(anchor_ref_json or "{}"),
                "body": body,
                "mentioned_user_ids": json.loads(mentions_json or "[]"),
                "author_id": author_id,
                "resolved": False,
                "resolved_by": None,
                "resolved_at": None,
                "created_at": now,
                "updated_at": now,
                "edited_at": None,
                "deleted_at": None,
            }
            store["comments"][new_id] = row
            return row
        if "UPDATE comments" in s and "RETURNING" in s:
            cid = str(args[0])
            existing = store["comments"].get(cid)
            if not existing:
                return None
            existing["body"] = args[1]
            existing["edited_at"] = datetime.now(tz=timezone.utc)
            existing["updated_at"] = datetime.now(tz=timezone.utc)
            return existing
        return None

    async def fetch(sql: str, *args: Any) -> list[dict[str, Any]]:
        s = " ".join(sql.split())
        if "FROM export_artifacts" in s:
            sid = str(args[0])
            sess = store["sessions"].get(sid)
            if sess is None:
                return []
            return sess.get("artifacts", [])
        return []

    async def fetchval(sql: str, *args: Any) -> Any:
        return None

    async def execute(sql: str, *args: Any) -> None:
        s = " ".join(sql.split())
        if "UPDATE comments" in s and "deleted_at = NOW()" in s:
            cid = str(args[0])
            row = store["comments"].get(cid)
            if row:
                row["deleted_at"] = datetime.now(tz=timezone.utc)
                row["updated_at"] = datetime.now(tz=timezone.utc)
            return
        if "UPDATE comments" in s and "resolved = TRUE" in s:
            cid = str(args[0])
            actor = str(args[1])
            row = store["comments"].get(cid)
            if row:
                row["resolved"] = True
                row["resolved_by"] = actor
                row["resolved_at"] = datetime.now(tz=timezone.utc)
                row["updated_at"] = datetime.now(tz=timezone.utc)
            return
        if "UPDATE comments" in s and "resolved = FALSE" in s:
            cid = str(args[0])
            row = store["comments"].get(cid)
            if row:
                row["resolved"] = False
                row["resolved_by"] = None
                row["resolved_at"] = None
                row["updated_at"] = datetime.now(tz=timezone.utc)

    fake_conn = mock.MagicMock()
    fake_conn.fetchrow = fetchrow
    fake_conn.fetch = fetch
    fake_conn.fetchval = fetchval
    fake_conn.execute = execute

    class _AcquireCM:
        async def __aenter__(self):
            return fake_conn
        async def __aexit__(self, *a):
            return None

    monkeypatch.setattr(cmt_service, "acquire", lambda: _AcquireCM())
    return store


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_SESSION_ID = str(uuid.uuid4())
_FIRM_ID = str(uuid.uuid4())
_AUTHOR_ID = str(uuid.uuid4())
_OTHER_USER_ID = str(uuid.uuid4())
_ADMIN_USER_ID = str(uuid.uuid4())


def _seed_session(store: dict[str, Any]) -> None:
    """Plant a session with a representative payload + an artifact +
    admin / member memberships.

    The real ``reports`` schema has a ``consulting_payload`` JSONB
    column that holds every M&A / growth-mode-specific field
    (synergy_estimate, frameworks, valuation_range, …). The service's
    ``_load_session_payload`` flattens those onto the top-level dict
    via ``out.update(consulting_payload)`` — so when the W9 section
    addressing walks ``synergy_estimate``, the key lands at the top
    level. The fake DB mimics that shape: writer-row fields at the
    top, mode-specific fields inside ``consulting_payload``.
    """
    store["sessions"][_SESSION_ID] = {
        "firm_id": _FIRM_ID,
        "payload": {
            "recommendation": "PROCEED",
            "summary": "Synergy basis is the load-bearing assumption.",
            "key_reasons": [
                {"text": "Resilient gross margin", "claim_id": "claim_kgr_1"},
            ],
            "risks": [],
            "counterarguments": [],
            "next_steps": [],
            "sources": [],
            "caveats": "",
            "confidence_level": "Medium",
            "consulting_payload": {
                "synergy_estimate": {
                    "revenue_synergies": [
                        {"type": "Cross-sell", "magnitude_gbp_m": 5.0, "basis_citations": ["claim_kgr_2"]},
                    ],
                    "cost_synergies": [],
                },
                "frameworks": {
                    "porters_five_forces": {"market_definition": "x"},
                },
                "recommendation_claim_ids": ["claim_kgr_1", "claim_kgr_2"],
            },
        },
        "artifacts": [
            {"id": "11111111-1111-1111-1111-111111111111",
             "artifact_type": "deck", "format": "pptx", "status": "ready"},
        ],
    }
    store["memberships"][(_FIRM_ID, _ADMIN_USER_ID)] = "admin"
    store["memberships"][(_FIRM_ID, _AUTHOR_ID)] = "member"
    store["memberships"][(_FIRM_ID, _OTHER_USER_ID)] = "member"


# ---------------------------------------------------------------------------
# Test 1 — section anchor validates against the live payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_section_comment_validates_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _patch_db(monkeypatch)
    _seed_session(store)

    res = await cmt_service.create_comment(
        session_id=uuid.UUID(_SESSION_ID),
        author_id=uuid.UUID(_AUTHOR_ID),
        anchor_type=AnchorType.SECTION,
        anchor_ref={"section_path": "synergy_estimate"},
        body="Tighten the synergy basis.",
    )
    assert res.ok, res.reason
    assert res.row["anchor_type"] == "section"
    assert res.row["anchor_ref"]["section_path"] == "synergy_estimate"


# ---------------------------------------------------------------------------
# Test 2 — claim anchor validates against the claim registry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_claim_comment_validates_claim_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _patch_db(monkeypatch)
    _seed_session(store)

    res = await cmt_service.create_comment(
        session_id=uuid.UUID(_SESSION_ID),
        author_id=uuid.UUID(_AUTHOR_ID),
        anchor_type=AnchorType.CLAIM,
        anchor_ref={"claim_id": "claim_kgr_1"},
        body="What's the source on this revenue claim?",
    )
    assert res.ok, res.reason
    assert res.row["anchor_ref"]["claim_id"] == "claim_kgr_1"

    # An anchor pointing at a claim_id that's not in the registry is
    # rejected with a 400 + clear reason.
    bad = await cmt_service.create_comment(
        session_id=uuid.UUID(_SESSION_ID),
        author_id=uuid.UUID(_AUTHOR_ID),
        anchor_type=AnchorType.CLAIM,
        anchor_ref={"claim_id": "claim_does_not_exist"},
        body="Bogus claim.",
    )
    assert not bad.ok
    assert bad.status_code == 400
    assert "claim_does_not_exist" in bad.reason


# ---------------------------------------------------------------------------
# Test 3 — invalid section path is rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_comment_invalid_section_path_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _patch_db(monkeypatch)
    _seed_session(store)

    res = await cmt_service.create_comment(
        session_id=uuid.UUID(_SESSION_ID),
        author_id=uuid.UUID(_AUTHOR_ID),
        anchor_type=AnchorType.SECTION,
        anchor_ref={"section_path": "this_section_doesnt_exist"},
        body="Bogus section.",
    )
    assert not res.ok
    assert res.status_code == 400
    assert "this_section_doesnt_exist" in res.reason


# ---------------------------------------------------------------------------
# Test 4 — reply inherits root's anchor (anchor_type + anchor_ref)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reply_inherits_root_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _patch_db(monkeypatch)
    _seed_session(store)

    root = await cmt_service.create_comment(
        session_id=uuid.UUID(_SESSION_ID),
        author_id=uuid.UUID(_AUTHOR_ID),
        anchor_type=AnchorType.SECTION,
        anchor_ref={"section_path": "synergy_estimate"},
        body="Tighten the synergy basis.",
    )
    assert root.ok

    reply = await cmt_service.reply_to_comment(
        parent_comment_id=uuid.UUID(root.comment_id),
        author_id=uuid.UUID(_OTHER_USER_ID),
        body="Agreed — I'll source it from the carve-out playbook.",
    )
    assert reply.ok, reply.reason
    # Reply row carries the SAME anchor as the root.
    assert reply.row["anchor_type"] == "section"
    assert reply.row["anchor_ref"]["section_path"] == "synergy_estimate"
    assert reply.row["parent_comment_id"] == root.comment_id

    # And a reply-to-a-reply walks up to the root for inheritance.
    reply2 = await cmt_service.reply_to_comment(
        parent_comment_id=uuid.UUID(reply.comment_id),
        author_id=uuid.UUID(_AUTHOR_ID),
        body="Thanks.",
    )
    assert reply2.ok
    assert reply2.row["parent_comment_id"] == root.comment_id
    assert reply2.row["anchor_ref"]["section_path"] == "synergy_estimate"


# ---------------------------------------------------------------------------
# Test 5 — resolve sets ``resolved=true`` on the root
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_thread_sets_resolved_on_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _patch_db(monkeypatch)
    _seed_session(store)

    root = await cmt_service.create_comment(
        session_id=uuid.UUID(_SESSION_ID),
        author_id=uuid.UUID(_AUTHOR_ID),
        anchor_type=AnchorType.ENGAGEMENT,
        anchor_ref=None,
        body="Engagement-level question.",
    )
    assert root.ok

    res = await cmt_service.resolve_thread(
        uuid.UUID(root.comment_id), uuid.UUID(_OTHER_USER_ID),
    )
    assert res.ok
    row = store["comments"][root.comment_id]
    assert row["resolved"] is True
    assert row["resolved_by"] == _OTHER_USER_ID
    assert row["resolved_at"] is not None

    # And unresolve flips back.
    res2 = await cmt_service.unresolve_thread(
        uuid.UUID(root.comment_id), uuid.UUID(_OTHER_USER_ID),
    )
    assert res2.ok
    assert store["comments"][root.comment_id]["resolved"] is False
    assert store["comments"][root.comment_id]["resolved_by"] is None


# ---------------------------------------------------------------------------
# Test 6 — resolving a reply is rejected (root-only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_only_meaningful_on_root_not_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _patch_db(monkeypatch)
    _seed_session(store)

    root = await cmt_service.create_comment(
        session_id=uuid.UUID(_SESSION_ID),
        author_id=uuid.UUID(_AUTHOR_ID),
        anchor_type=AnchorType.ENGAGEMENT,
        anchor_ref=None,
        body="Root.",
    )
    reply = await cmt_service.reply_to_comment(
        parent_comment_id=uuid.UUID(root.comment_id),
        author_id=uuid.UUID(_OTHER_USER_ID),
        body="Reply.",
    )

    res = await cmt_service.resolve_thread(
        uuid.UUID(reply.comment_id), uuid.UUID(_OTHER_USER_ID),
    )
    assert not res.ok
    assert res.status_code == 409
    assert "root" in res.reason.lower()


# ---------------------------------------------------------------------------
# Test 7 — edit is author-only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_comment_author_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _patch_db(monkeypatch)
    _seed_session(store)

    root = await cmt_service.create_comment(
        session_id=uuid.UUID(_SESSION_ID),
        author_id=uuid.UUID(_AUTHOR_ID),
        anchor_type=AnchorType.ENGAGEMENT,
        anchor_ref=None,
        body="Original body.",
    )

    # Author can edit.
    ok = await cmt_service.edit_comment(
        uuid.UUID(root.comment_id),
        uuid.UUID(_AUTHOR_ID),
        "Updated body.",
    )
    assert ok.ok
    assert store["comments"][root.comment_id]["body"] == "Updated body."
    assert store["comments"][root.comment_id]["edited_at"] is not None

    # Non-author cannot edit — 403.
    blocked = await cmt_service.edit_comment(
        uuid.UUID(root.comment_id),
        uuid.UUID(_OTHER_USER_ID),
        "Trying to edit someone else's comment.",
    )
    assert not blocked.ok
    assert blocked.status_code == 403
    assert "author" in blocked.reason.lower()
    # Body unchanged.
    assert store["comments"][root.comment_id]["body"] == "Updated body."


# ---------------------------------------------------------------------------
# Test 8 — delete is soft (deleted_at set; row remains)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_is_soft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _patch_db(monkeypatch)
    _seed_session(store)

    root = await cmt_service.create_comment(
        session_id=uuid.UUID(_SESSION_ID),
        author_id=uuid.UUID(_AUTHOR_ID),
        anchor_type=AnchorType.ENGAGEMENT,
        anchor_ref=None,
        body="To be deleted.",
    )

    # Author can delete.
    ok = await cmt_service.delete_comment(
        uuid.UUID(root.comment_id), uuid.UUID(_AUTHOR_ID),
    )
    assert ok.ok
    # Row still exists in the table, but deleted_at is set.
    row = store["comments"][root.comment_id]
    assert row["deleted_at"] is not None
    assert row["body"] == "To be deleted.", "body must be preserved for audit"

    # Admin can also delete (different comment to avoid the already-
    # deleted guard).
    root2 = await cmt_service.create_comment(
        session_id=uuid.UUID(_SESSION_ID),
        author_id=uuid.UUID(_AUTHOR_ID),
        anchor_type=AnchorType.ENGAGEMENT,
        anchor_ref=None,
        body="Admin deletes this one.",
    )
    ok_admin = await cmt_service.delete_comment(
        uuid.UUID(root2.comment_id), uuid.UUID(_ADMIN_USER_ID),
    )
    assert ok_admin.ok
    assert store["comments"][root2.comment_id]["deleted_at"] is not None

    # A non-author, non-admin can't delete — 403.
    root3 = await cmt_service.create_comment(
        session_id=uuid.UUID(_SESSION_ID),
        author_id=uuid.UUID(_AUTHOR_ID),
        anchor_type=AnchorType.ENGAGEMENT,
        anchor_ref=None,
        body="Someone else tries to delete this.",
    )
    blocked = await cmt_service.delete_comment(
        uuid.UUID(root3.comment_id), uuid.UUID(_OTHER_USER_ID),
    )
    assert not blocked.ok
    assert blocked.status_code == 403


# ---------------------------------------------------------------------------
# Test 9 — text_range orphan detected when quoted text disappears
# ---------------------------------------------------------------------------


def test_text_range_orphan_detected_after_text_change() -> None:
    """Pure-function check on :func:`is_text_range_orphaned`."""
    original_payload = {
        "synergy_estimate": {
            "revenue_synergies": [
                {"type": "Cross-sell pallet capacity",
                 "rationale": "Bidder's existing UK customer base overlaps in 12 named accounts."},
            ],
        },
    }
    comment = {
        "anchor_type": "text_range",
        "anchor_ref": {
            "section_path": "synergy_estimate",
            "start": 0, "end": 50,
            "quoted_text": "overlaps in 12 named accounts",
        },
    }
    # Quote still present in the section → not orphaned.
    assert is_text_range_orphaned(comment, original_payload) is False

    # Payload mutates — quoted substring gone after a section rewrite.
    mutated_payload = {
        "synergy_estimate": {
            "revenue_synergies": [
                {"type": "Cross-sell pallet capacity",
                 "rationale": "Bidder's existing UK customer base shares 9 accounts."},
            ],
        },
    }
    assert is_text_range_orphaned(comment, mutated_payload) is True

    # Section removed entirely → orphaned.
    removed_payload = {"synergy_estimate": {"revenue_synergies": []}}
    assert is_text_range_orphaned(comment, removed_payload) is True

    # Non-text_range anchor → always False (orphan check is text-range
    # specific).
    section_comment = {
        "anchor_type": "section",
        "anchor_ref": {"section_path": "synergy_estimate"},
    }
    assert is_text_range_orphaned(section_comment, original_payload) is False


# ---------------------------------------------------------------------------
# Test 10 — engagement anchor is always valid (no target required)
# ---------------------------------------------------------------------------


def test_engagement_anchor_always_valid() -> None:
    """Pure-function check on :func:`validate_anchor`."""
    # Engagement anchor passes with no anchor_ref + no payload.
    res = validate_anchor(AnchorType.ENGAGEMENT, None)
    assert res.ok
    assert res.reason == ""

    # Even when anchor_ref carries junk, engagement still passes
    # (the spec is "anchor_ref ignored").
    res2 = validate_anchor(AnchorType.ENGAGEMENT, {"random": "garbage"})
    assert res2.ok

    # Other types fail without a payload.
    res3 = validate_anchor(AnchorType.SECTION, {"section_path": "x"})
    assert not res3.ok
    assert "payload" in res3.reason.lower()
