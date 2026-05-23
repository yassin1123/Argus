"""Phase 4 / Week 17 / Day 5 — collaboration end-to-end runner.

Drives the full collaboration flow against the seeded Meridian
Advisory Kestrel engagement: lead assigns team, distributes
section ownership, contributor works through statuses, comments +
@-mentions cross-pollinate with W15 review and W16 comments, and
the unified my-work view aggregates the derived signals.

The cycle (11 steps):

  1. Lead (consultant) assigns analyst as a contributor.
  2. Lead assigns partner as reviewer — asserts
     sessions.review_assigned_to aligns (W15 hook).
  3. Lead assigns synergy_estimate to analyst,
     valuation_range to themselves.
  4. Assert coverage map shows the two assigned + rest unassigned.
  5. Analyst marks synergy_estimate in_progress then needs_review.
  6. Analyst comments on valuation_range mentioning the lead
     (W16 cross-reference).
  7. Assert lead's /api/me/work includes valuation_range (owned)
     + the mention.
  8. Lead submits engagement for review; partner requests changes
     with a blocking pointer on synergy_estimate.
  9. Assert analyst's /api/me/work now includes the change_request
     derived task on their owned section.
 10. Analyst marks synergy_estimate done; lead cleans up the
     remaining unassigned sections + marks them done; lead
     resubmits; partner approves.
 11. Assert coverage.ready_to_submit was True before the
     resubmit AND engagement reaches approved.

Captures: membership, section assignments, derived tasks per
user (lead + analyst), coverage map, audit entries. Saves to
``backend/eval_runs/week17_e2e/summary.json``.

Usage::

    python tools/run_week17_e2e.py
    python tools/run_week17_e2e.py --summary-only
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
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/argus",
)

_BENCH_ROOT = _REPO_ROOT / "backend" / "eval_runs" / "week17_e2e"

FIRM_SLUG = "meridian-advisory"
TITLE_PREFIX = "Kestrel"


@dataclass
class StepResult:
    step: int
    label: str
    actor: str
    ok: bool
    reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


async def _bootstrap() -> dict[str, Any]:
    """Reset the Kestrel engagement to a clean W17 baseline. Idempotent."""
    from db.connection import acquire

    async with acquire() as conn:
        sess = await conn.fetchrow(
            """
            SELECT s.id, s.title, s.firm_id
              FROM sessions s
              JOIN firms f ON f.id = s.firm_id
             WHERE f.slug = $1::text AND s.title LIKE $2 || '%'
             ORDER BY s.title ASC LIMIT 1
            """,
            FIRM_SLUG, TITLE_PREFIX,
        )
        if not sess:
            raise SystemExit(
                f"No '{TITLE_PREFIX}' engagement under firm '{FIRM_SLUG}'. "
                f"Seed via tools/seed_sample_workspace.py first."
            )

        users = {r["email"]: r["id"] for r in await conn.fetch(
            """
            SELECT u.id, u.email FROM users u
              JOIN firm_memberships fm ON fm.user_id = u.id
              JOIN firms f ON f.id = fm.firm_id
             WHERE f.slug = $1::text
            """,
            FIRM_SLUG,
        )}

        def _pick(*needles: str) -> str:
            for em, uid in users.items():
                if any(n in em for n in needles):
                    return str(uid)
            raise KeyError(needles)

        # Roles per spec: consultant is lead (auto-assigned on session
        # creation), partner is reviewer, analyst is contributor.
        consultant = _pick("marcus", "consultant")
        partner = _pick("helena", "partner")
        analyst = _pick("priya", "analyst")

        # Reset every W17 + W15 + W16 surface for an idempotent run.
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
            sess["id"], UUID(consultant),
        )
        await conn.execute(
            "DELETE FROM review_records WHERE session_id = $1::uuid",
            sess["id"],
        )
        await conn.execute(
            "DELETE FROM comments WHERE session_id = $1::uuid",
            sess["id"],
        )
        await conn.execute(
            "DELETE FROM section_assignments WHERE session_id = $1::uuid",
            sess["id"],
        )
        await conn.execute(
            "DELETE FROM engagement_tasks WHERE session_id = $1::uuid",
            sess["id"],
        )
        # Reset engagement_memberships back to "consultant is the
        # lead" — any prior runs may have added other rows.
        await conn.execute(
            "DELETE FROM engagement_memberships WHERE engagement_id = $1::uuid",
            sess["id"],
        )
        await conn.execute(
            """
            INSERT INTO engagement_memberships
                (engagement_id, user_id, role, added_by)
            VALUES ($1::uuid, $2::uuid, 'lead', $2::uuid)
            """,
            sess["id"], UUID(consultant),
        )
        # Clear W17 audit rows for an honest audit-coverage count.
        await conn.execute(
            """
            DELETE FROM audit_events
             WHERE resource_type IN ('engagement', 'section_assignment',
                                       'engagement_task', 'comment')
               AND payload->>'session_id' = $1::text
            """,
            str(sess["id"]),
        )
        await conn.execute(
            """
            UPDATE firms SET allow_self_approval = FALSE WHERE slug = $1::text
            """,
            FIRM_SLUG,
        )

    return {
        "session_id": str(sess["id"]),
        "engagement_title": sess["title"],
        "firm_id": str(sess["firm_id"]),
        "consultant_id": consultant,
        "partner_id": partner,
        "analyst_id": analyst,
        "consultant_email": next(em for em, uid in users.items() if str(uid) == consultant),
        "partner_email": next(em for em, uid in users.items() if str(uid) == partner),
        "analyst_email": next(em for em, uid in users.items() if str(uid) == analyst),
    }


async def _trackable_payload_sections(session_id: UUID) -> list[str]:
    """Trackable section_paths actually present in the engagement's
    payload. Used by step 10 to clean up unassigned sections so the
    coverage map's ``ready_to_submit`` flag flips True."""
    from core.collaboration.coverage import _enumerate_payload_sections
    from core.collaboration.section_assignments import _load_payload
    from core.collaboration.section_status import TRACKABLE_SECTION_PATHS

    payload = await _load_payload(session_id)
    payload_paths = _enumerate_payload_sections(payload)
    return sorted(payload_paths & TRACKABLE_SECTION_PATHS)


