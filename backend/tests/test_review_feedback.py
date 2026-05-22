"""Phase 4 / Week 15 / Day 3 — structured review feedback + resubmit gate
+ resolve-pointer tests.

Seven tests per spec, organised in two layers:

  - **Logic tests** for the new feedback module:
      - is_resubmit_blocked correctly enforces the major/blocking
        gate while letting minor pointers through.
      - validate_against_payload rejects pointers at non-existent
        section paths.
      - mark_pointer_resolved is idempotent + returns a changed
        flag the API can use.
      - The W15/D3 migration's backfill shape (plain-text →
        structured) round-trips through the read path.
  - **API tests** with FastAPI TestClient + mocked service layer:
      - request_changes accepts the structured shape and forwards
        the validated ReviewFeedback through.
      - The resolve-pointer endpoint flips a pointer and surfaces
        ``changed``.
      - resubmit is gated by unresolved blocking pointers; minor
        pointers don't gate.
      - GET /review now surfaces the structured feedback object on
        every request_changes row (and the older plain-text rows
        survive via the migration backfill).
"""

from __future__ import annotations

from unittest import mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import review as review_api
from auth.dependencies import get_current_user
from core.review.feedback import (
    FeedbackValidationError,
    ReviewFeedback,
    SectionPointer,
    is_resubmit_blocked,
    mark_pointer_resolved,
    validate_against_payload,
)
from core.review.service import ResolvePointerResult, ReviewTransitionResult


def _build_app(user_id: str | None = None) -> tuple[FastAPI, TestClient]:
    uid = user_id or str(uuid4())
    app = FastAPI()
    app.include_router(review_api.router, prefix="/api/sessions")

    async def fake_user() -> dict:
        return {"user_id": uid, "email": "actor@meridian.invalid", "role": "member"}

    app.dependency_overrides[get_current_user] = fake_user
    return app, TestClient(app)


def _ok_request_changes_result(uid: str) -> ReviewTransitionResult:
    return ReviewTransitionResult(
        ok=True,
        session_id=str(uuid4()),
        from_state="in_review",
        to_state="changes_requested",
        action="request_changes",
        actor_id=uid,
        review_record_id=str(uuid4()),
        status_code=200,
    )


# ---------------------------------------------------------------------------
# Test 1 — request-changes accepts the structured shape end-to-end
# ---------------------------------------------------------------------------


def test_request_changes_with_structured_feedback() -> None:
    sid = str(uuid4())
    uid = str(uuid4())
    app, client = _build_app(uid)

    canned = _ok_request_changes_result(uid)

    with mock.patch.object(review_api, "can_read", new=mock.AsyncMock(return_value=True)), \
         mock.patch.object(
             review_api, "transition_review",
             new=mock.AsyncMock(return_value=canned),
         ) as m:
        r = client.post(
            f"/api/sessions/{sid}/review/request-changes",
            json={
                "overall_note": "Tighten the valuation + the synergy basis.",
                "severity": "major",
                "section_pointers": [
                    {"section_path": "valuation_range",
                     "note": "Base case feels light vs the peer set.",
                     "severity": "major"},
                    {"section_path": "synergy_estimate",
                     "note": "Magnitude needs sourcing.",
                     "severity": "blocking"},
                ],
            },
        )
    assert r.status_code == 200, r.text
    assert r.json()["to_state"] == "changes_requested"

    # Service was called with a structured_feedback kwarg carrying the
    # exact pointers we sent (Pydantic-typed).
    call = m.await_args
    structured = call.kwargs.get("structured_feedback")
    assert isinstance(structured, ReviewFeedback)
    assert structured.severity == "major"
    paths = [p.section_path for p in structured.section_pointers]
    assert paths == ["valuation_range", "synergy_estimate"]
    severities = [p.severity for p in structured.section_pointers]
    assert severities == ["major", "blocking"]


# ---------------------------------------------------------------------------
# Test 2 — pointer to a non-existent path is rejected by the validator
# ---------------------------------------------------------------------------


