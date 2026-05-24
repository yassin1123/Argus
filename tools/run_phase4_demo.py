"""Phase 4 / Week 19 / Day 4 — comprehensive Phase 4 demo runner.

The Phase 4 integration test. Drives every Phase 4 capability end-
to-end against the seeded Meridian Kestrel engagement with the
three named users:

  - Marcus Thorne (consultant, engagement lead, author)
  - Helena Voss (partner, reviewer + firm admin)
  - Priya Shah (analyst, contributor)

Narrative — seven phases:

  1. SETUP (W17)
       Consultant claims lead. Analyst added as contributor, partner
       as reviewer. Sections distributed: analyst owns
       synergy_estimate + financial_profile; consultant owns
       valuation_range + target_overview.

  2. DRAFTING (W9 + W17)
       Analyst "deepens" synergy_estimate (real W9 accept_deepening
       flow against a manually-inserted complete deepening row —
       proves the W9 → W19 wiring without paying the LLM tax).
       Marks the section needs_review. Consultant does the same for
       valuation_range.

  3. DISCUSSION (W16 + W18)
       Consultant posts a section comment on synergy_estimate
       mentioning the analyst → MENTION notification fires.
       Analyst replies, mentioning the partner — the partner is
       also a prior thread participant via the dispatch_batch
       dedup contract (MENTION wins). Thread resolved.

  4. REVIEW CYCLE (W15 + W18)
       Consultant submits for review → partner gets REVIEW_REQUESTED
       + email. Partner requests changes with a blocking pointer
       on financial_profile → consultant gets CHANGES_REQUESTED.

  5. ADDRESS + VERSION (W9 + W19)
       Analyst deepens financial_profile (W19 version 4 lands).
       Consultant resolves the pointer + resubmits.

  6. APPROVE (W15 + W18)
       Partner approves → consultant gets REVIEW_APPROVED. The
       engagement is locked.

  7. PROVENANCE (W19)
       Walk the full version history. Diff v1 vs the final
       version. Render the human-readable provenance narrative.

Cost discipline: $0.00 LLM. The W9 acceptance flow is driven
through manually-constructed section_deepening_runs rows (the LLM
deepener has its own e2e suite); the demo's purpose is to prove
W15/16/17/18/19 compose, not to re-test W9's generation.

Captures: versions, section assignments + statuses, comments,
review_records, notifications per user, audit trail. Saves to
``backend/eval_runs/phase4_demo/summary.json``.

Usage::

    python tools/run_phase4_demo.py
    python tools/run_phase4_demo.py --summary-only
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
from uuid import UUID, uuid4

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))
sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/argus",
)
os.environ.setdefault("ARGUS_EMAIL_ADAPTER", "capture")
os.environ.setdefault("ARGUS_BASE_URL", "https://argus.example.com")

_BENCH_ROOT = _REPO_ROOT / "backend" / "eval_runs" / "phase4_demo"

FIRM_SLUG = "meridian-advisory"
TITLE_PREFIX = "Kestrel"


@dataclass
class StepResult:
    step: int
    phase: str
    label: str
    actor: str
    ok: bool
    reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


async def _bootstrap() -> dict[str, Any]:
    """Reset Kestrel to a clean Phase-4-demo baseline. Idempotent:
    every prior demo run's state surfaces are wiped + reinstalled."""
    from db.connection import acquire

    async with acquire() as conn:
        sess = await conn.fetchrow(
            """
            SELECT s.id, s.title, s.firm_id FROM sessions s
              JOIN firms f ON f.id = s.firm_id
             WHERE f.slug = $1::text AND s.title LIKE $2 || '%'
             ORDER BY s.title ASC LIMIT 1
            """,
            FIRM_SLUG, TITLE_PREFIX,
        )
        if not sess:
            raise SystemExit(
                f"Seed Meridian first: tools/seed_sample_workspace.py"
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

        consultant = _pick("marcus", "consultant")
        partner = _pick("helena", "partner")
        analyst = _pick("priya", "analyst")

        # Reset every Phase-4 state surface.
        await conn.execute(
            """
            UPDATE sessions SET review_state='draft',
                                review_assigned_to=NULL,
                                approved_at=NULL, approved_by=NULL,
                                submitted_at=NULL, submitted_by=NULL,
                                created_by_user_id=$2::uuid,
                                updated_at=NOW()
             WHERE id=$1::uuid
            """,
            sess["id"], UUID(consultant),
        )
        for sql in [
            "DELETE FROM notifications WHERE session_id = $1::uuid",
            "DELETE FROM review_records WHERE session_id = $1::uuid",
            "DELETE FROM comments WHERE session_id = $1::uuid",
            "DELETE FROM section_assignments WHERE session_id = $1::uuid",
            "DELETE FROM engagement_memberships WHERE engagement_id = $1::uuid",
            "DELETE FROM section_deepening_runs WHERE session_id = $1::uuid",
            "DELETE FROM payload_versions WHERE session_id = $1::uuid",
        ]:
            await conn.execute(sql, sess["id"])
        # Restore consultant as lead (W17/D1 invariant).
        await conn.execute(
            """
            INSERT INTO engagement_memberships (engagement_id, user_id, role, added_by)
            VALUES ($1::uuid, $2::uuid, 'lead', $2::uuid)
            """,
            sess["id"], UUID(consultant),
        )

        # Plant a known synergy_estimate + financial_profile +
        # valuation_range + target_overview so the section-ownership
        # validation passes. Idempotent — replaces every demo run.
        report_row = await conn.fetchrow(
            "SELECT consulting_payload FROM reports WHERE session_id = $1::uuid",
            sess["id"],
        )
        cp = report_row["consulting_payload"] if report_row else None
        if isinstance(cp, str):
            try:
                cp = json.loads(cp)
            except Exception:
                cp = None
        cp = cp or {}
        cp["synergy_estimate"] = {
            "revenue_synergies": [
                {"type": "Cross-sell", "magnitude_gbp_m": 5.0,
                 "rationale": "Initial cross-sell estimate based on FY24 data.",
                 "basis_citations": []},
            ],
            "cost_synergies": [],
        }
        cp["financial_profile"] = {
            "ebitda_margin_pct": 14.0,
            "revenue_growth_3y_cagr_pct": 7.5,
            "free_cash_flow_conversion_pct": 70.0,
        }
        cp["valuation_range"] = {
            "low_gbp_m": 80.0, "high_gbp_m": 120.0, "method": "DCF + comps",
        }
        cp["target_overview"] = {
            "company": "Kestrel Logistics", "sector": "Logistics",
        }
        cp.pop("_w16_pre_deepen", None)
        await conn.execute(
            "UPDATE reports SET consulting_payload = $2::jsonb WHERE session_id = $1::uuid",
            sess["id"], json.dumps(cp),
        )

        # Clear phase-4 audit rows from prior runs so the demo's
        # audit assertion counts only in-cycle events.
        await conn.execute(
            """
            DELETE FROM audit_events
             WHERE (payload->>'session_id' = $1::text
                    OR resource_id = $1::text)
               AND (action LIKE 'engagement.%' OR action LIKE 'section.%'
                    OR action LIKE 'review.%'    OR action LIKE 'comment.%'
                    OR action LIKE 'task.%'      OR action LIKE 'version.%'
                    OR action LIKE 'section_deepening.%')
            """,
            str(sess["id"]),
        )

        await conn.execute(
            "UPDATE firms SET allow_self_approval=FALSE WHERE slug=$1::text",
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


# ---------------------------------------------------------------------------
# W9 helper — drive accept_deepening via a manually-inserted complete row
# ---------------------------------------------------------------------------


async def _stage_and_accept_deepening(
    session_id: UUID, firm_id: UUID, section_path: str,
    triggered_by: UUID, accepted_by: UUID,
    deepened_section: dict[str, Any],
    depth_directive: str,
) -> dict[str, Any]:
    """Insert a complete deepening row with a deterministic
    deepened_section_json + call the real W9 accept_deepening so
    the W19/D1 wiring fires. The LLM deepener is bypassed — its
    output is supplied directly. $0 cost."""
    from core.section_deepening.acceptance import accept_deepening
    from core.section_deepening.addressing import get_section
    from core.versioning.service import _load_live_payload_for_session
    from db.connection import acquire

    live = await _load_live_payload_for_session(session_id)
    original = get_section(live, section_path)

    deep_id = uuid4()
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO section_deepening_runs
                (id, session_id, firm_id, section_path, depth_directive,
                 triggered_by, original_section_json, deepened_section_json,
                 new_evidence_chunks_used, new_claim_ids, status,
                 created_at, completed_at)
            VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5,
                    $6::uuid, $7::jsonb, $8::jsonb,
                    0, '[]'::jsonb, 'complete',
                    NOW(), NOW())
            """,
            deep_id, session_id, firm_id, section_path, depth_directive,
            triggered_by, json.dumps(original), json.dumps(deepened_section),
        )
    return await accept_deepening(session_id, deep_id, accepted_by)


# ---------------------------------------------------------------------------
# Phase narrative
# ---------------------------------------------------------------------------


async def _run_cycle(ctx: dict[str, Any], capture) -> dict[str, Any]:
    from core.collaboration.membership import assign_member, list_members
    from core.collaboration.roles import EngagementRole
    from core.collaboration.section_assignments import (
        assign_section, set_section_status,
    )
    from core.collaboration.section_status import SectionStatus
    from core.collaboration.coverage import section_coverage
    from core.comments.mentions import slug_for_user
    from core.comments.service import (
        create_comment, reply_to_comment, resolve_thread,
    )
    from core.review.feedback import ReviewFeedback, SectionPointer
    from core.review.service import (
        get_review_state, resolve_section_pointer, transition_review,
    )
    from core.review.state_machine import ReviewAction
    from core.versioning import (
        diff_versions, list_versions, get_current_version,
    )
    from core.versioning.service import ensure_initial_version
    from audit.queries import append_event as audit_append_event

    sid = UUID(ctx["session_id"])
    firm_uuid = UUID(ctx["firm_id"])
    consultant = UUID(ctx["consultant_id"])
    partner = UUID(ctx["partner_id"])
    analyst = UUID(ctx["analyst_id"])
    partner_slug = slug_for_user({"email": ctx["partner_email"]})
    analyst_slug = slug_for_user({"email": ctx["analyst_email"]})

    steps: list[StepResult] = []
    captures: dict[str, Any] = {}

    # Seed the v1 initial snapshot so the full provenance chain is
    # present in version history. Idempotent — short-circuits when a
    # v1 already exists. This is what save_report calls in the real
    # API path (W19/D1 wiring).
    await ensure_initial_version(sid, created_by=consultant)

    # =====================================================================
    # PHASE 1 — SETUP (W17)
    # =====================================================================

    r = await assign_member(
        session_id=sid, user_id=analyst, role=EngagementRole.CONTRIBUTOR,
        assigned_by=consultant,
    )
    steps.append(StepResult(1, "setup", "assign analyst as contributor",
                             "consultant", r.ok, r.reason))
    r = await assign_member(
        session_id=sid, user_id=partner, role=EngagementRole.REVIEWER,
        assigned_by=consultant,
    )
    steps.append(StepResult(2, "setup", "assign partner as reviewer",
                             "consultant", r.ok, r.reason,
                             extra={"review_assigned_to_aligned":
                                    bool(r.extra.get("review_assigned_to_updated"))}))

    # Distribute sections. Per W17/D2 TRACKABLE_SECTION_PATHS,
    # recommendation isn't trackable — we use target_overview instead.
    # Every TRACKABLE section present in the merged reports view
    # gets an owner — that's what makes coverage_ready_to_submit
    # flip True in Phase 5. Splits roughly along analyst (numbers /
    # detail / scope) vs consultant (structure / framing / strategy).
    distribution = [
        ("synergy_estimate",            analyst),
        ("financial_profile",           analyst),
        ("integration_plan",            analyst),
        ("risks",                       analyst),
        ("counterarguments",            analyst),
        ("valuation_range",             consultant),
        ("target_overview",             consultant),
        ("deal_structure_implications", consultant),
        ("summary",                     consultant),
        ("key_reasons",                 consultant),
        ("next_steps",                  consultant),
    ]
    for path, owner in distribution:
        r = await assign_section(
            session_id=sid, section_path=path,
            assigned_to=owner, assigned_by=consultant,
        )
        steps.append(StepResult(
            3, "setup", f"assign section {path}",
            "consultant", r.ok, r.reason,
            extra={"path": path, "owner": str(owner)},
        ))

    # =====================================================================
    # PHASE 2 — DRAFTING (W9 + W17)
    # =====================================================================

    # Analyst deepens synergy_estimate.
    r2_synergy = await _stage_and_accept_deepening(
        session_id=sid, firm_id=firm_uuid, section_path="synergy_estimate",
        triggered_by=analyst, accepted_by=analyst,
        deepened_section={
            "revenue_synergies": [
                {"type": "Cross-sell to UK SME pipeline",
                 "magnitude_gbp_m": 6.0,
                 "rationale": "Refined FY25 conversion + average deal size.",
                 "basis_citations": ["claim_a"]},
                {"type": "Upsell to existing top-tier",
                 "magnitude_gbp_m": 1.2,
                 "rationale": "Expanded to premium SLA tier post-deal.",
                 "basis_citations": ["claim_a"]},
            ],
            "cost_synergies": [
                {"type": "Shared dispatch ops",
                 "magnitude_gbp_m": 1.8,
                 "rationale": "Consolidating dispatch under one ops team.",
                 "basis_citations": []},
            ],
        },
        depth_directive="Make the cross-sell + cost-synergy basis explicit.",
    )
    steps.append(StepResult(
        4, "drafting", "analyst.deepen synergy_estimate (W9 -> W19)",
        "analyst", r2_synergy.get("status") == "accepted",
        extra={"status": r2_synergy.get("status")},
    ))
    # Analyst marks synergy_estimate needs_review (W17 status + W18 notify).
    r = await set_section_status(
        session_id=sid, section_path="synergy_estimate",
        status=SectionStatus.NEEDS_REVIEW, actor_id=analyst,
    )
    steps.append(StepResult(
        5, "drafting", "analyst.mark synergy_estimate needs_review",
        "analyst", r.ok, r.reason,
    ))

    # Consultant deepens valuation_range.
    r2_val = await _stage_and_accept_deepening(
        session_id=sid, firm_id=firm_uuid, section_path="valuation_range",
        triggered_by=consultant, accepted_by=consultant,
        deepened_section={
            "low_gbp_m": 95.0, "high_gbp_m": 125.0,
            "method": "DCF (12%/3% WACC/g) + comps median EV/EBITDA",
            "midpoint_rationale": (
                "Refined comp set to UK-only logistics peers; "
                "increased low end on stable EBITDA margins."
            ),
        },
        depth_directive="Tighten comp set + show WACC assumptions.",
    )
    steps.append(StepResult(
        6, "drafting", "consultant.deepen valuation_range (W9 -> W19)",
        "consultant", r2_val.get("status") == "accepted",
        extra={"status": r2_val.get("status")},
    ))

    # =====================================================================
    # PHASE 3 — DISCUSSION (W16 + W18)
    # =====================================================================

    # Consultant comments on synergy_estimate mentioning the analyst.
    syn_root = await create_comment(
        session_id=sid, author_id=consultant,
        anchor_type="section", anchor_ref={"section_path": "synergy_estimate"},
        body=f"@{analyst_slug} solid pipeline math - can you cite the FY25 source?",
        mentioned_user_ids=[str(analyst)],
    )
    steps.append(StepResult(
        7, "discussion", "consultant.comment+mention_analyst",
        "consultant", syn_root.ok, syn_root.reason,
        extra={"comment_id": syn_root.comment_id},
    ))
    captures["synergy_thread_root"] = syn_root.comment_id
    if syn_root.ok and syn_root.comment_id:
        await audit_append_event(
            action="comment.created",
            actor_user_id=str(consultant),
            resource_type="comment",
            resource_id=syn_root.comment_id,
            payload={
                "session_id": ctx["session_id"],
                "anchor_type": "section",
                "anchor_ref": {"section_path": "synergy_estimate"},
                "mention_count": 1,
            },
        )

    # Analyst replies mentioning the partner (partner is now both a
    # thread participant once they post AND mentioned in this reply
    # if we extend — but the partner hasn't posted yet, so they
    # qualify only via mention. Lead (consultant) was the root author
    # so they'll get COMMENT_REPLY. This proves the multi-recipient
    # dispatch without the dedup case (dedup is W17/W18 e2e's
    # specialty); here we just verify W16 thread + W18 fan-out.
    syn_reply = await reply_to_comment(
        parent_comment_id=UUID(syn_root.comment_id or ""),
        author_id=analyst,
        body=f"Will pull the FY25 brief and tag @{partner_slug} for visibility.",
        mentioned_user_ids=[str(partner)],
    )
    steps.append(StepResult(
        8, "discussion", "analyst.reply+mention_partner",
        "analyst", syn_reply.ok, syn_reply.reason,
        extra={"comment_id": syn_reply.comment_id},
    ))
    if syn_reply.ok and syn_reply.comment_id:
        await audit_append_event(
            action="comment.replied",
            actor_user_id=str(analyst),
            resource_type="comment",
            resource_id=syn_reply.comment_id,
            payload={
                "session_id": ctx["session_id"],
                "parent_comment_id": syn_root.comment_id,
                "mention_count": 1,
            },
        )

    # Resolve the thread.
    r = await resolve_thread(UUID(syn_root.comment_id or ""), consultant)
    steps.append(StepResult(
        9, "discussion", "consultant.resolve_synergy_thread",
        "consultant", r.ok, r.reason,
    ))
    if r.ok and syn_root.comment_id:
        await audit_append_event(
            action="comment.resolved",
            actor_user_id=str(consultant),
            resource_type="comment",
            resource_id=syn_root.comment_id,
            payload={"session_id": ctx["session_id"]},
        )

    # =====================================================================
    # PHASE 4 — REVIEW CYCLE (W15 + W18)
    # =====================================================================

    submit1 = await transition_review(
        sid, ReviewAction.SUBMIT_FOR_REVIEW, consultant, reviewer_id=partner,
    )
    steps.append(StepResult(
        10, "review", "consultant.submit_for_review",
        "consultant", submit1.ok, submit1.reason,
        extra={"to_state": submit1.to_state},
    ))

    request_changes = await transition_review(
        sid, ReviewAction.REQUEST_CHANGES, partner,
        structured_feedback=ReviewFeedback(
            overall_note="Strengthen the financial profile basis before approval.",
            severity="blocking",
            section_pointers=[SectionPointer(
                section_path="financial_profile",
                note="Sources for the margin + cash conversion numbers?",
                severity="blocking", resolved=False,
            )],
        ),
    )
    steps.append(StepResult(
        11, "review", "partner.request_changes (blocking on financial_profile)",
        "partner", request_changes.ok, request_changes.reason,
        extra={"review_record_id": request_changes.review_record_id},
    ))
    captures["change_request_record_id"] = request_changes.review_record_id

    # =====================================================================
    # PHASE 5 — ADDRESS + VERSION (W9 + W19)
    # =====================================================================

    # Analyst deepens financial_profile to strengthen sourcing.
    r3_fp = await _stage_and_accept_deepening(
        session_id=sid, firm_id=firm_uuid, section_path="financial_profile",
        triggered_by=analyst, accepted_by=analyst,
        deepened_section={
            "ebitda_margin_pct": 14.5,
            "revenue_growth_3y_cagr_pct": 7.8,
            "free_cash_flow_conversion_pct": 72.0,
            "ebitda_margin_basis": (
                "FY24 audited statements + Q1 FY25 trading update; "
                "WC discipline driving the modest expansion."
            ),
            "fcf_basis": (
                "Capex-light asset model (3PL partnerships) keeps "
                "conversion above 70%; one-off PPA in FY25 H1 noted."
            ),
        },
        depth_directive="Cite the source for every margin + FCF number.",
    )
    steps.append(StepResult(
        12, "address", "analyst.deepen financial_profile (W9 -> W19)",
        "analyst", r3_fp.get("status") == "accepted",
        extra={"status": r3_fp.get("status")},
    ))

    # Consultant resolves the pointer + resubmits.
    await resolve_section_pointer(
        sid, UUID(request_changes.review_record_id or ""), consultant,
        "financial_profile",
    )
    resub = await transition_review(
        sid, ReviewAction.RESUBMIT, consultant, reviewer_id=partner,
    )
    steps.append(StepResult(
        13, "address", "consultant.resolve_pointer + resubmit",
        "consultant", resub.ok, resub.reason,
        extra={"to_state": resub.to_state},
    ))

    # Mark every assigned section done so the W17 coverage map flips
    # ready_to_submit=True (advisory; partner still decides).
    for path, owner in distribution:
        await set_section_status(
            session_id=sid, section_path=path,
            status=SectionStatus.DONE, actor_id=owner,
        )
    cov = await section_coverage(sid)
    captures["coverage_ready_to_submit"] = cov.ready_to_submit

    # =====================================================================
    # PHASE 6 — APPROVE (W15 + W18)
    # =====================================================================

    approve = await transition_review(sid, ReviewAction.APPROVE, partner)
    steps.append(StepResult(
        14, "approve", "partner.approve",
        "partner", approve.ok, approve.reason,
        extra={"to_state": approve.to_state},
    ))

    final_state = await get_review_state(sid)
    captures["final_review_state"] = final_state.get("review_state") if final_state else None

    # =====================================================================
    # PHASE 7 — PROVENANCE (W19)
    # =====================================================================

    versions = await list_versions(sid)
    captures["versions"] = [v.to_dict() for v in versions]
    head = await get_current_version(sid)
    captures["head_version_number"] = head.version_number if head else None

    if versions:
        first_v = min(versions, key=lambda v: v.version_number).version_number
        last_v = max(versions, key=lambda v: v.version_number).version_number
        if first_v != last_v:
            diff = await diff_versions(sid, first_v, last_v)
            captures["diff_v1_to_final"] = diff.to_dict() if diff else None

    steps.append(StepResult(
        15, "provenance", f"version history walk ({len(versions)} versions)",
        "system", bool(versions),
        extra={"version_count": len(versions)},
    ))

    return {"steps": steps, "captures": captures}


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------


async def _read_notifications(sid: UUID) -> list[dict[str, Any]]:
    from db.connection import acquire
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, recipient_id, notification_type, source_ref,
                   actor_id, summary, read, email_status, created_at
              FROM notifications
             WHERE session_id = $1::uuid
             ORDER BY created_at ASC, id ASC
            """,
            sid,
        )
    out = []
    for r in rows:
        sr = r["source_ref"]
        if isinstance(sr, str):
            try:
                sr = json.loads(sr)
            except Exception:
                sr = {}
        out.append({
            "id": str(r["id"]),
            "recipient_id": str(r["recipient_id"]),
            "notification_type": r["notification_type"],
            "source_ref": sr or {},
            "actor_id": str(r["actor_id"]) if r["actor_id"] else None,
            "summary": r["summary"],
            "read": bool(r["read"]),
            "email_status": r["email_status"],
            "created_at": r["created_at"].isoformat(),
        })
    return out


