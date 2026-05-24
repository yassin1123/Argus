"""Phase 4 / Week 18 / Day 5 — notifications end-to-end runner.

Drives the full notification flow against the seeded Meridian
Kestrel engagement: actions across W15/16/17 generate
notifications for the right people through the right channels,
respecting preferences and dedup.

The cycle (8 steps):

  1.  Lead assigns analyst to synergy_estimate
        → analyst gets SECTION_ASSIGNED in-app, email skipped
          (section_assigned default is in-app only).
  2.  Lead posts a section comment mentioning the partner
        → partner gets MENTION + captured email.
  3.  Analyst replies on the lead's root comment
        → lead + partner (prior participants) get COMMENT_REPLY.
          Analyst (actor) excluded.
  4.  Partner replies on the same thread mentioning the analyst
        → analyst is now BOTH a prior participant AND mentioned;
          dedup_batch picks MENTION (higher priority) → analyst
          has exactly ONE notification from this event.
          Lead (still a participant, not mentioned) gets
          COMMENT_REPLY. Partner (actor) excluded.
  5.  Lead submits engagement for review (partner is reviewer)
        → partner gets REVIEW_REQUESTED + captured email.
  6.  Partner requests changes
        → lead gets CHANGES_REQUESTED + captured email.
  7.  Lead resolves the section pointer + resubmits
        → partner gets a second REVIEW_REQUESTED + email.
  8.  Partner approves
        → lead gets REVIEW_APPROVED + captured email.

Captures: every notification row + every captured email +
dedup confirmation. Saves to
``backend/eval_runs/week18_e2e/summary.json``.

Usage::

    python tools/run_week18_e2e.py
    python tools/run_week18_e2e.py --summary-only
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
os.environ.setdefault("ARGUS_EMAIL_ADAPTER", "capture")
os.environ.setdefault("ARGUS_BASE_URL", "https://argus.example.com")

_BENCH_ROOT = _REPO_ROOT / "backend" / "eval_runs" / "week18_e2e"

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
            raise SystemExit(f"Seed Meridian first ({FIRM_SLUG}).")

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

        # Reset every state surface for a deterministic run.
        await conn.execute(
            """
            UPDATE sessions SET review_state='draft',
                                review_assigned_to=$2::uuid,
                                submitted_at=NULL, submitted_by=NULL,
                                approved_at=NULL, approved_by=NULL,
                                created_by_user_id=$3::uuid,
                                updated_at=NOW()
             WHERE id=$1::uuid
            """,
            sess["id"], UUID(partner), UUID(consultant),
        )
        for sql in [
            "DELETE FROM notifications WHERE session_id = $1::uuid",
            "DELETE FROM review_records WHERE session_id = $1::uuid",
            "DELETE FROM comments WHERE session_id = $1::uuid",
            "DELETE FROM section_assignments WHERE session_id = $1::uuid",
            "DELETE FROM engagement_memberships WHERE engagement_id = $1::uuid",
        ]:
            await conn.execute(sql, sess["id"])

        # Re-seat consultant as the lead.
        await conn.execute(
            """
            INSERT INTO engagement_memberships (engagement_id, user_id, role, added_by)
            VALUES ($1::uuid, $2::uuid, 'lead', $2::uuid)
            """,
            sess["id"], UUID(consultant),
        )

        # Pre-populate the section_assignments payload guard (sec
        # validation reads reports.consulting_payload; we install
        # synergy_estimate so the W17/D2 assign_section validation
        # passes consistently).
        cp_row = await conn.fetchrow(
            "SELECT consulting_payload FROM reports WHERE session_id = $1::uuid",
            sess["id"],
        )
        cp = cp_row["consulting_payload"] if cp_row else None
        if isinstance(cp, str):
            try:
                cp = json.loads(cp)
            except Exception:
                cp = None
        cp = cp or {}
        if "synergy_estimate" not in cp:
            cp["synergy_estimate"] = {"revenue_synergies": []}
            await conn.execute(
                "UPDATE reports SET consulting_payload = $2::jsonb WHERE session_id = $1::uuid",
                sess["id"], json.dumps(cp),
            )

        # Notification preferences (per spec):
        #  - Partner: mention email ON (matches default; set
        #    explicitly so we can prove the preference path runs).
        #  - Analyst: section_assigned email OFF (matches default;
        #    set explicitly).
        await conn.execute(
            "DELETE FROM notification_preferences WHERE user_id = ANY($1::uuid[])",
            [UUID(consultant), UUID(partner), UUID(analyst)],
        )
        await conn.execute(
            """
            INSERT INTO notification_preferences
                (user_id, notification_type, in_app, email)
            VALUES ($1::uuid, 'mention', TRUE, TRUE)
            """,
            UUID(partner),
        )
        await conn.execute(
            """
            INSERT INTO notification_preferences
                (user_id, notification_type, in_app, email)
            VALUES ($1::uuid, 'section_assigned', TRUE, FALSE)
            """,
            UUID(analyst),
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
# Cycle
# ---------------------------------------------------------------------------


async def _run_cycle(ctx: dict[str, Any], capture) -> dict[str, Any]:
    from core.collaboration.membership import assign_member
    from core.collaboration.roles import EngagementRole
    from core.collaboration.section_assignments import assign_section
    from core.comments.mentions import slug_for_user
    from core.comments.service import create_comment, reply_to_comment
    from core.review.feedback import ReviewFeedback, SectionPointer
    from core.review.service import (
        resolve_section_pointer, transition_review,
    )
    from core.review.state_machine import ReviewAction

    sid = UUID(ctx["session_id"])
    firm_uuid = UUID(ctx["firm_id"])
    consultant = UUID(ctx["consultant_id"])
    partner = UUID(ctx["partner_id"])
    analyst = UUID(ctx["analyst_id"])
    partner_slug = slug_for_user({"email": ctx["partner_email"]})
    analyst_slug = slug_for_user({"email": ctx["analyst_email"]})

    steps: list[StepResult] = []
    captures: dict[str, Any] = {}

    # Both contributors need to be on the engagement before any
    # mention / section-assign can target them.
    await assign_member(
        session_id=sid, user_id=analyst, role=EngagementRole.CONTRIBUTOR,
        assigned_by=consultant,
    )
    await assign_member(
        session_id=sid, user_id=partner, role=EngagementRole.REVIEWER,
        assigned_by=consultant,
    )
    # Clear notifications generated by the seeding assigns so the
    # e2e counts only the in-cycle events.
    from db.connection import acquire
    async with acquire() as conn:
        await conn.execute(
            "DELETE FROM notifications WHERE session_id = $1::uuid", sid,
        )
    capture.clear()

    # Step 1 — Lead assigns analyst to synergy_estimate.
    r1 = await assign_section(
        session_id=sid, section_path="synergy_estimate",
        assigned_to=analyst, assigned_by=consultant,
    )
    steps.append(StepResult(
        step=1, label="lead.assign_section.synergy=analyst",
        actor="lead", ok=r1.ok, reason=r1.reason,
        extra={"assignment_id": r1.assignment.id if r1.assignment else None},
    ))

    # Step 2 — Lead posts root comment mentioning partner.
    r2 = await create_comment(
        session_id=sid, author_id=consultant,
        anchor_type="section",
        anchor_ref={"section_path": "synergy_estimate"},
        body=f"@{partner_slug} the synergy basis looks light - second pair of eyes?",
        mentioned_user_ids=[str(partner)],
    )
    steps.append(StepResult(
        step=2, label="lead.section_comment+mention_partner",
        actor="lead", ok=r2.ok, reason=r2.reason,
        extra={"comment_id": r2.comment_id},
    ))
    captures["root_comment_id"] = r2.comment_id

    # Step 3 — Analyst replies on the root (no mention).
    r3 = await reply_to_comment(
        parent_comment_id=UUID(r2.comment_id or ""),
        author_id=analyst,
        body="Pulling FY24 conversion rates now.",
    )
    steps.append(StepResult(
        step=3, label="analyst.reply (no mention)",
        actor="analyst", ok=r3.ok, reason=r3.reason,
        extra={"comment_id": r3.comment_id},
    ))

    # Step 4 — Partner replies mentioning the analyst. Analyst is
    # now a prior participant AND mentioned → dedup case.
    r4 = await reply_to_comment(
        parent_comment_id=UUID(r2.comment_id or ""),
        author_id=partner,
        body=f"@{analyst_slug} can you confirm the pipeline assumption?",
        mentioned_user_ids=[str(analyst)],
    )
    steps.append(StepResult(
        step=4, label="partner.reply+mention_analyst (DEDUP CASE)",
        actor="partner", ok=r4.ok, reason=r4.reason,
        extra={"comment_id": r4.comment_id},
    ))
    captures["dedup_comment_id"] = r4.comment_id

    # Step 5 — Lead submits for review.
    r5 = await transition_review(
        sid, ReviewAction.SUBMIT_FOR_REVIEW, consultant, reviewer_id=partner,
    )
    steps.append(StepResult(
        step=5, label="lead.submit_for_review",
        actor="lead", ok=r5.ok, reason=r5.reason,
        extra={"to_state": r5.to_state, "review_record_id": r5.review_record_id},
    ))

    # Step 6 — Partner requests changes.
    r6 = await transition_review(
        sid, ReviewAction.REQUEST_CHANGES, partner,
        structured_feedback=ReviewFeedback(
            overall_note="Tighten the cross-sell basis.",
            severity="blocking",
            section_pointers=[SectionPointer(
                section_path="synergy_estimate",
                note="Source the conversion rate.",
                severity="blocking", resolved=False,
            )],
        ),
    )
    steps.append(StepResult(
        step=6, label="partner.request_changes",
        actor="partner", ok=r6.ok, reason=r6.reason,
        extra={"review_record_id": r6.review_record_id},
    ))
    captures["change_request_id"] = r6.review_record_id

    # Step 7 — Lead resolves + resubmits.
    await resolve_section_pointer(
        sid, UUID(r6.review_record_id or ""), consultant, "synergy_estimate",
    )
    r7 = await transition_review(
        sid, ReviewAction.RESUBMIT, consultant, reviewer_id=partner,
    )
    steps.append(StepResult(
        step=7, label="lead.resubmit (after resolving pointer)",
        actor="lead", ok=r7.ok, reason=r7.reason,
        extra={"to_state": r7.to_state},
    ))

    # Step 8 — Partner approves.
    r8 = await transition_review(sid, ReviewAction.APPROVE, partner)
    steps.append(StepResult(
        step=8, label="partner.approve",
        actor="partner", ok=r8.ok, reason=r8.reason,
        extra={"to_state": r8.to_state},
    ))

    return {"steps": steps, "captures": captures}


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------


async def _read_notifications(session_id: UUID) -> list[dict[str, Any]]:
    from db.connection import acquire

    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, recipient_id, firm_id, notification_type,
                   session_id, source_ref, actor_id, summary,
                   read, read_at, created_at, email_status
              FROM notifications
             WHERE session_id = $1::uuid
             ORDER BY created_at ASC, id ASC
            """,
            session_id,
        )
    out: list[dict[str, Any]] = []
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
            "firm_id": str(r["firm_id"]),
            "notification_type": str(r["notification_type"]),
            "session_id": str(r["session_id"]) if r["session_id"] else None,
            "source_ref": sr or {},
            "actor_id": str(r["actor_id"]) if r["actor_id"] else None,
            "summary": str(r["summary"]),
            "read": bool(r["read"]),
            "created_at": r["created_at"].isoformat(),
            "email_status": str(r["email_status"]),
        })
    return out


