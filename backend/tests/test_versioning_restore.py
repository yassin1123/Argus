"""Phase 4 / Week 19 / Day 2 — version diff + restore tests.

Nine tests per spec. In-memory DB fake covering the columns
versioning + restore + notification dispatch + audit touch.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest import mock

import pytest

from core.versioning import (
    ChangeType,
    create_version,
    diff_versions,
    restore_version,
)
from core.versioning import diff as diff_mod
from core.versioning import restore as restore_mod
from core.versioning import service as versioning_mod
from core.notifications import dispatcher as dispatcher_mod
from core.notifications import recipients as recipients_mod
from core.notifications import wiring as wiring_mod


_FIRM_ID = "11111111-1111-1111-1111-111111111111"
_SESSION_ID = "33333333-3333-3333-3333-333333333333"
_LEAD_ID = "44444444-4444-4444-4444-444444444444"
_CONTRIB_ID = "55555555-5555-5555-5555-555555555555"
_ADMIN_ID = "66666666-6666-6666-6666-666666666666"


def _build_store(review_state: str = "draft") -> dict[str, Any]:
    return {
        "sessions": {
            _SESSION_ID: {
                "firm_id": _FIRM_ID,
                "review_state": review_state,
                "created_by_user_id": _LEAD_ID,
            },
        },
        "members": {
            (_SESSION_ID, _LEAD_ID): {"role": "lead", "removed_at": None},
            (_SESSION_ID, _CONTRIB_ID): {"role": "contributor", "removed_at": None},
        },
        "firm_memberships": {
            (_FIRM_ID, _LEAD_ID): "member",
            (_FIRM_ID, _CONTRIB_ID): "member",
            (_FIRM_ID, _ADMIN_ID): "admin",
        },
        "users": {
            _LEAD_ID: ("Helena Voss", "helena@m.invalid"),
            _CONTRIB_ID: ("Marcus Thorne", "marcus@m.invalid"),
            _ADMIN_ID: ("Kira Lee", "kira@m.invalid"),
        },
        "versions": {},   # (sid, vn) -> row
        "reports": {
            _SESSION_ID: {
                "recommendation": "PROCEED", "summary": "current v",
            },
        },
        "deepening_runs": [],   # list of {session_id, status}
        "artifacts": {},        # id -> {session_id, status, metadata}
        "notifications": [],
        "audit": [],
        "review_revert_calls": [],
    }


def _patch_db(monkeypatch: pytest.MonkeyPatch, store: dict[str, Any]) -> None:
    async def fetchrow(sql: str, *args: Any) -> dict[str, Any] | None:
        s = " ".join(sql.split())
        if "SELECT firm_id, created_by_user_id, review_state" in s:
            sid = str(args[0])
            sess = store["sessions"].get(sid)
            return sess if sess else None
        if "SELECT firm_id FROM sessions" in s:
            sid = str(args[0])
            sess = store["sessions"].get(sid)
            return {"firm_id": sess["firm_id"]} if sess else None
        if "SELECT review_state FROM sessions" in s:
            sid = str(args[0])
            sess = store["sessions"].get(sid)
            return {"review_state": sess["review_state"]} if sess else None
        if "engagement_memberships" in s and "role = 'lead'" in s and "LIMIT 1" in s:
            sid = str(args[0])
            for (s_id, u_id), m in store["members"].items():
                if s_id == sid and m["role"] == "lead" and m["removed_at"] is None:
                    return {"user_id": u_id}
            return None
        if "FROM firm_memberships" in s and "role" in s and "SELECT 1" not in s:
            firm, uid = str(args[0]), str(args[1])
            role = store["firm_memberships"].get((firm, uid))
            return {"role": role} if role else None
        if "FROM section_deepening_runs" in s and "queued" in s and "running" in s:
            sid = str(args[0])
            for r in store["deepening_runs"]:
                if r["session_id"] == sid and r["status"] in ("queued", "running"):
                    return {"?column?": 1}
            return None
        if "FROM users WHERE id" in s:
            uid = str(args[0])
            tup = store["users"].get(uid)
            return {"full_name": tup[0], "email": tup[1]} if tup else None
        if "FROM notification_preferences" in s:
            return None
        if "SELECT title FROM sessions" in s:
            sid = str(args[0])
            sess = store["sessions"].get(sid)
            return {"title": "Kestrel"} if sess else None
        if "COALESCE(MAX(version_number)" in s:
            sid = str(args[0])
            max_v = max((vn for (s_id, vn) in store["versions"] if s_id == sid),
                        default=0)
            return {"n": max_v + 1}
        if "FROM payload_versions" in s and "ORDER BY version_number DESC" in s and "LIMIT 1" in s:
            sid = str(args[0])
            relevant = sorted(
                ((vn, v) for (s_id, vn), v in store["versions"].items() if s_id == sid),
                key=lambda t: t[0], reverse=True,
            )
            return relevant[0][1] if relevant else None
        if "FROM payload_versions" in s and "version_number = $2" in s:
            sid, vn = str(args[0]), int(args[1])
            return store["versions"].get((sid, vn))
        if "INSERT INTO payload_versions" in s and "RETURNING" in s:
            row = {
                "id": str(uuid.uuid4()),
                "session_id": str(args[0]),
                "firm_id": str(args[1]),
                "version_number": int(args[2]),
                "payload_snapshot": json.loads(args[3]),
                "change_type": args[4],
                "change_summary": args[5],
                "changed_section_paths": json.loads(args[6]),
                "review_state_at_version": args[7],
                "created_by": str(args[8]) if args[8] else None,
                "created_at": datetime.now(tz=timezone.utc),
            }
            store["versions"][(row["session_id"], row["version_number"])] = row
            return row
        if "INSERT INTO notifications" in s and "RETURNING" in s:
            nid = str(uuid.uuid4())
            row = {
                "id": nid, "recipient_id": str(args[0]),
                "firm_id": str(args[1]), "notification_type": args[2],
                "session_id": str(args[3]) if args[3] else None,
                "source_ref": json.loads(args[4]) if args[4] else {},
                "actor_id": str(args[5]) if args[5] else None,
                "summary": args[6], "read": False, "read_at": None,
                "created_at": datetime.now(tz=timezone.utc),
                "email_status": args[7],
            }
            store["notifications"].append(row)
            return row
        return None

    async def fetch(sql: str, *args: Any) -> list[dict[str, Any]]:
        s = " ".join(sql.split())
        if "UPDATE export_artifacts" in s and "RETURNING id" in s:
            sid = str(args[0])
            flipped = []
            for aid, art in store["artifacts"].items():
                if art["session_id"] == sid and art["status"] == "ready":
                    art["metadata"]["stale_since_revert"] = True
                    flipped.append({"id": aid})
            return flipped
        if "FROM payload_versions" in s and "ORDER BY version_number DESC" in s and "LIMIT" not in s:
            sid = str(args[0])
            rows = [v for (s_id, _vn), v in store["versions"].items() if s_id == sid]
            rows.sort(key=lambda r: r["version_number"], reverse=True)
            return rows
        return []

    async def execute(sql: str, *args: Any) -> str:
        s = " ".join(sql.split())
        if "UPDATE reports SET" in s:
            sid = str(args[0])
            r = store["reports"].setdefault(sid, {})
            r["recommendation"] = args[1]
            r["confidence_level"] = args[2]
            r["summary"] = args[3]
            r["key_reasons"] = json.loads(args[4])
            r["risks"] = json.loads(args[5])
            r["counterarguments"] = json.loads(args[6])
            r["next_steps"] = json.loads(args[7])
            r["sources"] = json.loads(args[8])
            r["caveats"] = args[9]
            r["consulting_payload"] = json.loads(args[10])
            return "UPDATE 1"
        if "INSERT INTO audit_events" in s:
            store["audit"].append({
                "actor_user_id": args[0],
                "action": args[2],
                "resource_type": args[3],
                "resource_id": args[4],
                "payload": json.loads(args[10]) if len(args) > 10 and args[10] else {},
            })
            return "INSERT 0 1"
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
    monkeypatch.setattr(versioning_mod, "acquire", _acquire)
    monkeypatch.setattr(restore_mod, "acquire", _acquire)
    monkeypatch.setattr(dispatcher_mod, "acquire", _acquire)
    monkeypatch.setattr(recipients_mod, "acquire", _acquire)
    monkeypatch.setattr(wiring_mod, "acquire", _acquire)
    monkeypatch.setattr(_audit_q, "acquire", _acquire)


def _stub_auto_revert(monkeypatch: pytest.MonkeyPatch, store: dict[str, Any]) -> None:
    """Replace W15 auto_revert_if_locked with a stub that flips the
    session's review_state to draft + records the call."""
    async def _fake_revert(session_id, actor_id, edit_label):
        sess = store["sessions"].get(str(session_id))
        if not sess or sess["review_state"] not in ("approved", "delivered"):
            return None
        sess["review_state"] = "draft"
        store["review_revert_calls"].append({
            "session_id": str(session_id),
            "actor_id": str(actor_id), "edit_label": edit_label,
        })
        return mock.MagicMock(ok=True, to_state="draft")
    import core.review.service as _rs
    monkeypatch.setattr(_rs, "auto_revert_if_locked", _fake_revert)


