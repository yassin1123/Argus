"""Review transition service — Phase 4 / Week 15 / Day 2.

Wires the W15/D1 state machine + authorization + locking modules
into the persistence layer:

  - Loads ``sessions`` + ``firms`` + actor's firm-membership in one
    pass.
  - Validates the transition (state_machine.can_transition).
  - Authorises the actor (authorization.authorize_action).
  - Persists the new state + denormalised columns on
    ``sessions``.
  - Appends a row to ``review_records``.
  - Appends a row to ``audit_events`` (the W3-era audit table).
  - Returns a :class:`ReviewTransitionResult` the API layer turns
    into a 200 / 403 / 404 / 409 response.

Pure persistence + orchestration. The W15/D3 work pulls the
review-history reads into separate helpers; today's module focuses
on the write path.

Hard-rule reminders (per W15/D2 spec):
  - Every transition writes BOTH a review_records row and an
    audit_events row — no path skips audit.
  - Auto-revert on edit is a SOFT path — the caller can fire
    AUTO_REVERT to swap the engagement back to draft without
    blocking the edit itself. Locking decisions live in the
    callers (orchestrator / API handlers) using
    :func:`locking.is_locked`.
  - Approve/request_changes from the author are gated by
    ``firms.allow_self_approval``; the authorization layer fires
    the rule at the service boundary too (not only at the API).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from db.connection import acquire

from .authorization import AuthorizationResult, authorize_action
from .feedback import (
    FeedbackValidationError,
    ReviewFeedback,
    is_resubmit_blocked,
    mark_pointer_resolved,
    validate_against_payload,
)
from .locking import is_locked
from .state_machine import (
    ReviewAction,
    ReviewState,
    apply_transition,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------


@dataclass
class ReviewTransitionResult:
    """Return shape from :func:`transition_review`. ``ok`` is True
    only when the transition both fired and persisted; on any
    failure ``ok`` is False and ``status_code`` + ``reason`` map
    cleanly to an HTTP response."""

    ok: bool
    session_id: str
    from_state: str
    to_state: str | None
    action: str
    actor_id: str
    reviewer_id: str | None = None
    feedback: str | None = None
    review_record_id: str | None = None
    artifacts_marked_stale: int = 0
    status_code: int = 200
    reason: str = ""
    # W15/D3: when a resubmit is gated by unresolved blocking pointers
    # from the latest request_changes round, the API surfaces the
    # offending paths so the consultant knows what to address.
    blocking_pointer_paths: list[str] | None = None


# Reasons for the standard error paths. Strings kept short + 403-safe
# so the API can pass them straight into HTTPException(detail=...).
_NOT_FOUND = "session not found in this firm"
_BAD_ACTION = "transition is not legal from the current state"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _load_session(session_id: UUID, firm_id: UUID) -> dict[str, Any] | None:
    """Fetch session + denormalised review columns + firm-scope
    sanity check in one query."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, firm_id, title, review_state, review_assigned_to,
                   approved_by, approved_at, submitted_at, submitted_by,
                   created_by_user_id
              FROM sessions
             WHERE id = $1::uuid AND firm_id = $2::uuid
            """,
            session_id, firm_id,
        )
    return dict(row) if row else None


async def _load_firm(firm_id: UUID) -> dict[str, Any] | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, slug, allow_self_approval FROM firms WHERE id = $1::uuid",
            firm_id,
        )
    return dict(row) if row else None


async def _load_actor_membership(firm_id: UUID, actor_id: UUID) -> dict[str, Any] | None:
    """Pulls the actor's user-id + firm-membership role so the
    authorization layer can apply the admin/member gate."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT u.id, u.email, fm.role AS firm_role
              FROM users u
              JOIN firm_memberships fm ON fm.user_id = u.id
             WHERE u.id = $1::uuid AND fm.firm_id = $2::uuid
            """,
            actor_id, firm_id,
        )
    return dict(row) if row else None


async def _load_payload_for_validation(session_id: UUID) -> dict[str, Any]:
    """Pull the latest writer ``consulting_payload`` for the session
    so :func:`feedback.validate_against_payload` can resolve every
    pointer's ``section_path``. Returns an empty dict when no
    report row exists yet — the validator then rejects any non-root
    pointer cleanly.
    """
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
    out: dict[str, Any] = {k: row[k] for k in row.keys() if k != "consulting_payload"}
    cp = row["consulting_payload"]
    if isinstance(cp, str):
        try:
            cp = json.loads(cp)
        except Exception:
            cp = {}
    if isinstance(cp, dict):
        out.update(cp)
    return out


async def _firm_id_for_session(session_id: UUID) -> UUID | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT firm_id FROM sessions WHERE id = $1::uuid", session_id,
        )
    return row["firm_id"] if row else None


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _serialise_feedback(feedback: Any) -> str | None:
    """Coerce the caller's feedback argument into a JSON string ready
    for the ``review_records.feedback::jsonb`` column.

    Three accepted shapes:
      - ``None`` → SQL NULL.
      - :class:`ReviewFeedback` instance → ``.model_dump()`` JSON.
      - plain string → wrap as ``{"overall_note": <s>, "section_pointers":
        [], "severity": "major"}`` so the read-path always sees the
        structured shape (matches the W15/D3 migration backfill).
      - dict → JSON-dump as-is (caller responsibility to match shape).
    """
    if feedback is None:
        return None
    if isinstance(feedback, ReviewFeedback):
        return feedback.model_dump_json()
    if isinstance(feedback, dict):
        return json.dumps(feedback)
    if isinstance(feedback, str):
        return json.dumps({
            "overall_note": feedback,
            "section_pointers": [],
            "severity": "major",
        })
    raise TypeError(
        f"unsupported feedback type for review_records.feedback: "
        f"{type(feedback).__name__}"
    )


async def _request_changes_feedback_history(
    session_id: UUID,
) -> list[dict[str, Any]]:
    """Pull the feedback payloads from every ``request_changes`` row
    on a session, oldest → newest. Used by the resubmit gate
    + the GET-review enrichment."""
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT feedback
              FROM review_records
             WHERE session_id = $1::uuid
               AND action = 'request_changes'
             ORDER BY created_at ASC
            """,
            session_id,
        )
    out: list[dict[str, Any]] = []
    for r in rows:
        fb = r["feedback"]
        if isinstance(fb, str):
            try:
                fb = json.loads(fb)
            except Exception:
                fb = {"overall_note": fb, "section_pointers": [], "severity": "major"}
        out.append(fb or {})
    return out


