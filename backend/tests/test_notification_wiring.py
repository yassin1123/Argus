"""Phase 4 / Week 18 / Day 2 — wiring tests.

Eleven tests per spec. Each test wires through a real service call
(comments / review / membership / section / task) and verifies the
notifications table receives the right row shape.

In-memory DB fake covers every backing query the wiring helpers
+ the underlying services touch.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest import mock

import pytest

from core.notifications import dispatcher as dispatcher_mod
from core.notifications import recipients as recipients_mod
from core.notifications import wiring as wiring_mod


_FIRM_ID = "11111111-1111-1111-1111-111111111111"
_SESSION_ID = "33333333-3333-3333-3333-333333333333"
_LEAD_ID = "44444444-4444-4444-4444-444444444444"
_CONTRIB_ID = "55555555-5555-5555-5555-555555555555"
_PARTNER_ID = "66666666-6666-6666-6666-666666666666"
_ANALYST_ID = "77777777-7777-7777-7777-777777777777"


def _build_store() -> dict[str, Any]:
    return {
        "sessions": {
            _SESSION_ID: {
                "firm_id": _FIRM_ID,
                "title": "Kestrel Logistics — M&A diligence",
                "review_assigned_to": _PARTNER_ID,
                "submitted_by": _LEAD_ID,
                "created_by_user_id": _LEAD_ID,
            },
        },
        "firm_memberships": {
            (_FIRM_ID, _LEAD_ID): "member",
            (_FIRM_ID, _CONTRIB_ID): "member",
            (_FIRM_ID, _PARTNER_ID): "member",
            (_FIRM_ID, _ANALYST_ID): "member",
        },
        "members": {
            (_SESSION_ID, _LEAD_ID): {"role": "lead", "removed_at": None},
            (_SESSION_ID, _CONTRIB_ID): {"role": "contributor", "removed_at": None},
            (_SESSION_ID, _PARTNER_ID): {"role": "reviewer", "removed_at": None},
        },
        "users": {
            _LEAD_ID: ("Helena Voss", "helena@m.invalid"),
            _CONTRIB_ID: ("Marcus Thorne", "marcus@m.invalid"),
            _PARTNER_ID: ("Sarah Kim", "sarah@m.invalid"),
            _ANALYST_ID: ("Priya Shah", "priya@m.invalid"),
        },
        "comments": {},
        "section_assignments": {},
        "engagement_tasks": {},
        "preferences": {},
        "notifications": [],
        "audit": [],
        # Optional flag to make notifications INSERT raise.
        "fail_notification_inserts": False,
    }


def _patch_db(monkeypatch: pytest.MonkeyPatch, store: dict[str, Any]) -> None:
    """Single fake covering every service the wiring tests touch:
    comments service, review service stubs, collaboration services,
    audit log, notifications + recipient resolution."""

    async def fetchrow(sql: str, *args: Any) -> dict[str, Any] | None:
        s = " ".join(sql.split())

        # sessions: firm_id only
        if "FROM sessions WHERE id" in s and "firm_id" in s and "review_state" not in s and "review_assigned_to" not in s and "title" not in s:
            sid = str(args[0])
            sess = store["sessions"].get(sid)
            return {"firm_id": sess["firm_id"]} if sess else None
        # sessions: title (for wiring _load_engagement_title)
        if "SELECT title FROM sessions" in s:
            sid = str(args[0])
            sess = store["sessions"].get(sid)
            return {"title": sess["title"]} if sess else None
        # sessions: review_assigned_to + submitted_by + created_by_user_id
        if "review_assigned_to, submitted_by, created_by_user_id" in s:
            sid = str(args[0])
            sess = store["sessions"].get(sid)
            return sess if sess else None

        # firm_memberships role lookup
        if "FROM firm_memberships" in s and "role" in s and "SELECT 1" not in s:
            firm, uid = str(args[0]), str(args[1])
            role = store["firm_memberships"].get((firm, uid))
            return {"role": role} if role else None
        if "FROM firm_memberships" in s and "SELECT 1" in s:
            firm, uid = str(args[0]), str(args[1])
            return {"?column?": 1} if (firm, uid) in store["firm_memberships"] else None

        # engagement_memberships: active row lookup
        if "FROM engagement_memberships em" in s and "em.user_id" in s and "LIMIT 1" not in s and "ORDER BY" not in s:
            sid, uid = str(args[0]), str(args[1])
            m = store["members"].get((sid, uid))
            if m and m["removed_at"] is None:
                return {
                    "id": str(uuid.uuid4()), "engagement_id": sid, "user_id": uid,
                    "role": m["role"], "added_by": _LEAD_ID,
                    "added_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
                    "removed_at": None, "firm_id": _FIRM_ID,
                }
            return None
        # engagement_memberships: active lead lookup
        if "engagement_memberships" in s and "role = 'lead'" in s and "LIMIT 1" in s and "<>" not in s and "JOIN" not in s:
            sid = str(args[0])
            for (s_id, u_id), m in store["members"].items():
                if s_id == sid and m["role"] == "lead" and m["removed_at"] is None:
                    return {"user_id": u_id}
            return None

        # users name lookup
        if "FROM users WHERE id" in s:
            uid = str(args[0])
            tup = store["users"].get(uid)
            if not tup:
                return None
            return {"full_name": tup[0], "email": tup[1]}

        # notification_preferences
        if "FROM notification_preferences" in s:
            uid, nt = str(args[0]), args[1]
            pref = store["preferences"].get((uid, nt))
            if pref is None:
                return None
            return {"in_app": pref[0], "email": pref[1]}

        # notifications INSERT
        if "INSERT INTO notifications" in s and "RETURNING" in s:
            if store.get("fail_notification_inserts"):
                raise RuntimeError("simulated notification insert failure")
            nid = str(uuid.uuid4())
            row = {
                "id": nid,
                "recipient_id": str(args[0]),
                "firm_id": str(args[1]),
                "notification_type": args[2],
                "session_id": str(args[3]) if args[3] else None,
                "source_ref": json.loads(args[4]) if args[4] else {},
                "actor_id": str(args[5]) if args[5] else None,
                "summary": args[6],
                "read": False,
                "read_at": None,
                "created_at": datetime.now(tz=timezone.utc),
                "email_status": args[7],
            }
            store["notifications"].append(row)
            return row

        # Comments service backing
        if "FROM sessions WHERE id" in s and ("firm_id" in s):
            sid = str(args[0])
            sess = store["sessions"].get(sid)
            return {"firm_id": sess["firm_id"]} if sess else None
        if "FROM reports WHERE session_id" in s:
            # Comments service's _load_session_payload; return a minimal
            # shape good enough for engagement anchor validation.
            return {
                "recommendation": "PROCEED",
                "confidence_level": "Medium",
                "summary": "x",
                "key_reasons": [],
                "risks": [], "counterarguments": [], "next_steps": [],
                "sources": [], "caveats": "",
                "consulting_payload": {},
            }
        if "FROM comments WHERE id" in s:
            cid = str(args[0])
            return store["comments"].get(cid)
        if "INSERT INTO comments" in s and "RETURNING" in s:
            new_id = str(uuid.uuid4())
            now = datetime.now(tz=timezone.utc)
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
                "session_id": str(args[0]),
                "firm_id": str(args[1]),
                "parent_comment_id": str(parent_id) if parent_id else None,
                "anchor_type": anchor_type,
                "anchor_ref": json.loads(anchor_ref_json or "{}"),
                "body": body,
                "mentioned_user_ids": json.loads(mentions_json or "[]"),
                "author_id": author_id,
                "resolved": False, "resolved_by": None, "resolved_at": None,
                "created_at": now, "updated_at": now,
                "edited_at": None, "deleted_at": None,
            }
            store["comments"][new_id] = row
            return row

        # Section assignments
        if "FROM section_assignments" in s and "WHERE session_id" in s and "section_path" in s and "ORDER BY" not in s:
            sid, path = str(args[0]), args[1]
            return store["section_assignments"].get((sid, path))
        if "INSERT INTO section_assignments" in s and "RETURNING" in s:
            sid, firm, path, assigned_to, assigned_by = (
                str(args[0]), str(args[1]), args[2], str(args[3]), str(args[4]),
            )
            now = datetime.now(tz=timezone.utc)
            row = {
                "id": str(uuid.uuid4()),
                "session_id": sid, "firm_id": firm,
                "section_path": path,
                "assigned_to": assigned_to, "assigned_by": assigned_by,
                "status": "not_started",
                "assigned_at": now, "updated_at": now,
            }
            store["section_assignments"][(sid, path)] = row
            return row
        if "UPDATE section_assignments" in s and "SET status" in s and "RETURNING" in s:
            sid, path, status = str(args[0]), args[1], args[2]
            row = store["section_assignments"].get((sid, path))
            if not row:
                return None
            row["status"] = status
            row["updated_at"] = datetime.now(tz=timezone.utc)
            return row

        # engagement_memberships UPSERT (for assign_member)
        if "INSERT INTO engagement_memberships" in s and "RETURNING" in s:
            sid, uid = str(args[0]), str(args[1])
            if len(args) >= 4:
                role, added_by = args[2], str(args[3])
            else:
                role, added_by = "lead", uid
            row = {
                "id": str(uuid.uuid4()),
                "engagement_id": sid, "user_id": uid,
                "role": role, "added_by": added_by,
                "added_at": datetime.now(tz=timezone.utc),
                "removed_at": None,
            }
            store["members"][(sid, uid)] = {"role": role, "removed_at": None}
            return row

        # engagement_tasks INSERT
        if "INSERT INTO engagement_tasks" in s and "RETURNING" in s:
            tid = str(uuid.uuid4())
            row = {
                "id": tid, "session_id": str(args[0]), "firm_id": str(args[1]),
                "title": args[2],
                "assigned_to": str(args[3]) if args[3] else None,
                "created_by": str(args[4]), "section_path": args[5],
                "done": False, "done_at": None,
                "created_at": datetime.now(tz=timezone.utc),
            }
            store["engagement_tasks"][tid] = row
            return row

        return None

    async def fetch(sql: str, *args: Any) -> list[dict[str, Any]]:
        s = " ".join(sql.split())
        # Comment thread participants (for COMMENT_REPLY recipient resolver)
        if "FROM comments" in s and "id = $1::uuid OR parent_comment_id" in s:
            root_id = str(args[0])
            ids: list[str] = []
            for c in store["comments"].values():
                if c["deleted_at"] is not None:
                    continue
                if c["id"] == root_id or c["parent_comment_id"] == root_id:
                    if c["author_id"] not in ids:
                        ids.append(c["author_id"])
            return [{"author_id": uuid.UUID(uid)} for uid in ids]
        return []

    async def execute(sql: str, *args: Any) -> str:
        s = " ".join(sql.split())
        if "INSERT INTO audit_events" in s:
            store["audit"].append({
                "actor_user_id": args[0],
                "action": args[2],
                "resource_type": args[3],
                "resource_id": args[4],
                "payload": (json.loads(args[10]) if len(args) > 10 and args[10] else {}),
            })
        return "UPDATE 0"

    async def fetchval(sql: str, *args: Any) -> Any:
        return None

    fake_conn = mock.MagicMock()
    fake_conn.fetchrow = fetchrow
    fake_conn.fetch = fetch
    fake_conn.execute = execute
    fake_conn.fetchval = fetchval

    class _AcquireCM:
        async def __aenter__(self):
            return fake_conn
        async def __aexit__(self, *a):
            return None

    def _acquire():
        return _AcquireCM()

    import audit.queries as _audit_q
    import core.comments.service as _comments_svc
    import core.collaboration.membership as _memb
    import core.collaboration.section_assignments as _sa
    import core.collaboration.explicit_tasks as _et
    monkeypatch.setattr(dispatcher_mod, "acquire", _acquire)
    monkeypatch.setattr(recipients_mod, "acquire", _acquire)
    monkeypatch.setattr(wiring_mod, "acquire", _acquire)
    monkeypatch.setattr(_comments_svc, "acquire", _acquire)
    monkeypatch.setattr(_memb, "acquire", _acquire)
    monkeypatch.setattr(_sa, "acquire", _acquire)
    monkeypatch.setattr(_et, "acquire", _acquire)
    monkeypatch.setattr(_audit_q, "acquire", _acquire)


def _notifs_for(store: dict[str, Any], recipient_id: str) -> list[dict[str, Any]]:
    return [n for n in store["notifications"] if n["recipient_id"] == recipient_id]


def _notifs_of_type(
    store: dict[str, Any], notification_type: str,
) -> list[dict[str, Any]]:
    return [n for n in store["notifications"] if n["notification_type"] == notification_type]


# ---------------------------------------------------------------------------
# 1. MENTION wired through create_comment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mention_generates_notification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    from core.comments.service import create_comment
    from core.comments.anchors import AnchorType

    res = await create_comment(
        session_id=uuid.UUID(_SESSION_ID),
        author_id=uuid.UUID(_LEAD_ID),
        anchor_type=AnchorType.ENGAGEMENT,
        anchor_ref={},
        body=f"Heads up @priya — take a look.",
        mentioned_user_ids=[_ANALYST_ID],
    )
    assert res.ok, res.reason
    mentions = _notifs_of_type(store, "mention")
    assert len(mentions) == 1
    assert mentions[0]["recipient_id"] == _ANALYST_ID
    assert mentions[0]["actor_id"] == _LEAD_ID


# ---------------------------------------------------------------------------
# 2. COMMENT_REPLY wired through reply_to_comment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reply_notifies_thread_participants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    from core.comments.service import create_comment, reply_to_comment
    from core.comments.anchors import AnchorType

    root = await create_comment(
        session_id=uuid.UUID(_SESSION_ID),
        author_id=uuid.UUID(_CONTRIB_ID),
        anchor_type=AnchorType.ENGAGEMENT, anchor_ref={},
        body="Initial thought.",
    )
    assert root.ok
    # Partner replies to the contrib's root. Contrib should get a
    # COMMENT_REPLY notification; partner (actor) does not.
    rep = await reply_to_comment(
        parent_comment_id=uuid.UUID(root.comment_id),
        author_id=uuid.UUID(_PARTNER_ID),
        body="Pushing back on the basis.",
    )
    assert rep.ok
    replies = _notifs_of_type(store, "comment_reply")
    assert len(replies) == 1
    assert replies[0]["recipient_id"] == _CONTRIB_ID
    assert replies[0]["actor_id"] == _PARTNER_ID


# ---------------------------------------------------------------------------
# 3. Mention + reply dedup to ONE notification (MENTION wins)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mention_plus_reply_dedups_to_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    from core.comments.service import create_comment, reply_to_comment
    from core.comments.anchors import AnchorType

    # Root: contrib posts.
    root = await create_comment(
        session_id=uuid.UUID(_SESSION_ID),
        author_id=uuid.UUID(_CONTRIB_ID),
        anchor_type=AnchorType.ENGAGEMENT, anchor_ref={},
        body="Initial thought.",
    )
    # Reply: lead replies AND mentions the contrib. The contrib is
    # also a thread participant. dispatch_batch's dedup_key collapses
    # to ONE notification with notification_type=MENTION.
    rep = await reply_to_comment(
        parent_comment_id=uuid.UUID(root.comment_id),
        author_id=uuid.UUID(_LEAD_ID),
        body="@marcus your numbers — second pair of eyes?",
        mentioned_user_ids=[_CONTRIB_ID],
    )
    assert rep.ok
    contrib_notifs = _notifs_for(store, _CONTRIB_ID)
    assert len(contrib_notifs) == 1
    assert contrib_notifs[0]["notification_type"] == "mention"


# ---------------------------------------------------------------------------
# 4. submit_for_review → REVIEW_REQUESTED to reviewer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_notifies_reviewer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    from core.notifications.wiring import notify_review_transition

    await notify_review_transition(
        session_id=uuid.UUID(_SESSION_ID), firm_id=uuid.UUID(_FIRM_ID),
        actor_id=uuid.UUID(_LEAD_ID),
        action="submit_for_review",
        review_record_id="rr-1",
    )
    reqs = _notifs_of_type(store, "review_requested")
    assert len(reqs) == 1
    assert reqs[0]["recipient_id"] == _PARTNER_ID
    assert "submitted" in reqs[0]["summary"].lower()


# ---------------------------------------------------------------------------
# 5. request_changes → CHANGES_REQUESTED to submitter (+ lead)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_changes_notifies_submitter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    from core.notifications.wiring import notify_review_transition

    await notify_review_transition(
        session_id=uuid.UUID(_SESSION_ID), firm_id=uuid.UUID(_FIRM_ID),
        actor_id=uuid.UUID(_PARTNER_ID),  # partner = actor
        action="request_changes",
        review_record_id="rr-2",
        feedback={"severity": "blocking", "overall_note": "Tighten."},
    )
    crs = _notifs_of_type(store, "changes_requested")
    recipients = {n["recipient_id"] for n in crs}
    # Submitter = _LEAD_ID (per seed); excluded actor = partner.
    assert _LEAD_ID in recipients
    assert _PARTNER_ID not in recipients
    # Severity surfaces in the summary.
    lead_notif = next(n for n in crs if n["recipient_id"] == _LEAD_ID)
    assert "blocking" in lead_notif["summary"].lower()


# ---------------------------------------------------------------------------
# 6. approve → REVIEW_APPROVED to submitter + lead
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_notifies_submitter_and_lead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    from core.notifications.wiring import notify_review_transition

    await notify_review_transition(
        session_id=uuid.UUID(_SESSION_ID), firm_id=uuid.UUID(_FIRM_ID),
        actor_id=uuid.UUID(_PARTNER_ID),
        action="approve",
        review_record_id="rr-3",
    )
    notifs = _notifs_of_type(store, "review_approved")
    recipients = {n["recipient_id"] for n in notifs}
    # Lead is both submitter and lead in the seed → dedupes to one
    # row inside the recipient resolver.
    assert recipients == {_LEAD_ID}


# ---------------------------------------------------------------------------
# 7. assign_member → ENGAGEMENT_ASSIGNED to the new member
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_engagement_assign_notifies_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    from core.collaboration.membership import assign_member
    from core.collaboration.roles import EngagementRole

    res = await assign_member(
        session_id=uuid.UUID(_SESSION_ID),
        user_id=uuid.UUID(_ANALYST_ID),
        role=EngagementRole.CONTRIBUTOR,
        assigned_by=uuid.UUID(_LEAD_ID),
    )
    assert res.ok, res.reason
    notifs = _notifs_of_type(store, "engagement_assigned")
    assert len(notifs) == 1
    assert notifs[0]["recipient_id"] == _ANALYST_ID


# ---------------------------------------------------------------------------
# 8. assign_section → SECTION_ASSIGNED to the assignee
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_assign_notifies_assignee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    # Seed the report payload's synergy_estimate so the path validates.
    # (The fake DB returns a flat empty consulting_payload; we patch
    # _load_payload directly to skip that check.)
    from core.collaboration import section_assignments as sa_mod
    async def _fake_payload(_sid):
        return {"synergy_estimate": {"x": 1}}
    monkeypatch.setattr(sa_mod, "_load_payload", _fake_payload)

    res = await sa_mod.assign_section(
        session_id=uuid.UUID(_SESSION_ID),
        section_path="synergy_estimate",
        assigned_to=uuid.UUID(_CONTRIB_ID),
        assigned_by=uuid.UUID(_LEAD_ID),
    )
    assert res.ok, res.reason
    notifs = _notifs_of_type(store, "section_assigned")
    assert len(notifs) == 1
    assert notifs[0]["recipient_id"] == _CONTRIB_ID


# ---------------------------------------------------------------------------
# 9. set_section_status(needs_review) → SECTION_NEEDS_REVIEW to lead
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_needs_review_notifies_lead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    from core.collaboration import section_assignments as sa_mod
    from core.collaboration.section_status import SectionStatus

    async def _fake_payload(_sid):
        return {"synergy_estimate": {"x": 1}}
    monkeypatch.setattr(sa_mod, "_load_payload", _fake_payload)

    await sa_mod.assign_section(
        session_id=uuid.UUID(_SESSION_ID),
        section_path="synergy_estimate",
        assigned_to=uuid.UUID(_CONTRIB_ID),
        assigned_by=uuid.UUID(_LEAD_ID),
    )
    # Clear notifications so we only see the next event's output.
    store["notifications"] = []

    res = await sa_mod.set_section_status(
        session_id=uuid.UUID(_SESSION_ID),
        section_path="synergy_estimate",
        status=SectionStatus.NEEDS_REVIEW,
        actor_id=uuid.UUID(_CONTRIB_ID),
    )
    assert res.ok, res.reason
    notifs = _notifs_of_type(store, "section_needs_review")
    assert len(notifs) == 1
    assert notifs[0]["recipient_id"] == _LEAD_ID


# ---------------------------------------------------------------------------
# 10. create_task → TASK_ASSIGNED to assignee
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_assign_notifies_assignee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    from core.collaboration.explicit_tasks import create_task

    res = await create_task(
        session_id=uuid.UUID(_SESSION_ID),
        title="Ping client lawyer",
        created_by=uuid.UUID(_LEAD_ID),
        assigned_to=uuid.UUID(_CONTRIB_ID),
    )
    assert res.ok, res.reason
    notifs = _notifs_of_type(store, "task_assigned")
    assert len(notifs) == 1
    assert notifs[0]["recipient_id"] == _CONTRIB_ID
    assert "Ping client lawyer" in notifs[0]["summary"]


# ---------------------------------------------------------------------------
# 11. Notification failure does NOT break the core action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notification_failure_does_not_break_core_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hard rule: a notification-path failure must not roll back a
    committed comment / review / assignment. The wiring helper
    swallows + logs; the service still returns ok=True."""
    store = _build_store()
    _patch_db(monkeypatch, store)
    store["fail_notification_inserts"] = True

    from core.comments.service import create_comment
    from core.comments.anchors import AnchorType

    res = await create_comment(
        session_id=uuid.UUID(_SESSION_ID),
        author_id=uuid.UUID(_LEAD_ID),
        anchor_type=AnchorType.ENGAGEMENT, anchor_ref={},
        body="Hey @priya look here.",
        mentioned_user_ids=[_ANALYST_ID],
    )
    # Core action committed despite the notification path raising.
    assert res.ok
    assert res.comment_id is not None
    # And no notification rows landed (the INSERT raised).
    assert store["notifications"] == []
