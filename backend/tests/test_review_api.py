"""Phase 4 / Week 15 / Day 2 — review transition API + auto-revert tests.

Ten tests per spec. Two layers:

  - **API-surface tests** (FastAPI TestClient + dependency override
    + mocked ``transition_review``) — verify path routing, body
    parsing, response shape, error mapping from
    ``ReviewTransitionResult.status_code`` to HTTPException.
  - **Auto-revert tests** (mock ``auto_revert_if_locked`` at the
    section_deepening boundary) — verify the deepen + accept paths
    fire the revert helper and pass its result through to the
    response body.

The W15/D1 state-machine + authorisation logic already has its own
suite (``test_review_state_machine.py``); this module exercises the
W15/D2 service + API + edit-detection layer on top.
"""

from __future__ import annotations

from unittest import mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import review as review_api
from api import section_deepening as sd_module
from auth.dependencies import get_current_user
from core.review.service import ReviewTransitionResult


def _build_review_app(user_id: str | None = None) -> tuple[FastAPI, TestClient]:
    uid = user_id or str(uuid4())
    app = FastAPI()
    app.include_router(review_api.router, prefix="/api/sessions")

    async def fake_user() -> dict:
        return {"user_id": uid, "email": "actor@meridian.invalid", "role": "member"}

    app.dependency_overrides[get_current_user] = fake_user
    return app, TestClient(app)


def _build_deepen_app(user_id: str | None = None) -> tuple[FastAPI, TestClient]:
    """Variant for the auto-revert tests — wraps the section_deepening
    router so we can hit the deepen + accept paths and assert the
    revert helper fires."""
    uid = user_id or str(uuid4())
    app = FastAPI()
    app.include_router(sd_module.router, prefix="/api/sessions")

    async def fake_user() -> dict:
        return {"user_id": uid, "email": "actor@meridian.invalid", "role": "member"}

    app.dependency_overrides[get_current_user] = fake_user
    return app, TestClient(app)


def _ok_transition_result(
    *, from_state: str, to_state: str, action: str,
    actor_id: str, artifacts_stale: int = 0, review_record_id: str | None = None,
) -> ReviewTransitionResult:
    return ReviewTransitionResult(
        ok=True,
        session_id=str(uuid4()),
        from_state=from_state,
        to_state=to_state,
        action=action,
        actor_id=actor_id,
        review_record_id=review_record_id or str(uuid4()),
        artifacts_marked_stale=artifacts_stale,
        status_code=200,
        reason="",
    )


