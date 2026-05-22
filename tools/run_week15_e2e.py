"""Phase 4 / Week 15 / Day 5 — review-workflow e2e demo runner.

Drives the full multi-user review cycle against the seeded Meridian
Advisory engagement (W14/D3). Goes through the W15/D2 transition
service directly — no HTTP layer, no LLM calls, near-zero cost.

The cycle (10 steps, per spec):

  1.  Consultant submits + assigns the partner as reviewer.
  2.  Consultant attempts to approve their own work → 403.
  3.  Junior analyst (member, not assigned) attempts approve → 403.
  4.  Partner requests changes with 1 major + 1 minor pointer.
  5.  Consultant tries to resubmit before resolving the major
      pointer → 409 (blocked).
  6.  Consultant resolves the major pointer + resubmits → in_review.
  7.  Partner approves → approved (with reviewer ≠ author confirmed).
  8.  Consultant edits the memo (via auto_revert_if_locked) →
      auto-revert to draft, artifacts flagged stale.
  9.  Consultant resubmits + partner approves again → approved.
  10. Consultant marks delivered → delivered.

Persists every step's status + the inserted review_record + the
matching audit_events row count so the wrap-up doc has hard numbers.

Headline assertions (8) gate the ship decision per W15/D5 hard
rules — every authorization gate must fire correctly; lock-on-edit
auto-revert must trigger; audit_log must cover every transition.

Usage::

    python tools/run_week15_e2e.py
    python tools/run_week15_e2e.py --summary-only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))
sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")

_BENCH_ROOT = _REPO_ROOT / "backend" / "eval_runs" / "week15_e2e"

FIRM_SLUG = "meridian-advisory"
ENGAGEMENT_TITLE_PREFIX = "Kestrel"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class StepResult:
    step: int
    label: str
    actor: str
    ok: bool
    status_code: int
    from_state: str | None
    to_state: str | None
    reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class CycleSummary:
    firm_slug: str
    session_id: str
    engagement_title: str
    steps: list[StepResult]
    review_records: list[dict[str, Any]]
    audit_rows: list[dict[str, Any]]
    headline: dict[str, Any]
    headline_pass: bool


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _bootstrap_engagement() -> dict[str, Any]:
    """Re-set the seeded Meridian Kestrel engagement to a clean
    ``review_state=draft`` baseline so the runner is idempotent.
    Returns the session_id + the three Meridian user_ids keyed by
    role."""
    from db.connection import acquire

    async with acquire() as conn:
        sess = await conn.fetchrow(
            """
            SELECT s.id, s.title, s.firm_id, s.review_state
              FROM sessions s
              JOIN firms f ON f.id = s.firm_id
             WHERE f.slug = $1::text
               AND s.title LIKE $2 || '%'
             ORDER BY s.title ASC
             LIMIT 1
            """,
            FIRM_SLUG, ENGAGEMENT_TITLE_PREFIX,
        )
        if not sess:
            raise SystemExit(
                f"No '{ENGAGEMENT_TITLE_PREFIX}' engagement found for firm "
                f"'{FIRM_SLUG}'. Run tools/seed_sample_workspace.py first."
            )

        # The three Meridian users.
        users = {r["email"]: r["id"] for r in await conn.fetch(
            """
            SELECT u.id, u.email, fm.role
              FROM users u
              JOIN firm_memberships fm ON fm.user_id = u.id
              JOIN firms f ON f.id = fm.firm_id
             WHERE f.slug = $1::text
            """,
            FIRM_SLUG,
        )}
        partner_id = users["helena.voss@meridian.invalid"]
        consultant_id = users["marcus.thorne@meridian.invalid"]
        analyst_id = users["priya.shah@meridian.invalid"]

        # Reset the engagement to draft + clear review history.
        await conn.execute(
            """
            UPDATE sessions
               SET review_state = 'draft',
                   review_assigned_to = NULL,
                   approved_at = NULL, approved_by = NULL,
                   submitted_at = NULL, submitted_by = NULL,
                   created_by_user_id = $2::uuid,
                   updated_at = NOW()
             WHERE id = $1::uuid
            """,
            sess["id"], consultant_id,
        )
        await conn.execute(
            "DELETE FROM review_records WHERE session_id = $1::uuid",
            sess["id"],
        )
        await conn.execute(
            """
            DELETE FROM audit_events
             WHERE resource_type = 'session'
               AND resource_id = $1::text
               AND action LIKE 'review.%'
            """,
            str(sess["id"]),
        )

        # Make sure firms.allow_self_approval = FALSE so step 2's
        # self-approval denial is meaningful.
        await conn.execute(
            "UPDATE firms SET allow_self_approval = FALSE WHERE slug = $1::text",
            FIRM_SLUG,
        )

        # Make sure all three users have engagement memberships so the
        # listEngagementMembers reviewer-picker has a populated team.
        for uid, role in [(consultant_id, "lead"), (partner_id, "member"),
                          (analyst_id, "member")]:
            await conn.execute(
                """
                INSERT INTO engagement_memberships (engagement_id, user_id, role, added_by)
                VALUES ($1::uuid, $2::uuid, $3, $2::uuid)
                ON CONFLICT (engagement_id, user_id) DO UPDATE SET role = EXCLUDED.role
                """,
                sess["id"], uid, role,
            )

    return {
        "session_id": str(sess["id"]),
        "engagement_title": sess["title"],
        "firm_id": str(sess["firm_id"]),
        "partner_id": str(partner_id),
        "consultant_id": str(consultant_id),
        "analyst_id": str(analyst_id),
    }


async def _ensure_artifacts_for_stale_count(session_id: UUID) -> int:
    """Step 8 asserts artifacts get flagged stale on auto-revert. The
    Meridian seed has plenty of artifacts, but we cap to ``ready``
    ones (the W15/D2 stale-flagger only touches those). Returns the
    count of ready artifacts so the cycle can assert it later."""
    from db.connection import acquire

    async with acquire() as conn:
        n = await conn.fetchval(
            """
            SELECT COUNT(*) FROM export_artifacts
             WHERE session_id = $1::uuid AND status = 'ready'
            """,
            session_id,
        )
    return int(n or 0)


async def _read_review_records(session_id: UUID) -> list[dict[str, Any]]:
    from db.connection import acquire

    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, from_state, to_state, action, actor_id, reviewer_id,
                   feedback, created_at
              FROM review_records
             WHERE session_id = $1::uuid
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
                pass
        out.append({
            "id": str(r["id"]),
            "from_state": r["from_state"],
            "to_state": r["to_state"],
            "action": r["action"],
            "actor_id": str(r["actor_id"]),
            "reviewer_id": str(r["reviewer_id"]) if r["reviewer_id"] else None,
            "feedback": fb,
            "created_at": r["created_at"].isoformat(),
        })
    return out


async def _read_audit_rows(session_id: UUID) -> list[dict[str, Any]]:
    from db.connection import acquire

    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, action, actor_user_id, payload, created_at
              FROM audit_events
             WHERE resource_type = 'session'
               AND resource_id = $1::text
               AND action LIKE 'review.%'
             ORDER BY created_at ASC
            """,
            str(session_id),
        )
    out: list[dict[str, Any]] = []
    for r in rows:
        payload = r["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                pass
        out.append({
            "id": str(r["id"]),
            "action": r["action"],
            "actor_user_id": str(r["actor_user_id"]) if r["actor_user_id"] else None,
            "payload": payload,
            "created_at": r["created_at"].isoformat(),
        })
    return out


# ---------------------------------------------------------------------------
# Cycle steps
# ---------------------------------------------------------------------------


async def _run_cycle(ctx: dict[str, Any]) -> list[StepResult]:
    from core.review.feedback import ReviewFeedback, SectionPointer
    from core.review.service import (
        auto_revert_if_locked,
        resolve_section_pointer,
        transition_review,
    )
    from core.review.state_machine import ReviewAction

    sid = UUID(ctx["session_id"])
    partner = UUID(ctx["partner_id"])
    consultant = UUID(ctx["consultant_id"])
    analyst = UUID(ctx["analyst_id"])

    steps: list[StepResult] = []
    request_changes_record_id: str | None = None

    # Step 1 — Consultant submits, assigns partner.
    r1 = await transition_review(
        sid, ReviewAction.SUBMIT_FOR_REVIEW, consultant, reviewer_id=partner,
    )
    steps.append(StepResult(
        step=1, label="consultant.submit (assigns partner)",
        actor="consultant", ok=r1.ok, status_code=r1.status_code,
        from_state=r1.from_state, to_state=r1.to_state, reason=r1.reason,
    ))

    # Step 2 — Consultant attempts to approve own work → 403.
    r2 = await transition_review(sid, ReviewAction.APPROVE, consultant)
    steps.append(StepResult(
        step=2, label="consultant.approve_own (self-approval denied)",
        actor="consultant", ok=(r2.status_code == 403), status_code=r2.status_code,
        from_state=r2.from_state, to_state=r2.to_state,
        reason=r2.reason[:200],
    ))

    # Step 3 — Analyst (member, not assigned reviewer) attempts approve → 403.
    r3 = await transition_review(sid, ReviewAction.APPROVE, analyst)
    steps.append(StepResult(
        step=3, label="analyst.approve (unauthorized member)",
        actor="analyst", ok=(r3.status_code == 403), status_code=r3.status_code,
        from_state=r3.from_state, to_state=r3.to_state,
        reason=r3.reason[:200],
    ))

    # Step 4 — Partner requests changes with 1 major + 1 minor pointer.
    fb = ReviewFeedback(
        overall_note=(
            "Tighten the synergy basis (it's the load-bearing assumption); "
            "the risks section is OK but could use one more entry."
        ),
        severity="major",
        section_pointers=[
            SectionPointer(
                section_path="synergy_estimate",
                note="Magnitude needs explicit sourcing per the W14 carve-out playbook.",
                severity="major",
            ),
            SectionPointer(
                section_path="risks",
                note="Add a driver-shortage risk for completeness.",
                severity="minor",
            ),
        ],
    )
    r4 = await transition_review(
        sid, ReviewAction.REQUEST_CHANGES, partner, structured_feedback=fb,
    )
    if r4.ok:
        request_changes_record_id = r4.review_record_id
    steps.append(StepResult(
        step=4, label="partner.request_changes (1 major + 1 minor)",
        actor="partner", ok=r4.ok, status_code=r4.status_code,
        from_state=r4.from_state, to_state=r4.to_state,
        extra={"review_record_id": request_changes_record_id},
    ))

    # Step 5 — Consultant resubmits early → 409 with blocking_pointer_paths.
    r5 = await transition_review(sid, ReviewAction.RESUBMIT, consultant)
    steps.append(StepResult(
        step=5, label="consultant.resubmit_early (blocked)",
        actor="consultant",
        ok=(r5.status_code == 409 and r5.blocking_pointer_paths == ["synergy_estimate"]),
        status_code=r5.status_code,
        from_state=r5.from_state, to_state=r5.to_state,
        reason=r5.reason[:200],
        extra={"blocking_pointer_paths": r5.blocking_pointer_paths},
    ))

    # Step 6 — Consultant resolves the major pointer + resubmits → in_review.
    if request_changes_record_id is None:
        raise RuntimeError("step 4 didn't produce a review_record_id; cycle is broken")
    rp = await resolve_section_pointer(
        sid, UUID(request_changes_record_id), consultant, "synergy_estimate",
    )
    r6 = await transition_review(sid, ReviewAction.RESUBMIT, consultant)
    steps.append(StepResult(
        step=6, label="consultant.resolve_major + resubmit",
        actor="consultant", ok=(r6.ok and rp.ok and rp.changed),
        status_code=r6.status_code,
        from_state=r6.from_state, to_state=r6.to_state,
        extra={"pointer_resolved": rp.ok, "pointer_changed": rp.changed},
    ))

    # Step 7 — Partner approves → approved.
    r7 = await transition_review(sid, ReviewAction.APPROVE, partner)
    # Confirm reviewer ≠ author at the DB level via the approved_by column.
    from db.connection import acquire
    async with acquire() as conn:
        sess_row = await conn.fetchrow(
            "SELECT approved_by, created_by_user_id, approved_at FROM sessions WHERE id = $1::uuid",
            sid,
        )
    reviewer_ne_author = (
        sess_row["approved_by"] != sess_row["created_by_user_id"]
        and sess_row["approved_at"] is not None
    )
    steps.append(StepResult(
        step=7, label="partner.approve (reviewer != author)",
        actor="partner", ok=(r7.ok and reviewer_ne_author),
        status_code=r7.status_code,
        from_state=r7.from_state, to_state=r7.to_state,
        extra={
            "approved_by": str(sess_row["approved_by"]),
            "author": str(sess_row["created_by_user_id"]),
            "reviewer_ne_author": reviewer_ne_author,
        },
    ))

    # Step 8 — Consultant edits memo → auto-revert + artifacts flagged stale.
    ready_count = await _ensure_artifacts_for_stale_count(sid)
    r8 = await auto_revert_if_locked(
        sid, consultant,
        edit_label="W15/D5 e2e: consultant edited approved engagement",
    )
    auto_revert_ok = (
        r8 is not None
        and r8.ok
        and r8.from_state == "approved"
        and r8.to_state == "draft"
        and r8.artifacts_marked_stale >= ready_count
    )
    steps.append(StepResult(
        step=8, label="consultant.edit_after_approve (auto-revert)",
        actor="consultant", ok=auto_revert_ok,
        status_code=r8.status_code if r8 else 200,
        from_state=r8.from_state if r8 else None,
        to_state=r8.to_state if r8 else None,
        extra={
            "ready_artifacts_before": ready_count,
            "artifacts_marked_stale": r8.artifacts_marked_stale if r8 else 0,
        },
    ))

    # Step 9 — Resubmit (no pointers blocking now — round 1's major
    # was resolved before approval; no new request_changes round
    # exists) + partner approves again.
    r9a = await transition_review(sid, ReviewAction.SUBMIT_FOR_REVIEW, consultant, reviewer_id=partner)
    r9b = await transition_review(sid, ReviewAction.APPROVE, partner)
    steps.append(StepResult(
        step=9, label="consultant.resubmit + partner.approve (round 2)",
        actor="consultant+partner", ok=(r9a.ok and r9b.ok),
        status_code=r9b.status_code,
        from_state=r9a.from_state, to_state=r9b.to_state,
        extra={
            "resubmit_to_state": r9a.to_state,
            "approve_to_state": r9b.to_state,
        },
    ))

    # Step 10 — Consultant marks delivered → delivered.
    r10 = await transition_review(sid, ReviewAction.MARK_DELIVERED, consultant)
    steps.append(StepResult(
        step=10, label="consultant.mark_delivered",
        actor="consultant", ok=(r10.ok and r10.to_state == "delivered"),
        status_code=r10.status_code,
        from_state=r10.from_state, to_state=r10.to_state,
    ))

    return steps


# ---------------------------------------------------------------------------
# Headline assertions
# ---------------------------------------------------------------------------


def _headline_assertions(
    steps: list[StepResult],
    records: list[dict[str, Any]],
    audit: list[dict[str, Any]],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    out: dict[str, Any] = {}

    # 1. All 10 steps produce the expected outcome.
    out["all_10_steps_pass"] = all(s.ok for s in steps)
    out["step_pass_count"] = sum(1 for s in steps if s.ok)

    # 2. Self-approval blocked (step 2).
    s2 = next((s for s in steps if s.step == 2), None)
    out["self_approval_blocked"] = bool(s2 and s2.status_code == 403)

    # 3. Unauthorized member approval blocked (step 3).
    s3 = next((s for s in steps if s.step == 3), None)
    out["unauthorized_member_blocked"] = bool(s3 and s3.status_code == 403)

    # 4. Resubmit-gating works (step 5).
    s5 = next((s for s in steps if s.step == 5), None)
    out["resubmit_gating_enforced"] = bool(
        s5
        and s5.status_code == 409
        and s5.extra.get("blocking_pointer_paths") == ["synergy_estimate"]
    )

    # 5. Lock-on-approval auto-revert works (step 8).
    s8 = next((s for s in steps if s.step == 8), None)
    out["lock_on_approval_auto_revert"] = bool(s8 and s8.ok)
    out["artifacts_flagged_stale"] = (s8.extra.get("artifacts_marked_stale") or 0) if s8 else 0

    # 6. review_records has the complete transition sequence in order.
    expected_actions = [
        "submit_for_review",         # step 1
        "request_changes",           # step 4
        "resubmit",                  # step 6 (step 5 was blocked, no row)
        "approve",                   # step 7
        "auto_revert",               # step 8
        "submit_for_review",         # step 9a
        "approve",                   # step 9b
        "mark_delivered",            # step 10
    ]
    observed_actions = [r["action"] for r in records]
    out["review_records_sequence_complete"] = observed_actions == expected_actions
    out["expected_action_sequence"] = expected_actions
    out["observed_action_sequence"] = observed_actions

    # 7. audit_log has an entry for every transition. The W15/D2
    # service writes one ``review.<action>`` audit_events row per
    # review_records row, with the review_record_id in the payload.
    # W15/D3's resolve_section_pointer ALSO writes audit rows
    # (``review.resolve_pointer``) which are legitimately extra —
    # they're audits without a paired review_records row because
    # resolving a pointer isn't a state transition. So the check
    # is: every review_records row's id must appear in some audit
    # row's payload, and there can be additional audit rows beyond
    # that (resolve_pointer, future actions).
    audit_record_ids = {
        (a["payload"] or {}).get("review_record_id")
        for a in audit
        if isinstance(a.get("payload"), dict)
    }
    missing_audit_for_record_ids = [
        r["id"] for r in records if r["id"] not in audit_record_ids
    ]
    out["audit_covers_every_transition"] = not missing_audit_for_record_ids
    out["audit_missing_for_record_ids"] = missing_audit_for_record_ids
    out["review_records_count"] = len(records)
    out["audit_rows_count"] = len(audit)
    # ``extra_audit_rows_count`` ≥ 0 means we have legitimate audits
    # beyond pure transitions (resolve_pointer, etc.); not a failure.
    out["extra_audit_rows_count"] = max(0, len(audit) - len(records))

    # 8. Every approval recorded reviewer ≠ author.
    approvals = [r for r in records if r["action"] == "approve"]
    out["approvals_count"] = len(approvals)
    out["every_approval_reviewer_ne_author"] = all(
        r["actor_id"] != ctx["consultant_id"] for r in approvals
    )

    out["headline_pass"] = all(v for k, v in out.items() if isinstance(v, bool))
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main_async(args: argparse.Namespace) -> int:
    from db.connection import close_db, init_db

    _BENCH_ROOT.mkdir(parents=True, exist_ok=True)
    summary_path = _BENCH_ROOT / "summary.json"

    if args.summary_only:
        if not summary_path.exists():
            print("no previous summary.json. Run without --summary-only first.")
            return 1
        print(summary_path.read_text(encoding="utf-8"))
        return 0

    t0 = time.perf_counter()
    await init_db()
    try:
        ctx = await _bootstrap_engagement()
        print(f"engagement: {ctx['engagement_title']}  session={ctx['session_id']}")
        print(f"  consultant (author) = {ctx['consultant_id']}")
        print(f"  partner             = {ctx['partner_id']}")
        print(f"  analyst             = {ctx['analyst_id']}")
        print()
        steps = await _run_cycle(ctx)
        records = await _read_review_records(UUID(ctx["session_id"]))
        audit = await _read_audit_rows(UUID(ctx["session_id"]))
    finally:
        await close_db()
    wall = time.perf_counter() - t0

    headline = _headline_assertions(steps, records, audit, ctx)
    summary = CycleSummary(
        firm_slug=FIRM_SLUG,
        session_id=ctx["session_id"],
        engagement_title=ctx["engagement_title"],
        steps=steps,
        review_records=records,
        audit_rows=audit,
        headline=headline,
        headline_pass=bool(headline.get("headline_pass")),
    )

    body = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "wall_seconds": round(wall, 3),
        "firm_slug": summary.firm_slug,
        "session_id": summary.session_id,
        "engagement_title": summary.engagement_title,
        "n_steps": len(steps),
        "n_review_records": len(records),
        "n_audit_rows": len(audit),
        "headline": headline,
        "headline_pass": summary.headline_pass,
        "steps": [asdict(s) for s in steps],
        "review_records": records,
        "audit_rows": audit,
    }
    summary_path.write_text(json.dumps(body, indent=2, default=str), encoding="utf-8")

    print("=== STEPS ===")
    for s in steps:
        flag = "PASS" if s.ok else "FAIL"
        print(f"  [{flag}] step={s.step:>2}  actor={s.actor:<18}  {s.label}")
        print(f"          status={s.status_code}  {s.from_state} -> {s.to_state}")
        if not s.ok and s.reason:
            print(f"          reason: {s.reason[:120]}")
    print()
    print("=== HEADLINE ===")
    for k, v in headline.items():
        if isinstance(v, bool):
            print(f"  [{'PASS' if v else 'FAIL'}] {k}")
        elif not isinstance(v, (dict, list)):
            print(f"  {k}: {v}")
    print()
    print(f"review_records: {len(records)}  audit_rows: {len(audit)}  wall={wall:.2f}s")
    print(f"summary: {summary_path}")
    return 0 if summary.headline_pass else 1


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--summary-only", action="store_true")
    return p.parse_args()


def main() -> None:
    sys.exit(asyncio.run(main_async(_parse_args())))


if __name__ == "__main__":
    main()
