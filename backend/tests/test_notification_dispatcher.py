"""Phase 4 / Week 18 / Day 1 — notification dispatcher tests.

Ten tests per spec. In-memory DB fake mirroring the W17 / W16
pattern, extended with notifications + notification_preferences
backing.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest import mock

import pytest

from core.notifications import (
    NotificationEvent,
    NotificationType,
    default_preference,
    dispatch,
    dispatch_batch,
    render_summary,
    resolve_recipients,
)
from core.notifications import dispatcher as dispatcher_mod
from core.notifications import recipients as recipients_mod


_FIRM_ID = "11111111-1111-1111-1111-111111111111"
_SESSION_ID = "33333333-3333-3333-3333-333333333333"
_LEAD_ID = "44444444-4444-4444-4444-444444444444"
_CONTRIB_ID = "55555555-5555-5555-5555-555555555555"
_PARTNER_ID = "66666666-6666-6666-6666-666666666666"
_OTHER_ID = "77777777-7777-7777-7777-777777777777"


def _build_store() -> dict[str, Any]:
    """Seed: session with W15 review_assigned_to=partner +
    submitted_by=lead + created_by_user_id=lead; engagement
    memberships place lead as 'lead' and contrib as 'contributor'."""
    return {
        "sessions": {
            _SESSION_ID: {
                "firm_id": _FIRM_ID,
                "review_assigned_to": _PARTNER_ID,
                "submitted_by": _LEAD_ID,
                "created_by_user_id": _LEAD_ID,
            },
        },
        "members": {
            (_SESSION_ID, _LEAD_ID): {"role": "lead", "removed_at": None},
            (_SESSION_ID, _CONTRIB_ID): {"role": "contributor", "removed_at": None},
            (_SESSION_ID, _PARTNER_ID): {"role": "reviewer", "removed_at": None},
        },
        # users by id → (full_name, email) used by _actor_display_name
        "users": {
            _LEAD_ID: ("Helena Voss", "helena@m.invalid"),
            _CONTRIB_ID: ("Marcus Thorne", "marcus@m.invalid"),
            _PARTNER_ID: ("Sarah Kim", "sarah@m.invalid"),
            _OTHER_ID: ("Priya Shah", "priya@m.invalid"),
        },
        "comments": {},   # id -> row (used for thread participant resolution)
        "preferences": {},  # (user_id, notification_type) -> (in_app, email)
        "notifications": [],  # appended rows
    }


def _seed_comment_thread(store: dict[str, Any], root_author: str,
                          reply_authors: list[str]) -> str:
    root_id = str(uuid.uuid4())
    store["comments"][root_id] = {
        "id": root_id, "author_id": root_author,
        "parent_comment_id": None, "deleted_at": None,
    }
    for ra in reply_authors:
        rid = str(uuid.uuid4())
        store["comments"][rid] = {
            "id": rid, "author_id": ra,
            "parent_comment_id": root_id, "deleted_at": None,
        }
    return root_id


def _patch_db(monkeypatch: pytest.MonkeyPatch, store: dict[str, Any]) -> None:
    async def fetchrow(sql: str, *args: Any) -> dict[str, Any] | None:
        s = " ".join(sql.split())
        # engagement_memberships lead lookup
        if "engagement_memberships" in s and "role = 'lead'" in s and "LIMIT 1" in s:
            sid = str(args[0])
            for (s_id, u_id), m in store["members"].items():
                if s_id == sid and m["role"] == "lead" and m["removed_at"] is None:
                    return {"user_id": u_id}
            return None
        # sessions review state columns
        if "review_assigned_to, submitted_by, created_by_user_id" in s:
            sid = str(args[0])
            sess = store["sessions"].get(sid)
            return sess if sess else None
        # users display name lookup
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
            in_app, email = pref
            return {"in_app": in_app, "email": email}
        # notifications INSERT
        if "INSERT INTO notifications" in s and "RETURNING" in s:
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
        return None

    async def fetch(sql: str, *args: Any) -> list[dict[str, Any]]:
        s = " ".join(sql.split())
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
        return "UPDATE 0"

    fake_conn = mock.MagicMock()
    fake_conn.fetchrow = fetchrow
    fake_conn.fetch = fetch
    fake_conn.execute = execute

    class _AcquireCM:
        async def __aenter__(self):
            return fake_conn
        async def __aexit__(self, *a):
            return None

    def _acquire():
        return _AcquireCM()

    monkeypatch.setattr(dispatcher_mod, "acquire", _acquire)
    monkeypatch.setattr(recipients_mod, "acquire", _acquire)


# ---------------------------------------------------------------------------
# 1. Happy path — dispatch creates in-app notification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_creates_in_app_notification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    event = NotificationEvent(
        notification_type=NotificationType.MENTION,
        session_id=uuid.UUID(_SESSION_ID),
        firm_id=uuid.UUID(_FIRM_ID),
        actor_id=uuid.UUID(_LEAD_ID),
        source_ref={"comment_id": "c-1"},
        context={
            "mentioned_user_ids": [_CONTRIB_ID],
            "engagement_title": "Kestrel",
            "body_preview": "Take another look at synergy.",
        },
    )
    out = await dispatch(event)
    assert len(out) == 1
    assert out[0].recipient_id == _CONTRIB_ID
    assert out[0].notification_type == NotificationType.MENTION.value
    assert "mentioned you" in out[0].summary
    assert out[0].email_status == "pending"  # MENTION default = email on


# ---------------------------------------------------------------------------
# 2. Actor excluded from their own action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_actor_excluded_from_own_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    # Self-mention: the lead mentions themselves.
    event = NotificationEvent(
        notification_type=NotificationType.MENTION,
        session_id=uuid.UUID(_SESSION_ID),
        firm_id=uuid.UUID(_FIRM_ID),
        actor_id=uuid.UUID(_LEAD_ID),
        source_ref={"comment_id": "c-self"},
        context={
            "mentioned_user_ids": [_LEAD_ID, _CONTRIB_ID],
            "engagement_title": "Kestrel",
        },
    )
    out = await dispatch(event)
    # Lead (the actor) gets nothing; contrib gets the mention.
    recipients = {n.recipient_id for n in out}
    assert _LEAD_ID not in recipients
    assert _CONTRIB_ID in recipients


# ---------------------------------------------------------------------------
# 3. Dedup — multi-path recipient gets ONE notification (mention wins)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dedup_collapses_multi_path_recipient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reply on a thread that the contributor already participates
    in AND mentions the contributor → one notification (MENTION
    wins on priority, not COMMENT_REPLY)."""
    store = _build_store()
    _patch_db(monkeypatch, store)

    root_id = _seed_comment_thread(
        store, root_author=_CONTRIB_ID, reply_authors=[],
    )
    # Lead now posts a reply that ALSO mentions the contributor.
    common_source = {"comment_id": "reply-1"}
    mention_event = NotificationEvent(
        notification_type=NotificationType.MENTION,
        session_id=uuid.UUID(_SESSION_ID),
        firm_id=uuid.UUID(_FIRM_ID),
        actor_id=uuid.UUID(_LEAD_ID),
        source_ref=common_source,
        context={"mentioned_user_ids": [_CONTRIB_ID],
                 "engagement_title": "Kestrel"},
    )
    reply_event = NotificationEvent(
        notification_type=NotificationType.COMMENT_REPLY,
        session_id=uuid.UUID(_SESSION_ID),
        firm_id=uuid.UUID(_FIRM_ID),
        actor_id=uuid.UUID(_LEAD_ID),
        source_ref=common_source,
        context={"root_comment_id": root_id,
                 "engagement_title": "Kestrel"},
    )

    out = await dispatch_batch([mention_event, reply_event])
    assert len(out) == 1
    assert out[0].recipient_id == _CONTRIB_ID
    # Mention wins over comment_reply on TYPE_PRIORITY.
    assert out[0].notification_type == NotificationType.MENTION.value