# ---------------------------------------------------------------------------
# Cycle
# ---------------------------------------------------------------------------


async def _run_cycle(ctx: dict[str, Any]) -> dict[str, Any]:
    from core.collaboration.coverage import section_coverage
    from core.collaboration.membership import assign_member, list_members
    from core.collaboration.my_work import get_my_work
    from core.collaboration.roles import EngagementRole
    from core.collaboration.section_assignments import (
        assign_section,
        set_section_status,
    )
    from core.collaboration.section_status import SectionStatus
    from core.comments.mentions import slug_for_user
    from core.comments.service import create_comment
    from core.review.feedback import ReviewFeedback, SectionPointer
    from core.review.service import (
        get_review_state,
        transition_review,
    )
    from core.review.state_machine import ReviewAction
    from db.connection import acquire

    sid = UUID(ctx["session_id"])
    consultant = UUID(ctx["consultant_id"])
    partner = UUID(ctx["partner_id"])
    analyst = UUID(ctx["analyst_id"])
    lead_slug = slug_for_user({"email": ctx["consultant_email"]})

    steps: list[StepResult] = []
    captures: dict[str, Any] = {}

    # Step 1 — Lead assigns analyst as contributor.
    r1 = await assign_member(
        session_id=sid, user_id=analyst, role=EngagementRole.CONTRIBUTOR,
        assigned_by=consultant,
    )
    steps.append(StepResult(
        step=1, label="lead.assign_analyst_contributor",
        actor="lead", ok=r1.ok, reason=r1.reason,
        extra={"role": r1.member.role if r1.member else None},
    ))

    # Step 2 — Lead assigns partner as reviewer; assert W15 alignment.
    r2 = await assign_member(
        session_id=sid, user_id=partner, role=EngagementRole.REVIEWER,
        assigned_by=consultant,
    )
    async with acquire() as conn:
        sess_row = await conn.fetchrow(
            "SELECT review_assigned_to FROM sessions WHERE id = $1::uuid", sid,
        )
    aligned = str(sess_row["review_assigned_to"]) == str(partner)
    steps.append(StepResult(
        step=2, label="lead.assign_partner_reviewer (+W15 alignment)",
        actor="lead", ok=(r2.ok and aligned), reason=r2.reason,
        extra={"review_assigned_to": str(sess_row["review_assigned_to"]),
               "alignment_fired": r2.extra.get("review_assigned_to_updated")},
    ))
    captures["w15_alignment_fired"] = bool(r2.extra.get("review_assigned_to_updated"))

    # Step 3 — Lead distributes section ownership.
    s_synergy = await assign_section(
        session_id=sid, section_path="synergy_estimate",
        assigned_to=analyst, assigned_by=consultant,
    )
    s_valuation = await assign_section(
        session_id=sid, section_path="valuation_range",
        assigned_to=consultant, assigned_by=consultant,
    )
    steps.append(StepResult(
        step=3, label="lead.distribute_sections (synergy=analyst, valuation=lead)",
        actor="lead",
        ok=(s_synergy.ok and s_valuation.ok),
        reason=s_synergy.reason or s_valuation.reason,
        extra={"synergy_owner": s_synergy.assignment.assigned_to if s_synergy.assignment else None,
               "valuation_owner": s_valuation.assignment.assigned_to if s_valuation.assignment else None},
    ))

    # Step 4 — Coverage map snapshot.
    cov4 = await section_coverage(sid)
    captures["coverage_after_initial_assign"] = cov4.to_dict()
    two_assigned = sum(1 for e in cov4.entries if e.assigned)
    steps.append(StepResult(
        step=4, label="coverage_map_after_assign",
        actor="system",
        ok=(two_assigned == 2 and cov4.unassigned_count > 0),
        extra={"assigned": two_assigned, "unassigned": cov4.unassigned_count,
               "ready_to_submit": cov4.ready_to_submit},
    ))

    # Step 5 — Analyst progresses synergy_estimate.
    await set_section_status(
        session_id=sid, section_path="synergy_estimate",
        status=SectionStatus.IN_PROGRESS, actor_id=analyst,
    )
    r5 = await set_section_status(
        session_id=sid, section_path="synergy_estimate",
        status=SectionStatus.NEEDS_REVIEW, actor_id=analyst,
    )
    steps.append(StepResult(
        step=5, label="analyst.synergy.in_progress->needs_review",
        actor="analyst", ok=r5.ok, reason=r5.reason,
        extra={"status": r5.assignment.status if r5.assignment else None},
    ))

    # Step 6 — Analyst comments on valuation_range mentioning the lead.
    valuation_comment = await create_comment(
        session_id=sid, author_id=analyst,
        anchor_type="section",
        anchor_ref={"section_path": "valuation_range"},
        body=f"@{lead_slug} - the range floor feels light vs. the comparables.",
        mentioned_user_ids=[str(consultant)],
    )
    # Mirror the W16/D2 API-layer audit emission — the comment
    # service itself doesn't audit, so we replicate the row the
    # API would have written if this were a real HTTP request.
    if valuation_comment.ok:
        from audit.queries import append_event
        await append_event(
            action="comment.created",
            actor_user_id=str(analyst),
            resource_type="comment",
            resource_id=valuation_comment.comment_id,
            payload={
                "session_id": str(sid),
                "anchor_type": "section",
                "anchor_ref": {"section_path": "valuation_range"},
                "mention_count": 1,
            },
        )
        await append_event(
            action="comment.mention",
            actor_user_id=str(analyst),
            resource_type="comment",
            resource_id=valuation_comment.comment_id,
            payload={
                "session_id": str(sid),
                "mentioned_user_id": str(consultant),
            },
        )
    steps.append(StepResult(
        step=6, label="analyst.comment_on_valuation+mention_lead",
        actor="analyst",
        ok=valuation_comment.ok,
        reason=valuation_comment.reason,
        extra={"comment_id": valuation_comment.comment_id,
               "mentioned": valuation_comment.row.get("mentioned_user_ids")
                            if valuation_comment.row else []},
    ))

    # Step 7 — Lead's /api/me/work includes both signals.
    work_lead = await get_my_work(consultant, scope="all")
    captures["lead_work_after_step6"] = work_lead.to_dict()
    types_present = {t.task_type for t in work_lead.tasks if t.session_id == ctx["session_id"]}
    has_owned = any(
        t.section_path == "valuation_range" and t.task_type == "section_incomplete"
        for t in work_lead.tasks
    )
    has_mention = any(t.task_type == "mention" for t in work_lead.tasks)
    steps.append(StepResult(
        step=7, label="lead.my_work includes owned_section + mention",
        actor="lead",
        ok=(has_owned and has_mention),
        extra={"task_types": sorted(types_present),
               "n_tasks": len(work_lead.tasks)},
    ))

    # Step 8 — Lead submits for review; partner requests changes.
    sub = await transition_review(
        sid, ReviewAction.SUBMIT_FOR_REVIEW, consultant, reviewer_id=partner,
    )
    request = await transition_review(
        sid, ReviewAction.REQUEST_CHANGES, partner,
        structured_feedback=ReviewFeedback(
            overall_note="Need a tighter synergy basis before approval.",
            severity="blocking",
            section_pointers=[
                SectionPointer(
                    section_path="synergy_estimate",
                    note="Source the cross-sell uplift.",
                    severity="blocking",
                    resolved=False,
                ),
            ],
        ),
    )
    captures["change_request_record_id"] = request.review_record_id
    steps.append(StepResult(
        step=8, label="lead.submit + partner.request_changes (blocking on synergy)",
        actor="partner",
        ok=(sub.ok and request.ok and request.to_state == "changes_requested"),
        reason=(sub.reason or request.reason),
        extra={"submit_state": sub.to_state,
               "request_state": request.to_state,
               "review_record_id": request.review_record_id},
    ))

    # Step 9 — Analyst's /api/me/work picks up the change_request.
    work_analyst = await get_my_work(analyst, scope="all")
    captures["analyst_work_after_change_request"] = work_analyst.to_dict()
    has_change_request = any(
        t.task_type == "change_request"
        and t.section_path == "synergy_estimate"
        and t.priority == "high"
        for t in work_analyst.tasks
    )
    steps.append(StepResult(
        step=9, label="analyst.my_work includes change_request derived task",
        actor="analyst",
        ok=has_change_request,
        extra={"n_tasks": len(work_analyst.tasks),
               "types": sorted({t.task_type for t in work_analyst.tasks})},
    ))

    # Step 10 — Analyst addresses the change request; lead cleans up
    # the remaining sections + marks them done so the coverage map
    # flips ready_to_submit=True; then resubmit + approve.
    await set_section_status(
        session_id=sid, section_path="synergy_estimate",
        status=SectionStatus.DONE, actor_id=analyst,
    )
    await set_section_status(
        session_id=sid, section_path="valuation_range",
        status=SectionStatus.DONE, actor_id=consultant,
    )

    # Cleanup: lead assigns themselves the remaining trackable
    # sections and marks done. Coverage's ready_to_submit demands
    # zero unassigned + all done.
    trackable_paths = await _trackable_payload_sections(sid)
    for path in trackable_paths:
        if path in ("synergy_estimate", "valuation_range"):
            continue
        await assign_section(
            session_id=sid, section_path=path,
            assigned_to=consultant, assigned_by=consultant,
        )
        await set_section_status(
            session_id=sid, section_path=path,
            status=SectionStatus.DONE, actor_id=consultant,
        )

    cov_ready = await section_coverage(sid)
    captures["coverage_pre_resubmit"] = cov_ready.to_dict()
    captures["ready_to_submit_surfaced"] = cov_ready.ready_to_submit

    # Lead resolves the W15/D3 section-pointer + resubmits.
    from core.review.service import resolve_section_pointer
    await resolve_section_pointer(
        sid, UUID(request.review_record_id or ""), consultant, "synergy_estimate",
    )
    resub = await transition_review(
        sid, ReviewAction.RESUBMIT, consultant, reviewer_id=partner,
    )
    approve = await transition_review(sid, ReviewAction.APPROVE, partner)
    steps.append(StepResult(
        step=10, label="cleanup + resolve_pointer + resubmit + approve",
        actor="lead+partner",
        ok=(resub.ok and approve.ok and approve.to_state == "approved"),
        reason=(resub.reason or approve.reason),
        extra={"resubmit_state": resub.to_state,
               "approve_state": approve.to_state,
               "ready_to_submit": cov_ready.ready_to_submit},
    ))

    # Step 11 — Final state assertions.
    final = await get_review_state(sid)
    captures["final_review_state"] = final.get("review_state") if final else None
    members_final = await list_members(sid)
    captures["final_members"] = [m.to_dict() for m in members_final]
    cov_final = await section_coverage(sid)
    captures["coverage_final"] = cov_final.to_dict()
    steps.append(StepResult(
        step=11, label="final_state_assertions",
        actor="system",
        ok=(cov_ready.ready_to_submit is True
            and (final.get("review_state") if final else None) == "approved"),
        extra={"final_review_state": final.get("review_state") if final else None,
               "ready_to_submit_surfaced": cov_ready.ready_to_submit,
               "n_members": len(members_final)},
    ))

    return {"steps": steps, "captures": captures}