# ---------------------------------------------------------------------------
# Headline
# ---------------------------------------------------------------------------


def _headline(
    steps: list[StepResult],
    captures: dict[str, Any],
    notifications: list[dict[str, Any]],
    captured_emails: list[dict[str, Any]],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    out: dict[str, Any] = {}

    # 1. All eight steps succeeded.
    out["all_steps_pass"] = all(s.ok for s in steps)

    # 2. Actor never notified for own action — check each notif's
    # actor_id != recipient_id.
    actor_self_notifs = [
        n for n in notifications
        if n.get("actor_id") and n["actor_id"] == n["recipient_id"]
    ]
    out["actor_never_notified_for_own_action"] = len(actor_self_notifs) == 0

    # 3. Dedup — analyst's notification from step 4's reply is
    # exactly one row with notification_type='mention'.
    dedup_cid = captures.get("dedup_comment_id")
    analyst_from_dedup = [
        n for n in notifications
        if n["recipient_id"] == ctx["analyst_id"]
        and n["source_ref"].get("comment_id") == dedup_cid
    ]
    out["dedup_one_notification_per_recipient_per_event"] = len(analyst_from_dedup) == 1
    out["dedup_winner_is_mention_over_comment_reply"] = (
        len(analyst_from_dedup) == 1
        and analyst_from_dedup[0]["notification_type"] == "mention"
    )

    # 4. Preferences — analyst's SECTION_ASSIGNED has email_status='skipped'.
    section_assigned_for_analyst = [
        n for n in notifications
        if n["recipient_id"] == ctx["analyst_id"]
        and n["notification_type"] == "section_assigned"
    ]
    out["analyst_section_assigned_email_skipped"] = bool(
        section_assigned_for_analyst
        and all(n["email_status"] == "skipped" for n in section_assigned_for_analyst)
    )

    # 5. Partner's MENTION row has email_status='sent' AND there's
    # a captured email to the partner.
    partner_mentions = [
        n for n in notifications
        if n["recipient_id"] == ctx["partner_id"]
        and n["notification_type"] == "mention"
    ]
    partner_mention_email_sent = bool(
        partner_mentions
        and all(n["email_status"] == "sent" for n in partner_mentions)
    )
    partner_captured = [
        e for e in captured_emails if e["to_email"] == ctx["partner_email"]
    ]
    out["partner_mention_email_captured"] = (
        partner_mention_email_sent and len(partner_captured) > 0
    )

    # 6. Captured emails carry firm branding + a "View in Argus" link.
    for e in captured_emails:
        assert "View in Argus" in e["html_body"], \
            f"missing 'View in Argus' in {e['subject']}"
    out["captured_emails_have_branding_and_deeplink"] = all(
        ("argus.example.com" in e["html_body"])
        and ("Meridian" in e["html_body"] or "MERIDIAN" in e["html_body"].upper())
        for e in captured_emails
    )

    # 7. email_status matches preference for every row:
    #    pref-email-on  → email_status in ('sent','failed')
    #    pref-email-off → email_status == 'skipped'
    pref_matrix = {
        ("partner", "mention"): True,             # explicit pref on
        ("analyst", "section_assigned"): False,   # explicit pref off
    }
    pref_violations = []
    for n in notifications:
        recipient = (
            "lead" if n["recipient_id"] == ctx["consultant_id"]
            else "partner" if n["recipient_id"] == ctx["partner_id"]
            else "analyst" if n["recipient_id"] == ctx["analyst_id"]
            else "unknown"
        )
        key = (recipient, n["notification_type"])
        if key in pref_matrix:
            email_on = pref_matrix[key]
            if email_on and n["email_status"] not in ("sent", "failed"):
                pref_violations.append({"key": key, "got": n["email_status"]})
            if not email_on and n["email_status"] != "skipped":
                pref_violations.append({"key": key, "got": n["email_status"]})
    out["email_status_matches_preference"] = len(pref_violations) == 0
    out["preference_violations"] = pref_violations

    # 8. Deep-links resolve — every notification has the source_ref
    # fields its type needs (so deepLink.ts produces a non-fallback URL).
    def _has_deep_target(n: dict[str, Any]) -> bool:
        nt = n["notification_type"]
        sref = n["source_ref"] or {}
        if nt in ("mention", "comment_reply"):
            return bool(sref.get("comment_id"))
        if nt in ("section_assigned", "section_needs_review"):
            return bool(sref.get("section_path"))
        if nt in ("review_requested", "changes_requested", "review_approved"):
            return bool(n["session_id"])
        if nt == "task_assigned":
            return bool(sref.get("task_id"))
        if nt == "engagement_assigned":
            return bool(n["session_id"])
        return True
    out["every_notification_has_deeplink_target"] = all(
        _has_deep_target(n) for n in notifications
    )

    # 9. Review chain — REVIEW_REQUESTED for partner (×2 — one per
    # submit + one per resubmit), CHANGES_REQUESTED + REVIEW_APPROVED
    # for the consultant.
    types_for_partner = [
        n["notification_type"] for n in notifications
        if n["recipient_id"] == ctx["partner_id"]
    ]
    types_for_consultant = [
        n["notification_type"] for n in notifications
        if n["recipient_id"] == ctx["consultant_id"]
    ]
    out["partner_review_requested_count"] = types_for_partner.count("review_requested")
    out["consultant_changes_requested_count"] = types_for_consultant.count("changes_requested")
    out["consultant_review_approved_count"] = types_for_consultant.count("review_approved")
    out["review_chain_complete"] = (
        types_for_partner.count("review_requested") >= 2
        and types_for_consultant.count("changes_requested") >= 1
        and types_for_consultant.count("review_approved") >= 1
    )

    # 10. Notification volume per user (informational).
    out["notification_count_by_user"] = {
        "lead": sum(1 for n in notifications if n["recipient_id"] == ctx["consultant_id"]),
        "partner": sum(1 for n in notifications if n["recipient_id"] == ctx["partner_id"]),
        "analyst": sum(1 for n in notifications if n["recipient_id"] == ctx["analyst_id"]),
    }
    out["captured_email_count"] = len(captured_emails)

    out["headline_pass"] = all(v for k, v in out.items() if isinstance(v, bool))
    return out


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
    finally:
        await close_db()
    wall = time.perf_counter() - t0

    captured = [
        {
            "to_email": e.to_email,
            "subject": e.subject,
            "html_body": e.html_body,
            "text_body": e.text_body,
            "notification_id": e.extra.get("notification_id") if e.extra else None,
            "notification_type": e.extra.get("notification_type") if e.extra else None,
        }
        for e in capture.captured
    ]

    headline = _headline(
        cycle["steps"], cycle["captures"], notifications, captured, ctx,
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
        "n_captured_emails": len(captured),
        "headline": headline,
        "headline_pass": bool(headline.get("headline_pass")),
        "steps": [asdict(s) for s in cycle["steps"]],
        "captures": cycle["captures"],
        "notifications": notifications,
        "captured_emails": [
            # Keep summary compact — drop the full HTML body but
            # preserve subject + recipient + a snippet for diffing.
            {**e, "html_body": e["html_body"][:200] + "..."
                                  if len(e["html_body"]) > 200 else e["html_body"],
                  "text_body": e["text_body"][:200]}
            for e in captured
        ],
    }
    summary_path.write_text(json.dumps(body, indent=2, default=str), encoding="utf-8")

    print("=== STEPS ===")
    for s in cycle["steps"]:
        flag = "PASS" if s.ok else "FAIL"
        print(f"  [{flag}] step={s.step:>2}  actor={s.actor:<10} {s.label}")
        if not s.ok and s.reason:
            print(f"           reason: {s.reason[:160]}")
    print()
    print("=== NOTIFICATIONS ({} total, {} captured emails) ===".format(
        len(notifications), len(captured),
    ))
    for n in notifications:
        recipient = (
            "lead" if n["recipient_id"] == ctx["consultant_id"]
            else "partner" if n["recipient_id"] == ctx["partner_id"]
            else "analyst" if n["recipient_id"] == ctx["analyst_id"]
            else "?"
        )
        print(f"  -> {recipient:8} {n['notification_type']:22} "
              f"email={n['email_status']:8} {n['summary'][:60]}")
    print()
    print("=== HEADLINE ===")
    for k, v in headline.items():
        if isinstance(v, bool):
            print(f"  [{'PASS' if v else 'FAIL'}] {k}")
        elif not isinstance(v, (dict, list)):
            print(f"  {k}: {v}")
        elif isinstance(v, dict):
            print(f"  {k}: {v}")
    print()
    print(f"wall={wall:.2f}s   summary: {summary_path}")
    return 0 if headline.get("headline_pass") else 1


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--summary-only", action="store_true")
    return p.parse_args()


def main() -> None:
    sys.exit(asyncio.run(main_async(_parse_args())))


if __name__ == "__main__":
    main()