# ---------------------------------------------------------------------------
# 4. Preference: email disabled → email_status='skipped'
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preference_respected_email_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    # Contributor opts out of email for mentions.
    store["preferences"][(_CONTRIB_ID, NotificationType.MENTION.value)] = (True, False)

    event = NotificationEvent(
        notification_type=NotificationType.MENTION,
        session_id=uuid.UUID(_SESSION_ID),
        firm_id=uuid.UUID(_FIRM_ID),
        actor_id=uuid.UUID(_LEAD_ID),
        source_ref={"comment_id": "c-1"},
        context={"mentioned_user_ids": [_CONTRIB_ID],
                 "engagement_title": "Kestrel"},
    )
    out = await dispatch(event)
    assert len(out) == 1
    assert out[0].email_status == "skipped"


# ---------------------------------------------------------------------------
# 5. Default preference when no row exists
# ---------------------------------------------------------------------------


def test_default_preference_when_no_row() -> None:
    # No DB roundtrip needed; the defaults module is the source of truth.
    in_app, email = default_preference(NotificationType.MENTION)
    assert in_app is True and email is True
    in_app, email = default_preference(NotificationType.SECTION_ASSIGNED)
    assert in_app is True and email is False
    # Unknown values fall back to in-app-only.
    in_app, email = default_preference("not_a_real_type")
    assert in_app is True and email is False