def _seed_two_versions(store: dict[str, Any]) -> None:
    """Insert v1 + v2 directly so the diff tests have a baseline."""
    v1 = {
        "id": str(uuid.uuid4()),
        "session_id": _SESSION_ID, "firm_id": _FIRM_ID,
        "version_number": 1,
        "payload_snapshot": {
            "recommendation": "PROCEED",
            "summary": "Initial: synergy basis is the load-bearing assumption.",
            "synergy_estimate": {
                "revenue_synergies": [
                    {"type": "Cross-sell", "magnitude_gbp_m": 5.0,
                     "basis_citations": ["claim_a"]},
                ],
            },
            "key_reasons": [
                {"text": "Gross margin resilient", "claim_id": "claim_a"},
            ],
            "recommendation_claim_ids": ["claim_a"],
        },
        "change_type": "initial", "change_summary": "Initial generation",
        "changed_section_paths": [],
        "review_state_at_version": "draft",
        "created_by": _LEAD_ID,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    v2 = {
        **v1,
        "id": str(uuid.uuid4()),
        "version_number": 2,
        "payload_snapshot": {
            "recommendation": "PROCEED",
            "summary": "Updated: synergy basis re-anchored to the FY25 pipeline.",
            "synergy_estimate": {
                "revenue_synergies": [
                    {"type": "Reframed cross-sell", "magnitude_gbp_m": 7.5,
                     "basis_citations": ["claim_b"]},
                ],
            },
            "key_reasons": [
                {"text": "Gross margin resilient", "claim_id": "claim_a"},
                {"text": "New pipeline signal", "claim_id": "claim_b"},
            ],
            "recommendation_claim_ids": ["claim_a", "claim_b"],
        },
        "change_type": "section_deepening",
        "change_summary": "Deepened synergy_estimate",
        "changed_section_paths": ["summary", "synergy_estimate",
                                   "key_reasons", "recommendation_claim_ids"],
        "review_state_at_version": "draft",
        "created_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
    }
    store["versions"][(_SESSION_ID, 1)] = v1
    store["versions"][(_SESSION_ID, 2)] = v2


# ---------------------------------------------------------------------------
# 1. diff_versions returns per-section change classification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diff_versions_section_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    _seed_two_versions(store)

    diff = await diff_versions(uuid.UUID(_SESSION_ID), 1, 2)
    assert diff is not None
    paths = {c.section_path: c.change for c in diff.section_changes}
    assert paths.get("summary") == "modified"
    assert paths.get("synergy_estimate") == "modified"
    assert paths.get("key_reasons") == "modified"
    assert paths.get("recommendation_claim_ids") == "modified"


# ---------------------------------------------------------------------------
# 2. Word-level diff produced for modified sections
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diff_versions_content_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    _seed_two_versions(store)

    diff = await diff_versions(uuid.UUID(_SESSION_ID), 1, 2)
    assert diff is not None
    summary = next(c for c in diff.section_changes if c.section_path == "summary")
    # Should have at least one 'removed' and one 'added' segment.
    statuses = {s.status for s in summary.word_segments}
    assert "removed" in statuses
    assert "added" in statuses
    # Claim deltas: claim_b added across the two versions.
    assert "claim_b" in diff.claim_changes["added"]
    assert diff.claim_changes["removed"] == []


# ---------------------------------------------------------------------------
# 3. Restore appends a new version; history preserved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restore_creates_new_version_not_overwrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    _stub_auto_revert(monkeypatch, store)
    _seed_two_versions(store)

    before_count = len(store["versions"])
    res = await restore_version(
        uuid.UUID(_SESSION_ID), 1, uuid.UUID(_LEAD_ID),
    )
    assert res.ok, res.reason
    assert res.new_version is not None
    assert res.new_version.version_number == 3
    assert res.new_version.change_type == "restore"
    # Versions 1 and 2 still present (history intact).
    assert (_SESSION_ID, 1) in store["versions"]
    assert (_SESSION_ID, 2) in store["versions"]
    assert len(store["versions"]) == before_count + 1
    # New version's snapshot equals v1's snapshot.
    assert res.new_version.payload_snapshot["summary"] == \
        store["versions"][(_SESSION_ID, 1)]["payload_snapshot"]["summary"]


# ---------------------------------------------------------------------------
# 4. Restore on approved engagement requires confirm_revert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restore_on_approved_requires_confirm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store(review_state="approved")
    _patch_db(monkeypatch, store)
    _stub_auto_revert(monkeypatch, store)
    _seed_two_versions(store)

    res = await restore_version(
        uuid.UUID(_SESSION_ID), 1, uuid.UUID(_LEAD_ID),
        confirm_revert=False,
    )
    assert not res.ok
    assert res.status_code == 409
    assert "confirm_revert" in res.reason.lower()
    assert res.extra.get("requires_confirm_revert") is True


# ---------------------------------------------------------------------------
# 5. Restore on approved + confirm → auto-revert fires
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restore_on_approved_with_confirm_reverts_to_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store(review_state="approved")
    _patch_db(monkeypatch, store)
    _stub_auto_revert(monkeypatch, store)
    _seed_two_versions(store)

    res = await restore_version(
        uuid.UUID(_SESSION_ID), 1, uuid.UUID(_LEAD_ID),
        confirm_revert=True,
    )
    assert res.ok, res.reason
    assert res.reverted_from_approved is True
    # The W15 stub recorded the call + flipped review_state to draft.
    assert len(store["review_revert_calls"]) == 1
    assert store["sessions"][_SESSION_ID]["review_state"] == "draft"


# ---------------------------------------------------------------------------
# 6. Restore flags ready artifacts stale
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restore_flags_artifacts_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    _stub_auto_revert(monkeypatch, store)
    _seed_two_versions(store)

    # Seed two ready artifacts + one draft.
    for aid, status in [("a-1", "ready"), ("a-2", "ready"), ("a-3", "draft")]:
        store["artifacts"][aid] = {
            "session_id": _SESSION_ID, "status": status, "metadata": {},
        }

    res = await restore_version(uuid.UUID(_SESSION_ID), 1, uuid.UUID(_LEAD_ID))
    assert res.ok
    assert res.artifacts_marked_stale == 2
    assert store["artifacts"]["a-1"]["metadata"]["stale_since_revert"] is True
    assert store["artifacts"]["a-2"]["metadata"]["stale_since_revert"] is True
    # The 'draft' artifact wasn't flipped.
    assert "stale_since_revert" not in store["artifacts"]["a-3"]["metadata"]


# ---------------------------------------------------------------------------
# 7. Restore dispatches a VERSION_RESTORED notification to the lead
#    (actor-exclusion means the lead-as-actor wouldn't get notified;
#    we use the admin as actor so the lead gets the row.)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restore_notifies_lead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    _stub_auto_revert(monkeypatch, store)
    _seed_two_versions(store)

    res = await restore_version(
        uuid.UUID(_SESSION_ID), 1, uuid.UUID(_ADMIN_ID),
    )
    assert res.ok
    notifs = [n for n in store["notifications"]
              if n["notification_type"] == "version_restored"]
    assert len(notifs) == 1
    assert notifs[0]["recipient_id"] == _LEAD_ID
    assert "restored" in notifs[0]["summary"].lower()


# ---------------------------------------------------------------------------
# 8. Contributors cannot restore (lead/author/admin only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contributor_cannot_restore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    _stub_auto_revert(monkeypatch, store)
    _seed_two_versions(store)

    res = await restore_version(
        uuid.UUID(_SESSION_ID), 1, uuid.UUID(_CONTRIB_ID),
    )
    assert not res.ok
    assert res.status_code == 403
    assert "lead" in res.reason.lower()


# ---------------------------------------------------------------------------
# 9. Restore writes an audit row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restore_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    _stub_auto_revert(monkeypatch, store)
    _seed_two_versions(store)

    res = await restore_version(
        uuid.UUID(_SESSION_ID), 1, uuid.UUID(_LEAD_ID),
    )
    assert res.ok
    audit_actions = [a["action"] for a in store["audit"]]
    assert "version.restored" in audit_actions
    audit_row = next(a for a in store["audit"]
                      if a["action"] == "version.restored")
    assert audit_row["payload"]["restored_version_number"] == 1
    assert audit_row["payload"]["new_version_number"] == 3