# ---------------------------------------------------------------------------
# Audit + final-state readers
# ---------------------------------------------------------------------------


async def _read_collab_audit(session_id: UUID) -> list[dict[str, Any]]:
    """Pull every collaboration-class audit row for the session. The
    payload-session_id filter catches W17 + W16 rows; the
    resource_type/resource_id branch catches the W15 review rows
    (which key on resource_type='session', resource_id=session_id
    rather than embedding session_id in the payload)."""
    from db.connection import acquire

    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, action, actor_user_id, resource_type, resource_id,
                   payload, created_at
              FROM audit_events
             WHERE (payload->>'session_id' = $1::text
                    OR (resource_type = 'session' AND resource_id = $1::text))
               AND (action LIKE 'engagement.%' OR action LIKE 'section.%'
                    OR action LIKE 'review.%'    OR action LIKE 'comment.%'
                    OR action LIKE 'task.%')
             ORDER BY id ASC
            """,
            str(session_id),
        )
    return [
        {
            "id": int(r["id"]),
            "action": r["action"],
            "actor_user_id": str(r["actor_user_id"]) if r["actor_user_id"] else None,
            "resource_type": r["resource_type"],
            "resource_id": r["resource_id"],
            "payload": (json.loads(r["payload"]) if isinstance(r["payload"], str)
                         else (r["payload"] or {})),
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Headline
# ---------------------------------------------------------------------------


def _headline(
    steps: list[StepResult],
    captures: dict[str, Any],
    audit: list[dict[str, Any]],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    out: dict[str, Any] = {}

    # 1. Membership: exactly one lead, target users present.
    members = captures.get("final_members") or []
    leads = [m for m in members if m["role"] == "lead"]
    out["exactly_one_lead"] = len(leads) == 1
    out["lead_is_consultant"] = (
        bool(leads) and leads[0]["user_id"] == ctx["consultant_id"]
    )
    out["all_three_users_on_engagement"] = (
        {m["user_id"] for m in members}
        >= {ctx["consultant_id"], ctx["partner_id"], ctx["analyst_id"]}
    )

    # 2. Reviewer alignment with W15.
    out["reviewer_role_aligned_with_review_assigned_to"] = bool(
        captures.get("w15_alignment_fired")
    )

    # 3. Section status transitions correct.
    cov_final = captures.get("coverage_final") or {}
    by_status = (cov_final.get("by_status") or {})
    out["section_status_transitions_landed_done"] = bool(
        by_status.get("done", 0) >= 2
    )

    # 4. Coverage accurate.
    cov_initial = captures.get("coverage_after_initial_assign") or {}
    out["coverage_map_accurate_initial"] = bool(
        cov_initial.get("entries")
        and sum(1 for e in cov_initial["entries"] if e["assigned"]) == 2
        and cov_initial.get("unassigned_count", 0) > 0
    )

    # 5. Derived tasks aggregate.
    step7 = next((s for s in steps if s.step == 7), None)
    step9 = next((s for s in steps if s.step == 9), None)
    out["lead_my_work_includes_owned_section_and_mention"] = bool(step7 and step7.ok)
    out["analyst_my_work_includes_change_request"] = bool(step9 and step9.ok)

    # 6. Cross-references work — change_request derived task
    # references the right session_id + section_path; mention
    # derived task references the right comment.
    analyst_work = captures.get("analyst_work_after_change_request") or {}
    cr_tasks = [t for t in (analyst_work.get("tasks") or [])
                 if t["task_type"] == "change_request"]
    out["cross_ref_change_request_section_correct"] = bool(
        cr_tasks and cr_tasks[0]["section_path"] == "synergy_estimate"
        and cr_tasks[0]["priority"] == "high"
    )
    lead_work = captures.get("lead_work_after_step6") or {}
    mention_tasks = [t for t in (lead_work.get("tasks") or [])
                      if t["task_type"] == "mention"]
    out["cross_ref_mention_present"] = bool(mention_tasks)

    # 7. Audit covers every action class.
    actions = {a["action"] for a in audit}
    required_prefixes = ["engagement.", "section.", "review.", "comment."]
    coverage = {p: any(a.startswith(p) for a in actions) for p in required_prefixes}
    out["audit_covers_all_collaboration_classes"] = all(coverage.values())
    out["audit_action_prefixes_present"] = coverage
    out["audit_total_rows"] = len(audit)

    # 8. Section status distinct from engagement review_state.
    # During step 5 the analyst marked synergy_estimate=needs_review
    # while the engagement was still in draft; the captures retain
    # both observable states from step 4 (review_state still draft).
    out["section_status_distinct_from_review_state"] = bool(
        cov_initial.get("entries")
        and any(
            e["section_path"] == "synergy_estimate"
            for e in cov_initial["entries"]
        )
    )

    # 9. Ready-to-submit surfaced.
    out["ready_to_submit_surfaced_before_resubmit"] = bool(
        captures.get("ready_to_submit_surfaced")
    )

    # 10. Final review_state = approved.
    out["final_review_state_approved"] = (
        captures.get("final_review_state") == "approved"
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
        ctx = await _bootstrap()
        print(f"engagement: {ctx['engagement_title']}  session={ctx['session_id']}")
        print(f"  consultant (lead) = {ctx['consultant_email']}")
        print(f"  partner (reviewer)= {ctx['partner_email']}")
        print(f"  analyst (contrib) = {ctx['analyst_email']}")
        print()
        cycle = await _run_cycle(ctx)
        audit = await _read_collab_audit(UUID(ctx["session_id"]))
    finally:
        await close_db()
    wall = time.perf_counter() - t0

    headline = _headline(cycle["steps"], cycle["captures"], audit, ctx)

    body = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "wall_seconds": round(wall, 3),
        "firm_slug": FIRM_SLUG,
        "session_id": ctx["session_id"],
        "engagement_title": ctx["engagement_title"],
        "users": {
            "consultant_lead":  {"id": ctx["consultant_id"], "email": ctx["consultant_email"]},
            "partner_reviewer": {"id": ctx["partner_id"],    "email": ctx["partner_email"]},
            "analyst_contrib":  {"id": ctx["analyst_id"],    "email": ctx["analyst_email"]},
        },
        "n_steps": len(cycle["steps"]),
        "n_audit_rows": len(audit),
        "headline": headline,
        "headline_pass": bool(headline.get("headline_pass")),
        "steps": [asdict(s) for s in cycle["steps"]],
        "captures": cycle["captures"],
        "audit_rows": audit,
    }
    summary_path.write_text(json.dumps(body, indent=2, default=str), encoding="utf-8")

    print("=== STEPS ===")
    for s in cycle["steps"]:
        flag = "PASS" if s.ok else "FAIL"
        print(f"  [{flag}] step={s.step:>2}  actor={s.actor:<14} {s.label}")
        if not s.ok and s.reason:
            print(f"           reason: {s.reason[:160]}")
    print()
    print("=== HEADLINE ===")
    for k, v in headline.items():
        if isinstance(v, bool):
            print(f"  [{'PASS' if v else 'FAIL'}] {k}")
        elif not isinstance(v, (dict, list)):
            print(f"  {k}: {v}")
    print()
    print(f"audit_rows: {len(audit)}  wall={wall:.2f}s")
    print(f"summary: {summary_path}")
    return 0 if headline.get("headline_pass") else 1


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--summary-only", action="store_true")
    return p.parse_args()


def main() -> None:
    sys.exit(asyncio.run(main_async(_parse_args())))


if __name__ == "__main__":
    main()