async def _read_audit(sid: UUID) -> list[dict[str, Any]]:
    from db.connection import acquire
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, action, actor_user_id, resource_type, resource_id,
                   payload, created_at
              FROM audit_events
             WHERE (payload->>'session_id' = $1::text
                    OR (resource_type IN ('session','engagement','comment',
                                          'section_assignment','engagement_task',
                                          'section_deepening')
                        AND resource_id = $1::text)
                    OR (resource_type = 'session' AND resource_id = $1::text))
               AND (action LIKE 'engagement.%' OR action LIKE 'section.%'
                    OR action LIKE 'review.%'    OR action LIKE 'comment.%'
                    OR action LIKE 'task.%'      OR action LIKE 'version.%'
                    OR action LIKE 'section_deepening.%')
             ORDER BY id ASC
            """,
            str(sid),
        )
    out = []
    for r in rows:
        payload = r["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        out.append({
            "id": int(r["id"]), "action": r["action"],
            "actor_user_id": str(r["actor_user_id"]) if r["actor_user_id"] else None,
            "resource_type": r["resource_type"], "resource_id": r["resource_id"],
            "payload": payload or {},
            "created_at": r["created_at"].isoformat(),
        })
    return out


# ---------------------------------------------------------------------------
# Headline assertions
# ---------------------------------------------------------------------------


def _headline(
    steps: list[StepResult],
    captures: dict[str, Any],
    notifications: list[dict[str, Any]],
    audit: list[dict[str, Any]],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    out: dict[str, Any] = {}

    # 1. All steps succeeded.
    out["all_steps_pass"] = all(s.ok for s in steps)

    # 2. Final review_state == approved.
    out["final_review_state_approved"] = (
        captures.get("final_review_state") == "approved"
    )

    # 3. Version history coherent: ≥4 versions, monotonic version_numbers,
    # correct change_types present (initial + section_deepening at least),
    # review_state captured per version.
    versions = sorted(
        (v for v in captures.get("versions") or []),
        key=lambda v: int(v["version_number"]),
    )
    out["version_count"] = len(versions)
    out["version_numbers_monotonic"] = (
        len(versions) >= 1
        and [int(v["version_number"]) for v in versions]
            == list(range(1, len(versions) + 1))
    )
    change_types_present = {v["change_type"] for v in versions}
    out["version_change_types"] = sorted(change_types_present)
    out["versions_include_initial_and_deepening"] = (
        "initial" in change_types_present
        and "section_deepening" in change_types_present
    )
    out["versions_have_at_least_4"] = len(versions) >= 4
    out["version_review_state_captured"] = all(
        v.get("review_state_at_version") is not None for v in versions
    )

    # 4. Section ownership + statuses tracked. Coverage's
    # ready_to_submit went True after every section was marked done.
    out["coverage_ready_to_submit_after_addressing"] = bool(
        captures.get("coverage_ready_to_submit")
    )

    # 5. Comments threaded + mentions resolved + notifications delivered.
    mention_recipients = {
        n["recipient_id"] for n in notifications
        if n["notification_type"] == "mention"
    }
    out["mention_notifications_reached_analyst"] = ctx["analyst_id"] in mention_recipients
    out["mention_notifications_reached_partner"] = ctx["partner_id"] in mention_recipients

    # 6. Review cycle gated correctly: submit -> request_changes ->
    # resubmit -> approve all fired with the right recipients.
    types_to_partner = [
        n["notification_type"] for n in notifications
        if n["recipient_id"] == ctx["partner_id"]
    ]
    types_to_consultant = [
        n["notification_type"] for n in notifications
        if n["recipient_id"] == ctx["consultant_id"]
    ]
    out["partner_received_review_requested_x2"] = types_to_partner.count("review_requested") >= 2
    out["consultant_received_changes_requested"] = "changes_requested" in types_to_consultant
    out["consultant_received_review_approved"] = "review_approved" in types_to_consultant

    # 7. Actor never notified for own action; dedup held.
    self_notifs = [
        n for n in notifications
        if n.get("actor_id") and n["actor_id"] == n["recipient_id"]
    ]
    out["actor_never_notified_for_own_action"] = len(self_notifs) == 0
    # Dedup proxy: no recipient has two notifications for the same
    # source_ref.comment_id with different types (the W18 multi-path
    # dedup contract).
    by_recipient_source: dict[tuple[str, str], list[str]] = {}
    for n in notifications:
        comment_id = (n["source_ref"] or {}).get("comment_id")
        if not comment_id:
            continue
        key = (n["recipient_id"], str(comment_id))
        by_recipient_source.setdefault(key, []).append(n["notification_type"])
    dedup_violations = [k for k, types in by_recipient_source.items()
                         if len(types) > 1]
    out["dedup_held_no_multi_type_per_source"] = len(dedup_violations) == 0

    # 8. Audit covers all four event classes + version.
    actions = {a["action"] for a in audit}
    required_prefixes = ["engagement.", "section.", "review.", "comment."]
    coverage = {p: any(a.startswith(p) for a in actions) for p in required_prefixes}
    out["audit_covers_all_collaboration_classes"] = all(coverage.values())
    out["audit_action_prefixes"] = coverage
    out["audit_rows_count"] = len(audit)

    # 9. Diff v1 -> final shows the deepened sections.
    diff = captures.get("diff_v1_to_final")
    if diff:
        modified_paths = [
            c["section_path"] for c in diff.get("section_changes", [])
            if c.get("change") == "modified"
        ]
        out["diff_modified_paths"] = sorted(modified_paths)
        # We deepened synergy_estimate, valuation_range, financial_profile.
        for expected in ("synergy_estimate", "valuation_range", "financial_profile"):
            out[f"diff_includes_{expected}"] = expected in modified_paths
    else:
        out["diff_includes_synergy_estimate"] = False
        out["diff_includes_valuation_range"] = False
        out["diff_includes_financial_profile"] = False

    # 10. Notification volume per user (informational).
    out["notification_count_by_user"] = {
        "consultant": sum(1 for n in notifications if n["recipient_id"] == ctx["consultant_id"]),
        "partner":    sum(1 for n in notifications if n["recipient_id"] == ctx["partner_id"]),
        "analyst":    sum(1 for n in notifications if n["recipient_id"] == ctx["analyst_id"]),
    }

    out["headline_pass"] = all(v for k, v in out.items() if isinstance(v, bool))
    return out


# ---------------------------------------------------------------------------
# Provenance narrative
# ---------------------------------------------------------------------------


def _render_provenance(
    versions: list[dict[str, Any]],
    ctx: dict[str, Any],
    final_state: str | None,
) -> str:
    """Human-readable provenance story — the trust-payoff. Walks
    every version with its change type, author, and review state."""
    if not versions:
        return "No version history captured."
    versions = sorted(versions, key=lambda v: int(v["version_number"]))
    user_name = {
        ctx["consultant_id"]: "the consultant",
        ctx["partner_id"]:    "the partner",
        ctx["analyst_id"]:    "the analyst",
    }

    lines: list[str] = []
    lines.append(
        f"This memo went through {len(versions)} version(s) over the engagement."
    )
    for v in versions:
        n = int(v["version_number"])
        ct = v["change_type"]
        actor = user_name.get(v.get("created_by") or "", "the system")
        ts = (v.get("created_at") or "")[:19].replace("T", " ")
        rs = v.get("review_state_at_version") or "?"
        if ct == "initial":
            lines.append(
                f"  v{n} (initial generation, review_state={rs}, "
                f"by {actor}, at {ts})."
            )
        elif ct == "section_deepening":
            paths = ", ".join(v.get("changed_section_paths") or []) or "—"
            lines.append(
                f"  v{n}: {actor} deepened [{paths}] (review_state={rs}, "
                f"at {ts}). {v.get('change_summary') or ''}"
            )
        elif ct == "review_revert":
            lines.append(
                f"  v{n}: auto-revert from approval, triggered by {actor} "
                f"(review_state={rs}, at {ts})."
            )
        elif ct == "restore":
            lines.append(
                f"  v{n}: {actor} restored a prior version "
                f"(review_state={rs}, at {ts})."
            )
        else:
            lines.append(f"  v{n}: {ct} by {actor} at {ts}.")
    if final_state:
        last = versions[-1]
        lines.append(
            f"The final state is {final_state.upper()} at v{int(last['version_number'])}."
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main_async(args: argparse.Namespace) -> int:
    from db.connection import close_db, init_db
    from core.notifications.email import (
        CaptureEmailAdapter, reset_adapter_for_tests,
    )

    _BENCH_ROOT.mkdir(parents=True, exist_ok=True)
    summary_path = _BENCH_ROOT / "summary.json"

    if args.summary_only:
        if not summary_path.exists():
            print("no previous summary.json. Run without --summary-only first.")
            return 1
        print(summary_path.read_text(encoding="utf-8"))
        return 0

    t0 = time.perf_counter()
    capture = CaptureEmailAdapter()
    reset_adapter_for_tests(capture)

    await init_db()
    try:
        ctx = await _bootstrap()
        print(f"engagement: {ctx['engagement_title']}  session={ctx['session_id']}")
        print(f"  consultant (lead) = {ctx['consultant_email']}")
        print(f"  partner (reviewer)= {ctx['partner_email']}")
        print(f"  analyst (contrib) = {ctx['analyst_email']}")
        print()
        cycle = await _run_cycle(ctx, capture)
        notifications = await _read_notifications(UUID(ctx["session_id"]))
        audit = await _read_audit(UUID(ctx["session_id"]))
    finally:
        await close_db()
    wall = time.perf_counter() - t0

    headline = _headline(cycle["steps"], cycle["captures"], notifications, audit, ctx)
    provenance = _render_provenance(
        cycle["captures"].get("versions") or [],
        ctx,
        cycle["captures"].get("final_review_state"),
    )

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
        "n_notifications": len(notifications),
        "n_audit_rows": len(audit),
        "n_captured_emails": len(capture.captured),
        "headline": headline,
        "headline_pass": bool(headline.get("headline_pass")),
        "provenance_narrative": provenance,
        "steps": [asdict(s) for s in cycle["steps"]],
        "captures": cycle["captures"],
        "notifications": notifications,
        "audit_rows": audit,
    }
    summary_path.write_text(json.dumps(body, indent=2, default=str), encoding="utf-8")

    print("=== STEPS ===")
    for s in cycle["steps"]:
        flag = "PASS" if s.ok else "FAIL"
        print(f"  [{flag}] step={s.step:>2}  {s.phase:<11} {s.label}")
        if not s.ok and s.reason:
            print(f"           reason: {s.reason[:160]}")
    print()
    print("=== HEADLINE ===")
    for k, v in headline.items():
        if isinstance(v, bool):
            print(f"  [{'PASS' if v else 'FAIL'}] {k}")
        elif not isinstance(v, (dict, list)):
            print(f"  {k}: {v}")
        else:
            print(f"  {k}: {v}")
    print()
    print("=== PROVENANCE NARRATIVE ===")
    print(provenance)
    print()
    print(f"notifications={len(notifications)}  audit={len(audit)}  "
          f"captured_emails={len(capture.captured)}  wall={wall:.2f}s")
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