async def _persist_transition(
    *,
    session_id: UUID,
    firm_id: UUID,
    actor_id: UUID,
    action: ReviewAction,
    from_state: ReviewState,
    to_state: ReviewState,
    reviewer_id: UUID | None,
    feedback: Any | None,
) -> dict[str, Any]:
    """Single-transaction write covering:

      - ``sessions.review_state`` update + denormalised columns.
      - ``review_records`` insert.
      - ``audit_events`` insert.

    Returns the inserted review_record row dict (id, created_at, …).
    """
    payload = {
        "from_state": from_state.value,
        "to_state": to_state.value,
        "action": action.value,
        "reviewer_id": str(reviewer_id) if reviewer_id else None,
        "feedback_present": bool(feedback),
    }
    async with acquire() as conn:
        async with conn.transaction():
            # 1. Update sessions.
            sets: list[str] = ["review_state = $2"]
            params: list[Any] = [session_id, to_state.value]
            param_n = 2
            if action == ReviewAction.SUBMIT_FOR_REVIEW or action == ReviewAction.RESUBMIT:
                param_n += 1
                sets.append(f"submitted_at = NOW(), submitted_by = ${param_n}::uuid")
                params.append(actor_id)
                if reviewer_id:
                    param_n += 1
                    sets.append(f"review_assigned_to = ${param_n}::uuid")
                    params.append(reviewer_id)
            elif action == ReviewAction.APPROVE:
                param_n += 1
                sets.append(f"approved_at = NOW(), approved_by = ${param_n}::uuid")
                params.append(actor_id)
            elif action in (ReviewAction.REOPEN, ReviewAction.AUTO_REVERT):
                # Clear the approved-by trail so the next approval
                # surfaces correctly on the workspace UI.
                sets.append("approved_at = NULL, approved_by = NULL")
            await conn.execute(
                f"UPDATE sessions SET {', '.join(sets)}, updated_at = NOW() WHERE id = $1::uuid",
                *params,
            )

            # 2. Insert review_records. ``feedback`` is now JSONB
            # post-migration 037 — accept dict/structured payloads as
            # well as raw strings (the legacy plain-text path).
            feedback_json = _serialise_feedback(feedback)
            rr = await conn.fetchrow(
                """
                INSERT INTO review_records (
                    session_id, firm_id, from_state, to_state, action,
                    actor_id, reviewer_id, feedback
                ) VALUES (
                    $1::uuid, $2::uuid, $3, $4, $5,
                    $6::uuid, $7::uuid, $8::jsonb
                )
                RETURNING id, created_at
                """,
                session_id, firm_id,
                from_state.value, to_state.value, action.value,
                actor_id, reviewer_id, feedback_json,
            )

            # 3. Append audit_events. Every transition logs — no
            # exceptions to this rule per W15/D2 hard rule.
            await conn.execute(
                """
                INSERT INTO audit_events (
                    actor_user_id, action, resource_type, resource_id, payload
                ) VALUES ($1::uuid, $2, 'session', $3, $4::jsonb)
                """,
                actor_id,
                f"review.{action.value}",
                str(session_id),
                json.dumps({**payload, "review_record_id": str(rr["id"])}),
            )
    return dict(rr)