# ---------------------------------------------------------------------------
# 6. Recipient resolution: MENTION uses mentioned_user_ids
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recipient_resolution_mention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    event = NotificationEvent(
        notification_type=NotificationType.MENTION,
        session_id=uuid.UUID(_SESSION_ID),
        firm_id=uuid.UUID(_FIRM_ID),
        actor_id=uuid.UUID(_LEAD_ID),
        source_ref={},
        context={"mentioned_user_ids": [_CONTRIB_ID, _PARTNER_ID]},
    )
    recips = await resolve_recipients(event)
    assert set(str(r) for r in recips) == {_CONTRIB_ID, _PARTNER_ID}


# ---------------------------------------------------------------------------
# 7. COMMENT_REPLY recipient resolution excludes the actor + dedups
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recipient_resolution_comment_reply_excludes_actor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    # Thread: contrib (root) + partner (replied). Lead now replies.
    root_id = _seed_comment_thread(
        store, root_author=_CONTRIB_ID, reply_authors=[_PARTNER_ID],
    )
    event = NotificationEvent(
        notification_type=NotificationType.COMMENT_REPLY,
        session_id=uuid.UUID(_SESSION_ID),
        firm_id=uuid.UUID(_FIRM_ID),
        actor_id=uuid.UUID(_LEAD_ID),
        source_ref={"comment_id": "reply-2"},
        context={"root_comment_id": root_id,
                 "engagement_title": "Kestrel"},
    )
    out = await dispatch(event)
    # Contrib + partner get notified; lead (actor) does not.
    recipients = {n.recipient_id for n in out}
    assert recipients == {_CONTRIB_ID, _PARTNER_ID}
    # And exactly one row per recipient.
    assert len(out) == 2


# ---------------------------------------------------------------------------
# 8. REVIEW_REQUESTED targets the assigned reviewer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recipient_resolution_review_requested_targets_reviewer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    event = NotificationEvent(
        notification_type=NotificationType.REVIEW_REQUESTED,
        session_id=uuid.UUID(_SESSION_ID),
        firm_id=uuid.UUID(_FIRM_ID),
        actor_id=uuid.UUID(_LEAD_ID),
        source_ref={"review_record_id": "rr-1"},
        context={"engagement_title": "Kestrel"},
    )
    out = await dispatch(event)
    assert len(out) == 1
    assert out[0].recipient_id == _PARTNER_ID  # sessions.review_assigned_to
    assert "submitted" in out[0].summary.lower()


# ---------------------------------------------------------------------------
# 9. CHANGES_REQUESTED targets submitter + lead (minus actor)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recipient_resolution_changes_requested_targets_submitter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    # Partner requests changes; submitter = lead (per seed).
    # Lead is also the engagement lead — so the resolver returns
    # only the lead once (dedup).
    event = NotificationEvent(
        notification_type=NotificationType.CHANGES_REQUESTED,
        session_id=uuid.UUID(_SESSION_ID),
        firm_id=uuid.UUID(_FIRM_ID),
        actor_id=uuid.UUID(_PARTNER_ID),
        source_ref={"review_record_id": "rr-2"},
        context={"engagement_title": "Kestrel", "severity": "blocking"},
    )
    out = await dispatch(event)
    recipients = {n.recipient_id for n in out}
    assert _LEAD_ID in recipients
    assert _PARTNER_ID not in recipients   # actor excluded
    # Summary carries the severity hint.
    lead_notif = next(n for n in out if n.recipient_id == _LEAD_ID)
    assert "blocking" in lead_notif.summary.lower()


# ---------------------------------------------------------------------------
# 10. Summary rendering per type
# ---------------------------------------------------------------------------


def test_summary_rendering_per_type() -> None:
    ctx = {"engagement_title": "Kestrel Logistics",
           "section_path": "synergy_estimate",
           "body_preview": "Take another look at the cross-sell line.",
           "severity": "blocking",
           "task_title": "Ping client lawyer",
           "role": "contributor"}

    mention = render_summary(NotificationType.MENTION, "Helena Voss", ctx)
    assert "Helena Voss" in mention
    assert "synergy_estimate" in mention
    assert "Kestrel" in mention

    cr = render_summary(NotificationType.CHANGES_REQUESTED, "Helena Voss", ctx)
    assert "requested changes" in cr.lower()
    assert "blocking" in cr.lower()

    ea = render_summary(NotificationType.ENGAGEMENT_ASSIGNED, "Helena Voss", ctx)
    assert "added you" in ea.lower()
    assert "contributor" in ea.lower()

    snr = render_summary(NotificationType.SECTION_NEEDS_REVIEW, "Marcus", ctx)
    assert "needs review" in snr.lower()
    assert "synergy_estimate" in snr

    ta = render_summary(NotificationType.TASK_ASSIGNED, "Helena Voss", ctx)
    assert "Ping client lawyer" in ta