def _fail_transition_result(status_code: int, reason: str, from_state: str = "in_review") -> ReviewTransitionResult:
    return ReviewTransitionResult(
        ok=False,
        session_id=str(uuid4()),
        from_state=from_state,
        to_state=None,
        action="approve",
        actor_id=str(uuid4()),
        status_code=status_code,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Test 1 — submit_for_review transitions state
# ---------------------------------------------------------------------------


def test_submit_for_review_transitions_state() -> None:
    sid = str(uuid4())
    uid = str(uuid4())
    reviewer = str(uuid4())
    app, client = _build_review_app(uid)

    canned = _ok_transition_result(
        from_state="draft", to_state="in_review",
        action="submit_for_review", actor_id=uid,
    )

    with mock.patch.object(review_api, "can_read", new=mock.AsyncMock(return_value=True)), \
         mock.patch.object(
             review_api, "get_review_state",
             new=mock.AsyncMock(return_value={"review_state": "draft"}),
         ), \
         mock.patch.object(
             review_api, "transition_review",
             new=mock.AsyncMock(return_value=canned),
         ) as m:
        r = client.post(
            f"/api/sessions/{sid}/review/submit",
            json={"reviewer_id": reviewer},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["from_state"] == "draft"
    assert body["to_state"] == "in_review"
    assert body["action"] == "submit_for_review"
    # transition_review was called with the correct action + reviewer_id.
    call = m.await_args
    assert str(call.args[1].value) == "submit_for_review"
    assert str(call.kwargs.get("reviewer_id")) == reviewer


# ---------------------------------------------------------------------------
# Test 2 — author cannot approve own work (self-approval guard)
# ---------------------------------------------------------------------------


def test_approve_requires_reviewer_different_from_author() -> None:
    sid = str(uuid4())
    uid = str(uuid4())
    app, client = _build_review_app(uid)

    # Service returns 403 because the author tried to approve.
    denial = _fail_transition_result(
        status_code=403,
        reason="self-approval is disabled for this firm",
    )

    with mock.patch.object(review_api, "can_read", new=mock.AsyncMock(return_value=True)), \
         mock.patch.object(
             review_api, "transition_review",
             new=mock.AsyncMock(return_value=denial),
         ):
        r = client.post(f"/api/sessions/{sid}/review/approve", json={})
    assert r.status_code == 403, r.text
    body = r.json()
    assert "self-approval" in body["detail"].lower()


# ---------------------------------------------------------------------------
# Test 3 — request_changes carries feedback through
# ---------------------------------------------------------------------------


def test_request_changes_records_feedback() -> None:
    sid = str(uuid4())
    uid = str(uuid4())
    app, client = _build_review_app(uid)
    canned = _ok_transition_result(
        from_state="in_review", to_state="changes_requested",
        action="request_changes", actor_id=uid,
    )

    with mock.patch.object(review_api, "can_read", new=mock.AsyncMock(return_value=True)), \
         mock.patch.object(
             review_api, "transition_review",
             new=mock.AsyncMock(return_value=canned),
         ) as m:
        # Empty overall_note is rejected at the body-validation layer.
        r0 = client.post(
            f"/api/sessions/{sid}/review/request-changes",
            json={"overall_note": ""},
        )
        assert r0.status_code == 422, "empty overall_note should fail Pydantic validation"

        r = client.post(
            f"/api/sessions/{sid}/review/request-changes",
            json={"overall_note": "Tighten the valuation triple — base case feels light."},
        )
    assert r.status_code == 200, r.text
    assert r.json()["to_state"] == "changes_requested"
    # W15/D3: the structured ReviewFeedback is forwarded via the
    # ``structured_feedback`` kwarg; the legacy ``feedback`` kwarg
    # is now reserved for the older plain-text path.
    call = m.await_args
    structured = call.kwargs.get("structured_feedback")
    assert structured is not None
    assert "valuation" in structured.overall_note


# ---------------------------------------------------------------------------
# Test 4 — full cycle: submit → request changes → resubmit → approve
# ---------------------------------------------------------------------------


def test_full_cycle_submit_request_resubmit_approve() -> None:
    sid = str(uuid4())
    uid = str(uuid4())
    app, client = _build_review_app(uid)

    # Sequence of canned service responses + the GET-state response
    # for the submit endpoint's state-disambiguation.
    state_seq = iter([
        {"review_state": "draft"},
        {"review_state": "changes_requested"},
    ])
    transition_seq = iter([
        _ok_transition_result(from_state="draft", to_state="in_review",
                              action="submit_for_review", actor_id=uid),
        _ok_transition_result(from_state="in_review", to_state="changes_requested",
                              action="request_changes", actor_id=uid),
        _ok_transition_result(from_state="changes_requested", to_state="in_review",
                              action="resubmit", actor_id=uid),
        _ok_transition_result(from_state="in_review", to_state="approved",
                              action="approve", actor_id=uid),
    ])

    async def state_stub(_sid):
        return next(state_seq)

    async def trans_stub(*args, **kwargs):
        return next(transition_seq)

    with mock.patch.object(review_api, "can_read", new=mock.AsyncMock(return_value=True)), \
         mock.patch.object(review_api, "get_review_state", new=state_stub), \
         mock.patch.object(review_api, "transition_review", new=trans_stub):
        # 1. Submit.
        r1 = client.post(f"/api/sessions/{sid}/review/submit", json={})
        assert r1.status_code == 200, r1.text
        assert r1.json()["to_state"] == "in_review"
        # 2. Request changes.
        r2 = client.post(
            f"/api/sessions/{sid}/review/request-changes",
            json={"overall_note": "minor fixes"},
        )
        assert r2.json()["to_state"] == "changes_requested"
        # 3. Resubmit — the same /submit endpoint dispatches to RESUBMIT
        # when the state is changes_requested.
        r3 = client.post(f"/api/sessions/{sid}/review/submit", json={})
        assert r3.json()["to_state"] == "in_review"
        assert r3.json()["action"] == "resubmit"
        # 4. Approve.
        r4 = client.post(f"/api/sessions/{sid}/review/approve", json={})
        assert r4.json()["to_state"] == "approved"


# ---------------------------------------------------------------------------
# Test 5 — edit on approved auto-reverts to draft (deepen trigger)
# ---------------------------------------------------------------------------


def test_edit_on_approved_auto_reverts_to_draft() -> None:
    sid = str(uuid4())
    uid = str(uuid4())
    app, client = _build_deepen_app(uid)

    revert = _ok_transition_result(
        from_state="approved", to_state="draft",
        action="auto_revert", actor_id=uid, artifacts_stale=4,
        review_record_id=str(uuid4()),
    )

    with mock.patch.object(sd_module, "can_read", new=mock.AsyncMock(return_value=True)), \
         mock.patch.object(sd_module, "can_write", new=mock.AsyncMock(return_value=True)), \
         mock.patch.object(
             sd_module, "auto_revert_if_locked",
             new=mock.AsyncMock(return_value=revert),
         ) as m:
        r = client.post(
            f"/api/sessions/{sid}/deepen",
            json={"section_path": "summary", "depth_directive": "Tighten."},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "queued"
    assert body.get("review_auto_reverted") is True
    assert body.get("artifacts_marked_stale") == 4
    assert "approved" in body.get("review_revert_message", "").lower() or \
           "draft" in body.get("review_revert_message", "").lower()
    # The revert helper was called with the right edit label.
    args, kwargs = m.await_args
    assert "section deepening triggered" in kwargs.get("edit_label", "")


# ---------------------------------------------------------------------------
# Test 6 — accept_deepening on approved also auto-reverts
# ---------------------------------------------------------------------------


def test_deepen_on_approved_auto_reverts() -> None:
    sid = str(uuid4())
    did = str(uuid4())
    uid = str(uuid4())
    app, client = _build_deepen_app(uid)

    revert = _ok_transition_result(
        from_state="approved", to_state="draft",
        action="auto_revert", actor_id=uid, artifacts_stale=3,
    )

    with mock.patch.object(sd_module, "can_read", new=mock.AsyncMock(return_value=True)), \
         mock.patch.object(sd_module, "can_write", new=mock.AsyncMock(return_value=True)), \
         mock.patch.object(
             sd_module, "auto_revert_if_locked",
             new=mock.AsyncMock(return_value=revert),
         ), \
         mock.patch.object(
             sd_module, "accept_deepening",
             new=mock.AsyncMock(return_value={"status": "accepted", "deepening_id": did}),
         ):
        r = client.post(f"/api/sessions/{sid}/deepen/{did}/accept")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") == "accepted"
    assert body.get("review_auto_reverted") is True
    assert body.get("artifacts_marked_stale") == 3


# ---------------------------------------------------------------------------
# Test 7 — auto-revert marks artifacts stale (service-level)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_revert_marks_artifacts_stale() -> None:
    """The service's ``_mark_artifacts_stale`` helper must:

      - Only touch ``status='ready'`` rows.
      - Set ``metadata.stale_since_revert`` (not delete; not
        regenerate, per hard rule).
      - Return the row count it stamped so the API surfaces it.
    """
    from core.review import service as review_service

    fake_pool = mock.MagicMock()
    fake_conn = mock.MagicMock()
    fake_conn.fetchval = mock.AsyncMock(return_value=None)
    fake_conn.fetch = mock.AsyncMock(return_value=[{"id": str(uuid4())} for _ in range(2)])

    # async ctx manager: ``async with acquire() as conn``.
    class _AcquireCM:
        async def __aenter__(self): return fake_conn
        async def __aexit__(self, *a): return None

    with mock.patch.object(review_service, "acquire", lambda: _AcquireCM()):
        n = await review_service._mark_artifacts_stale(uuid4(), reason="test")
    assert n == 2

    # The UPDATE SQL stamps metadata.stale_since_revert with the reason.
    # We can check the call argument shape.
    update_call = fake_conn.fetchval.await_args
    assert "UPDATE export_artifacts" in update_call.args[0]
    assert "status = 'ready'" in update_call.args[0]
    assert "stale_since_revert" in update_call.args[0]
    # The hardrule "no auto-delete + no auto-regenerate" is enforced
    # structurally — the helper only fires an UPDATE on metadata.


# ---------------------------------------------------------------------------
# Test 8 — review history endpoint returns all transitions
# ---------------------------------------------------------------------------


def test_review_history_returns_all_transitions() -> None:
    sid = str(uuid4())
    uid = str(uuid4())
    app, client = _build_review_app(uid)
    canned_state = {
        "session_id": sid,
        "review_state": "approved",
        "review_assigned_to": None,
        "approved_by": uid,
        "approved_at": "2026-05-20T10:00:00+00:00",
        "submitted_at": "2026-05-20T09:30:00+00:00",
        "submitted_by": uid,
        "history": [
            {"id": str(uuid4()), "from_state": "draft", "to_state": "in_review",
             "action": "submit_for_review", "actor_id": uid, "reviewer_id": None,
             "feedback": None, "created_at": "2026-05-20T09:30:00+00:00"},
            {"id": str(uuid4()), "from_state": "in_review", "to_state": "approved",
             "action": "approve", "actor_id": uid, "reviewer_id": None,
             "feedback": None, "created_at": "2026-05-20T10:00:00+00:00"},
        ],
    }
    with mock.patch.object(review_api, "can_read", new=mock.AsyncMock(return_value=True)), \
         mock.patch.object(
             review_api, "get_review_state",
             new=mock.AsyncMock(return_value=canned_state),
         ):
        r = client.get(f"/api/sessions/{sid}/review")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["review_state"] == "approved"
    assert len(body["history"]) == 2
    assert body["history"][0]["action"] == "submit_for_review"
    assert body["history"][1]["action"] == "approve"


# ---------------------------------------------------------------------------
# Test 9 — cross-firm review action returns 404
# ---------------------------------------------------------------------------


def test_cross_firm_review_action_returns_404() -> None:
    """Cross-firm callers see the same 404 shape the rest of the
    W9/W10 endpoints use (don't leak that the session exists in
    another firm)."""
    sid = str(uuid4())
    uid = str(uuid4())
    app, client = _build_review_app(uid)

    with mock.patch.object(review_api, "can_read", new=mock.AsyncMock(return_value=False)):
        r1 = client.post(f"/api/sessions/{sid}/review/submit", json={})
        r2 = client.post(f"/api/sessions/{sid}/review/approve", json={})
        r3 = client.post(
            f"/api/sessions/{sid}/review/request-changes",
            json={"overall_note": "x"},
        )
        r4 = client.post(f"/api/sessions/{sid}/review/reopen", json={})
        r5 = client.get(f"/api/sessions/{sid}/review")

    for r in (r1, r2, r3, r4, r5):
        assert r.status_code == 404, (
            f"expected 404 on cross-firm review action; got {r.status_code}: {r.text}"
        )


# ---------------------------------------------------------------------------
# Test 10 — every transition writes an audit_events row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_transition_writes_audit_log() -> None:
    """Per W15/D2 hard rule: no transition skips audit. The
    persistence helper writes BOTH a review_records INSERT and an
    audit_events INSERT in one transaction; we verify the SQL is
    issued by intercepting at the connection layer."""
    from core.review import service as review_service
    from core.review.state_machine import ReviewAction, ReviewState

    fake_conn = mock.MagicMock()
    fake_conn.execute = mock.AsyncMock(return_value=None)
    fake_conn.fetchrow = mock.AsyncMock(
        return_value={"id": uuid4(), "created_at": None}
    )

    class _TxCM:
        async def __aenter__(self): return None
        async def __aexit__(self, *a): return None

    fake_conn.transaction = lambda: _TxCM()

    class _AcquireCM:
        async def __aenter__(self): return fake_conn
        async def __aexit__(self, *a): return None

    with mock.patch.object(review_service, "acquire", lambda: _AcquireCM()):
        await review_service._persist_transition(
            session_id=uuid4(),
            firm_id=uuid4(),
            actor_id=uuid4(),
            action=ReviewAction.APPROVE,
            from_state=ReviewState.IN_REVIEW,
            to_state=ReviewState.APPROVED,
            reviewer_id=None,
            feedback=None,
        )

    # Exactly three SQL statements should have fired:
    #   1. UPDATE sessions ...
    #   2. INSERT INTO review_records ... (via fetchrow)
    #   3. INSERT INTO audit_events ...
    update_calls = [c for c in fake_conn.execute.await_args_list if "UPDATE sessions" in c.args[0]]
    audit_calls = [c for c in fake_conn.execute.await_args_list if "audit_events" in c.args[0]]
    assert len(update_calls) == 1, f"expected one UPDATE sessions, got {len(update_calls)}"
    assert len(audit_calls) == 1, f"expected one INSERT audit_events, got {len(audit_calls)}"
    # review_records insert went through fetchrow (RETURNING id).
    rr_calls = [c for c in fake_conn.fetchrow.await_args_list if "review_records" in c.args[0]]
    assert len(rr_calls) == 1, f"expected one INSERT review_records, got {len(rr_calls)}"

    # Audit payload includes the action + the review_record_id link.
    audit_sql = audit_calls[0].args[0]
    assert "review.approve" in audit_calls[0].args[2]
    assert "review_record_id" in audit_calls[0].args[4]