def test_section_pointers_reference_valid_paths() -> None:
    """The feedback validator rejects pointers at paths that don't
    resolve. The W9 ``get_section`` semantics flow through here."""
    payload = {
        "recommendation": "PROCEED",
        "synergy_estimate": {"revenue_synergies": []},
        "frameworks": {"porters_five_forces": {"market_definition": "x"}},
    }
    good = ReviewFeedback(
        overall_note="ok",
        section_pointers=[
            SectionPointer(section_path="synergy_estimate", note="x"),
            SectionPointer(section_path="frameworks.porters_five_forces",
                           note="y"),
        ],
    )
    # No exception.
    validate_against_payload(good, payload)

    bad = ReviewFeedback(
        overall_note="bad",
        section_pointers=[
            SectionPointer(section_path="not_a_real_section", note="x"),
            SectionPointer(section_path="frameworks.nonexistent_thing",
                           note="y"),
        ],
    )
    with pytest.raises(FeedbackValidationError) as exc:
        validate_against_payload(bad, payload)
    assert "not_a_real_section" in str(exc.value)
    assert "nonexistent_thing" in str(exc.value)


# ---------------------------------------------------------------------------
# Test 3 — resolve-pointer flips a pointer + is idempotent
# ---------------------------------------------------------------------------


def test_resolve_pointer_marks_resolved() -> None:
    """Logic-level: ``mark_pointer_resolved`` flips the right
    pointer, leaves the others alone, and reports ``changed`` so a
    second resolve is a no-op."""
    fb = {
        "overall_note": "X",
        "severity": "major",
        "section_pointers": [
            {"section_path": "valuation_range", "note": "A",
             "severity": "major", "resolved": False},
            {"section_path": "synergy_estimate", "note": "B",
             "severity": "blocking", "resolved": False},
        ],
    }
    new_fb, changed = mark_pointer_resolved(
        fb, "valuation_range", resolved_by="u1",
    )
    assert changed is True
    pointers = new_fb["section_pointers"]
    assert pointers[0]["resolved"] is True
    assert pointers[0]["resolved_by"] == "u1"
    assert pointers[1]["resolved"] is False, "untouched pointer must stay"

    # Idempotent: resolving again returns changed=False.
    _, again = mark_pointer_resolved(new_fb, "valuation_range", resolved_by="u1")
    assert again is False

    # Now the API surface — the endpoint forwards to
    # resolve_section_pointer and surfaces ``changed``.
    sid = str(uuid4())
    rid = str(uuid4())
    uid = str(uuid4())
    app, client = _build_app(uid)
    canned = ResolvePointerResult(
        ok=True, review_record_id=rid, section_path="valuation_range",
        changed=True,
    )
    with mock.patch.object(review_api, "can_read", new=mock.AsyncMock(return_value=True)), \
         mock.patch.object(
             review_api, "resolve_section_pointer",
             new=mock.AsyncMock(return_value=canned),
         ):
        r = client.post(
            f"/api/sessions/{sid}/review/feedback/{rid}/resolve-pointer",
            json={"section_path": "valuation_range"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["changed"] is True
    assert body["section_path"] == "valuation_range"


# ---------------------------------------------------------------------------
# Test 4 — resubmit blocked while major/blocking pointers are unresolved
# ---------------------------------------------------------------------------


def test_resubmit_blocked_until_blocking_pointers_resolved() -> None:
    """``is_resubmit_blocked`` returns True when the latest
    request_changes round has any unresolved major/blocking pointer."""
    # Two rounds — the consultant addressed Round 1 then got Round 2.
    history = [
        {
            "overall_note": "first round",
            "severity": "major",
            "section_pointers": [
                {"section_path": "valuation_range",
                 "severity": "major", "resolved": True},
            ],
        },
        {
            "overall_note": "second round",
            "severity": "blocking",
            "section_pointers": [
                {"section_path": "synergy_estimate",
                 "severity": "blocking", "resolved": False},
                {"section_path": "risks",
                 "severity": "minor", "resolved": False},
            ],
        },
    ]
    blocked, paths = is_resubmit_blocked(history)
    assert blocked is True
    assert paths == ["synergy_estimate"], (
        "minor pointers should NOT contribute to the blocking list"
    )

    # API surface — resubmit endpoint surfaces the structured 409 body.
    sid = str(uuid4())
    uid = str(uuid4())
    app, client = _build_app(uid)
    canned = ReviewTransitionResult(
        ok=False, session_id=sid,
        from_state="changes_requested", to_state=None,
        action="resubmit", actor_id=uid,
        status_code=409,
        reason="resubmit is blocked while major/blocking section pointers ...",
        blocking_pointer_paths=["synergy_estimate"],
    )
    with mock.patch.object(review_api, "can_read", new=mock.AsyncMock(return_value=True)), \
         mock.patch.object(
             review_api, "get_review_state",
             new=mock.AsyncMock(return_value={"review_state": "changes_requested"}),
         ), \
         mock.patch.object(
             review_api, "transition_review",
             new=mock.AsyncMock(return_value=canned),
         ):
        r = client.post(f"/api/sessions/{sid}/review/submit", json={})
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["blocking_pointer_paths"] == ["synergy_estimate"]


# ---------------------------------------------------------------------------
# Test 5 — resubmit allowed with unresolved minor pointers
# ---------------------------------------------------------------------------


def test_resubmit_allowed_with_unresolved_minor_pointers() -> None:
    """Per W15/D3 hard rule: minor pointers are advisory. They don't
    gate resubmission even when unresolved."""
    history = [
        {
            "overall_note": "minor only",
            "severity": "minor",
            "section_pointers": [
                {"section_path": "risks", "severity": "minor", "resolved": False},
                {"section_path": "next_steps", "severity": "minor", "resolved": False},
            ],
        },
    ]
    blocked, paths = is_resubmit_blocked(history)
    assert blocked is False
    assert paths == []

    # And an empty history (no request_changes ever) returns not-blocked.
    blocked2, paths2 = is_resubmit_blocked([])
    assert blocked2 is False
    assert paths2 == []


# ---------------------------------------------------------------------------
# Test 6 — GET /review surfaces structured feedback on every record
# ---------------------------------------------------------------------------


def test_review_history_includes_feedback_and_resolution_status() -> None:
    sid = str(uuid4())
    uid = str(uuid4())
    app, client = _build_app(uid)

    canned_state = {
        "session_id": sid,
        "review_state": "changes_requested",
        "review_assigned_to": None,
        "approved_by": None,
        "approved_at": None,
        "submitted_at": "2026-05-22T09:00:00+00:00",
        "submitted_by": uid,
        "history": [
            {
                "id": str(uuid4()),
                "from_state": "draft", "to_state": "in_review",
                "action": "submit_for_review", "actor_id": uid,
                "reviewer_id": None, "feedback": None,
                "created_at": "2026-05-22T09:00:00+00:00",
            },
            {
                "id": str(uuid4()),
                "from_state": "in_review", "to_state": "changes_requested",
                "action": "request_changes", "actor_id": uid,
                "reviewer_id": None,
                "feedback": {
                    "overall_note": "Tighten valuation.",
                    "severity": "major",
                    "section_pointers": [
                        {"section_path": "valuation_range",
                         "note": "Base case light.",
                         "severity": "major",
                         "resolved": True,
                         "resolved_by": uid},
                        {"section_path": "synergy_estimate",
                         "note": "Magnitude needs sourcing.",
                         "severity": "blocking",
                         "resolved": False},
                    ],
                },
                "created_at": "2026-05-22T10:00:00+00:00",
            },
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
    assert len(body["history"]) == 2
    rc = body["history"][1]
    assert rc["action"] == "request_changes"
    fb = rc["feedback"]
    assert fb["overall_note"] == "Tighten valuation."
    assert fb["severity"] == "major"
    assert len(fb["section_pointers"]) == 2
    assert fb["section_pointers"][0]["resolved"] is True
    assert fb["section_pointers"][1]["resolved"] is False


# ---------------------------------------------------------------------------
# Test 7 — migration backfill shape (plain-text → structured)
# ---------------------------------------------------------------------------


def test_feedback_migration_backfills_plain_text() -> None:
    """Migration 037 wraps any legacy plain-text feedback into the
    structured shape: ``{overall_note: <s>, section_pointers: [],
    severity: 'major'}``. The read path should accept both wrapped
    legacy rows AND fresh structured rows without a special case.

    This test exercises the SHAPE the migration emits: a wrapped
    legacy row carries empty pointers + severity=major and the
    resubmit gate treats it as unblocking.
    """
    # 1. The shape itself.
    backfilled = {
        "overall_note": "Pls tighten the synergy section.",
        "section_pointers": [],
        "severity": "major",
    }
    # 2. ReviewFeedback parses the wrapped shape cleanly.
    fb_model = ReviewFeedback(**backfilled)
    assert fb_model.overall_note.startswith("Pls tighten")
    assert fb_model.section_pointers == []
    assert fb_model.severity == "major"

    # 3. validate_against_payload is a no-op (no pointers to check).
    validate_against_payload(fb_model, {"anything": 1})

    # 4. The resubmit gate doesn't block on a backfilled row — empty
    # pointers list means no blocking paths regardless of severity.
    blocked, paths = is_resubmit_blocked([backfilled])
    assert blocked is False
    assert paths == []

    # 5. mark_pointer_resolved on a backfilled row is a no-op
    # (no matching path), with changed=False.
    _, changed = mark_pointer_resolved(backfilled, "anywhere", resolved_by="u")
    assert changed is False