async def _mark_artifacts_stale(session_id: UUID, reason: str) -> int:
    """Tag every ``ready`` artifact on the session with
    ``metadata.stale_since_revert = true`` so downstream consumers
    (email attachment-bundle, regression checks) treat them as
    stale. Returns the row count updated.

    Per spec hard rule: no auto-delete + no auto-regenerate. Flag,
    don't touch.
    """
    async with acquire() as conn:
        n = await conn.fetchval(
            """
            UPDATE export_artifacts
               SET metadata = jsonb_set(
                       COALESCE(metadata, '{}'::jsonb),
                       '{stale_since_revert}',
                       to_jsonb($2::text)
                   )
             WHERE session_id = $1::uuid
               AND status = 'ready'
             RETURNING id
            """,
            session_id, reason,
        )
    if isinstance(n, int):
        return n
    # asyncpg's UPDATE…RETURNING via fetchval gives the first row's
    # column; for a count we use fetch instead. Re-query cleanly:
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id FROM export_artifacts
             WHERE session_id = $1::uuid
               AND status = 'ready'
               AND metadata ? 'stale_since_revert'
            """,
            session_id,
        )
    return len(rows)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def transition_review(
    session_id: UUID,
    action: ReviewAction | str,
    actor_id: UUID,
    *,
    reviewer_id: UUID | None = None,
    feedback: Any | None = None,
    structured_feedback: ReviewFeedback | None = None,
) -> ReviewTransitionResult:
    """End-to-end transition handler.

    Sequence (per W15/D2 spec):
      1. Load session + firm + actor.
      2. Validate transition via state_machine.
      3. Authorise via authorization.authorize_action.
      4. Persist state change (sessions) + audit (review_records +
         audit_events) in one transaction.
      5. If the action is AUTO_REVERT, flag any ready artifacts as
         ``stale_since_revert`` (no delete, no regenerate).

    Returns ``ReviewTransitionResult`` with ``status_code`` mapped
    to the appropriate HTTP code so the API layer is a thin
    forwarder.
    """
    if isinstance(action, str):
        try:
            action_enum = ReviewAction(action)
        except ValueError:
            return ReviewTransitionResult(
                ok=False, session_id=str(session_id), from_state="",
                to_state=None, action=action, actor_id=str(actor_id),
                status_code=400, reason=f"unknown action: {action!r}",
            )
    else:
        action_enum = action

    firm_id = await _firm_id_for_session(session_id)
    if firm_id is None:
        return ReviewTransitionResult(
            ok=False, session_id=str(session_id), from_state="",
            to_state=None, action=action_enum.value, actor_id=str(actor_id),
            status_code=404, reason=_NOT_FOUND,
        )

    session = await _load_session(session_id, firm_id)
    if session is None:
        return ReviewTransitionResult(
            ok=False, session_id=str(session_id), from_state="",
            to_state=None, action=action_enum.value, actor_id=str(actor_id),
            status_code=404, reason=_NOT_FOUND,
        )

    firm = await _load_firm(firm_id)
    if firm is None:
        return ReviewTransitionResult(
            ok=False, session_id=str(session_id), from_state="",
            to_state=None, action=action_enum.value, actor_id=str(actor_id),
            status_code=404, reason="firm not found",
        )

    actor_row = await _load_actor_membership(firm_id, actor_id)
    if actor_row is None:
        # The actor isn't a member of this firm — same 404 shape as
        # cross-firm access (don't leak that the session exists).
        return ReviewTransitionResult(
            ok=False, session_id=str(session_id), from_state="",
            to_state=None, action=action_enum.value, actor_id=str(actor_id),
            status_code=404, reason=_NOT_FOUND,
        )

    # 2. Structural validity.
    from_state = ReviewState(session["review_state"])
    transition = apply_transition(from_state, action_enum)
    if not transition.ok:
        return ReviewTransitionResult(
            ok=False, session_id=str(session_id),
            from_state=from_state.value, to_state=None,
            action=action_enum.value, actor_id=str(actor_id),
            status_code=409, reason=transition.reason or _BAD_ACTION,
        )
    to_state = transition.to_state
    assert to_state is not None  # apply_transition contract

    # 2b. W15/D3 — when the action is request_changes with a
    # structured payload, validate every pointer's section_path
    # against the live consulting_payload before persisting. A
    # pointer at a non-existent path is rejected at the boundary
    # so the consultant doesn't navigate to a dead address.
    if (
        action_enum == ReviewAction.REQUEST_CHANGES
        and structured_feedback is not None
        and structured_feedback.section_pointers
    ):
        payload_for_validation = await _load_payload_for_validation(session_id)
        try:
            validate_against_payload(structured_feedback, payload_for_validation)
        except FeedbackValidationError as e:
            return ReviewTransitionResult(
                ok=False, session_id=str(session_id),
                from_state=from_state.value, to_state=None,
                action=action_enum.value, actor_id=str(actor_id),
                status_code=400, reason=str(e),
            )

    # 2c. W15/D3 — resubmit gate. Resubmission isn't allowed while
    # major/blocking pointers from the latest request_changes round
    # are unresolved. Minor pointers are advisory; they don't gate.
    if action_enum == ReviewAction.RESUBMIT:
        history = await _request_changes_feedback_history(session_id)
        blocked, paths = is_resubmit_blocked(history)
        if blocked:
            return ReviewTransitionResult(
                ok=False, session_id=str(session_id),
                from_state=from_state.value, to_state=None,
                action=action_enum.value, actor_id=str(actor_id),
                status_code=409,
                reason=(
                    "resubmit is blocked while major/blocking section pointers "
                    "from the latest request_changes round are unresolved: "
                    + ", ".join(paths)
                ),
                blocking_pointer_paths=paths,
            )

    # 3. Authorisation. AUTO_REVERT is a special case — system-only.
    # The locking-layer caller has already established the
    # legitimate edit-detection trigger; we trust the call site and
    # skip the user-facing authorize check here.
    if action_enum != ReviewAction.AUTO_REVERT:
        auth: AuthorizationResult = authorize_action(
            action_enum,
            actor={"id": str(actor_id), "firm_role": actor_row.get("firm_role")},
            session=session,
            firm=firm,
        )
        if not auth.allowed:
            return ReviewTransitionResult(
                ok=False, session_id=str(session_id),
                from_state=from_state.value, to_state=None,
                action=action_enum.value, actor_id=str(actor_id),
                status_code=403, reason=auth.reason,
            )

    # 4. Persist — single transaction. structured_feedback wins over
    # the plain-text feedback arg so callers that pass both get the
    # structured shape; legacy callers keep working.
    feedback_to_persist: Any = structured_feedback if structured_feedback is not None else feedback
    rr = await _persist_transition(
        session_id=session_id,
        firm_id=firm_id,
        actor_id=actor_id,
        action=action_enum,
        from_state=from_state,
        to_state=to_state,
        reviewer_id=reviewer_id,
        feedback=feedback_to_persist,
    )

    # 5. Auto-revert side effect: flag the artifacts stale.
    n_stale = 0
    if action_enum == ReviewAction.AUTO_REVERT:
        n_stale = await _mark_artifacts_stale(
            session_id,
            feedback or "edit attempted on approved engagement; reverted to draft",
        )

    return ReviewTransitionResult(
        ok=True,
        session_id=str(session_id),
        from_state=from_state.value,
        to_state=to_state.value,
        action=action_enum.value,
        actor_id=str(actor_id),
        reviewer_id=str(reviewer_id) if reviewer_id else None,
        feedback=feedback,
        review_record_id=str(rr["id"]),
        artifacts_marked_stale=n_stale,
        status_code=200,
        reason="",
    )


# ---------------------------------------------------------------------------
# Read helpers — used by GET /api/sessions/{id}/review
# ---------------------------------------------------------------------------


async def get_review_state(session_id: UUID) -> dict[str, Any] | None:
    """Return current review state + denormalised columns + full
    review_records history for a session.

    Returns None if the session doesn't exist (caller maps to 404).
    """
    async with acquire() as conn:
        sess = await conn.fetchrow(
            """
            SELECT id, firm_id, title, review_state, review_assigned_to,
                   approved_by, approved_at, submitted_at, submitted_by,
                   created_by_user_id, updated_at
              FROM sessions
             WHERE id = $1::uuid
            """,
            session_id,
        )
        if not sess:
            return None
        history = await conn.fetch(
            """
            SELECT id, from_state, to_state, action, actor_id, reviewer_id,
                   feedback, created_at
              FROM review_records
             WHERE session_id = $1::uuid
             ORDER BY created_at ASC
            """,
            session_id,
        )
    decoded_history: list[dict[str, Any]] = []
    for h in history:
        fb = h["feedback"]
        if isinstance(fb, str):
            try:
                fb = json.loads(fb)
            except Exception:
                pass
        decoded_history.append({
            "id": str(h["id"]),
            "from_state": h["from_state"],
            "to_state": h["to_state"],
            "action": h["action"],
            "actor_id": str(h["actor_id"]),
            "reviewer_id": str(h["reviewer_id"]) if h["reviewer_id"] else None,
            "feedback": fb,
            "created_at": h["created_at"].isoformat(),
        })
    return {
        "session_id": str(sess["id"]),
        "review_state": sess["review_state"],
        "review_assigned_to": str(sess["review_assigned_to"]) if sess["review_assigned_to"] else None,
        "approved_by": str(sess["approved_by"]) if sess["approved_by"] else None,
        "approved_at": sess["approved_at"].isoformat() if sess["approved_at"] else None,
        "submitted_at": sess["submitted_at"].isoformat() if sess["submitted_at"] else None,
        "submitted_by": str(sess["submitted_by"]) if sess["submitted_by"] else None,
        "history": decoded_history,
    }


# ---------------------------------------------------------------------------
# Resolve-pointer flow (W15/D3)
# ---------------------------------------------------------------------------


@dataclass
class ResolvePointerResult:
    """Return shape from :func:`resolve_section_pointer`."""

    ok: bool
    review_record_id: str
    section_path: str
    changed: bool = False
    status_code: int = 200
    reason: str = ""


async def resolve_section_pointer(
    session_id: UUID,
    review_record_id: UUID,
    actor_id: UUID,
    section_path: str,
) -> ResolvePointerResult:
    """Mark a single section pointer as resolved on a specific
    request_changes review_record. Idempotent (a second resolve is a
    no-op with ``changed=False``).

    Auth: any firm member who can read the session can resolve a
    pointer — the consultant addressing feedback is typically the
    author, but a teammate sharing the engagement should be able to
    flag pointers resolved on their behalf. Authorization is
    enforced upstream at the API layer via ``can_read``.
    """
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, session_id, action, feedback
              FROM review_records
             WHERE id = $1::uuid
            """,
            review_record_id,
        )
        if not row or str(row["session_id"]) != str(session_id):
            return ResolvePointerResult(
                ok=False, review_record_id=str(review_record_id),
                section_path=section_path,
                status_code=404, reason="review_record not found on this session",
            )
        if row["action"] != "request_changes":
            return ResolvePointerResult(
                ok=False, review_record_id=str(review_record_id),
                section_path=section_path,
                status_code=409,
                reason="pointers can only be resolved on a request_changes record",
            )

        fb = row["feedback"]
        if isinstance(fb, str):
            try:
                fb = json.loads(fb)
            except Exception:
                fb = {}
        if not isinstance(fb, dict):
            fb = {}
        new_fb, changed = mark_pointer_resolved(
            fb, section_path, resolved_by=str(actor_id),
        )
        if changed:
            await conn.execute(
                """
                UPDATE review_records
                   SET feedback = $2::jsonb
                 WHERE id = $1::uuid
                """,
                review_record_id, json.dumps(new_fb),
            )
            # Audit the resolution so the workspace timeline shows it.
            await conn.execute(
                """
                INSERT INTO audit_events (
                    actor_user_id, action, resource_type, resource_id, payload
                ) VALUES ($1::uuid, 'review.resolve_pointer', 'session', $2, $3::jsonb)
                """,
                actor_id,
                str(session_id),
                json.dumps({
                    "review_record_id": str(review_record_id),
                    "section_path": section_path,
                }),
            )
    return ResolvePointerResult(
        ok=True,
        review_record_id=str(review_record_id),
        section_path=section_path,
        changed=changed,
    )


# ---------------------------------------------------------------------------
# Edit-lock helper for caller convenience
# ---------------------------------------------------------------------------


async def auto_revert_if_locked(
    session_id: UUID,
    actor_id: UUID,
    edit_label: str,
) -> ReviewTransitionResult | None:
    """If the session is currently in a locked review state
    (approved / delivered), fire an AUTO_REVERT transition and
    return its result. Otherwise return ``None`` — caller proceeds
    with the edit.

    Edit-detection callers (W9 deepening trigger / accept, future
    memo-edit endpoints) call this BEFORE applying the mutation.
    The result's ``artifacts_marked_stale`` count is surfaceable
    in the API response so the consultant sees what flipped.
    """
    firm_id = await _firm_id_for_session(session_id)
    if firm_id is None:
        return None
    session = await _load_session(session_id, firm_id)
    if session is None:
        return None
    if not is_locked(session):
        return None
    return await transition_review(
        session_id,
        ReviewAction.AUTO_REVERT,
        actor_id,
        feedback=edit_label,
    )


__all__ = [
    "ResolvePointerResult",
    "ReviewTransitionResult",
    "auto_revert_if_locked",
    "get_review_state",
    "resolve_section_pointer",
    "transition_review",
]
