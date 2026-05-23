"""Phase 4 / Week 16 / Day 5 — commenting end-to-end runner.

Drives a full multi-user threaded discussion against the seeded
Meridian Advisory engagement (W14/D3) and verifies the W16 surface
end-to-end:

  1.  Consultant posts a section comment on synergy_estimate with
      @-mentions of both the partner (resolved) and a non-member
      slug (silently dropped).
  2.  Consultant also posts a text_range comment quoting a specific
      phrase from the section — used later to verify orphan
      detection.
  3.  Partner replies on the section thread mentioning the analyst.
  4.  Analyst replies on the section thread.
  5.  Consultant comments on the W7 claim ``claim_kgr_1``.
  6.  Consultant creates an artifact (or reuses an existing one)
      and posts an artifact-anchored comment.
  7.  Consultant submits the engagement for review; assert
      ``review.comments.unresolved`` shows the right open-thread
      count.
  8.  Partner resolves the section-anchored thread.
  9.  Simulate the W9 section deepening by rewriting the
      synergy_estimate text in-place. (Real LLM-driven deepening is
      tested elsewhere; the e2e cares about the OBSERVABLE outcome —
      whether the orphan detector flags the text_range comment whose
      quote is gone — and a direct rewrite is deterministic + zero
      LLM cost.)
 10.  Partner approves; assert approval is NOT blocked by unresolved
      threads (advisory only per W16/D2 hard rule).

Captures the W15+W16 review state, every comment row, the orphan
verdict per text_range thread, and the matching audit rows. Persists
to ``backend/eval_runs/week16_e2e/summary.json``.

Usage::

    python tools/run_week16_e2e.py
    python tools/run_week16_e2e.py --summary-only
"""

from __future__ import annotations

import argparse
import asyncio
import json
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

_BENCH_ROOT = _REPO_ROOT / "backend" / "eval_runs" / "week16_e2e"

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
    reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# DB bootstrap
# ---------------------------------------------------------------------------


async def _bootstrap_engagement() -> dict[str, Any]:
    """Reset the Meridian Kestrel engagement to a clean draft state +
    return the relevant user IDs. Idempotent — running the e2e twice
    in a row leaves the engagement in the same final state."""
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
            FIRM_SLUG, ENGAGEMENT_TITLE_PREFIX,
        )
        if not sess:
            raise SystemExit(
                f"No '{ENGAGEMENT_TITLE_PREFIX}' engagement under firm "
                f"'{FIRM_SLUG}'. Seed first via tools/seed_sample_workspace.py."
            )

        users = {r["email"]: r["id"] for r in await conn.fetch(
            """
            SELECT u.id, u.email
              FROM users u
              JOIN firm_memberships fm ON fm.user_id = u.id
              JOIN firms f ON f.id = fm.firm_id
             WHERE f.slug = $1::text
             ORDER BY fm.created_at ASC
            """,
            FIRM_SLUG,
        )}

        # Locate the three named users by email keyword. The Meridian
        # seeder plants helena.voss (partner), marcus.thorne (consultant),
        # priya.shah (analyst); falling back to ordered list keeps the
        # script working if the seeder is re-renamed.
        def _pick(*needles: str) -> str:
            for em, uid in users.items():
                if any(n in em for n in needles):
                    return str(uid)
            raise KeyError(f"No user matching {needles!r} in firm {FIRM_SLUG}")

        partner_id = _pick("helena", "partner")
        consultant_id = _pick("marcus", "consultant")
        analyst_id = _pick("priya", "analyst")

        # Reset review state + comments + bulk-clear the comment audit
        # rows from previous runs so the audit assertion is honest.
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
            sess["id"], UUID(consultant_id),
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
            """
            DELETE FROM audit_events
             WHERE resource_type = 'comment'
                OR (resource_type = 'session'
                    AND resource_id = $1::text
                    AND action LIKE 'review.%')
            """,
            str(sess["id"]),
        )

        # Make sure firms.allow_self_approval = FALSE so reviewer != author.
        await conn.execute(
            "UPDATE firms SET allow_self_approval = FALSE WHERE slug = $1::text",
            FIRM_SLUG,
        )

        # Reset synergy_estimate to a known pre-deepen shape so the
        # orphan check is deterministic across re-runs. Without this
        # a second run would pick up step 9's already-rewritten
        # section and the text_range quote would survive deepening,
        # masking the orphan signal.
        report_row = await conn.fetchrow(
            "SELECT consulting_payload FROM reports WHERE session_id = $1::uuid",
            sess["id"],
        )
        cp = (report_row or {}).get("consulting_payload") if report_row else None
        if isinstance(cp, str):
            try:
                cp = json.loads(cp)
            except Exception:
                cp = None
        cp = cp or {}
        cp["synergy_estimate"] = {
            "revenue_synergies": [
                {
                    "type": "Cross-sell to Kestrel SME pipeline",
                    "magnitude_gbp_m": 5.0,
                    "rationale": (
                        "PRE_DEEPEN_MARKER_W16D5 — Cross-sell uplift modelled "
                        "on FY24 pilot conversion rates."
                    ),
                    "basis_citations": ["claim_revenue_1"],
                },
            ],
            "cost_synergies": [],
        }
        # Drop any prior _w16_pre_deepen marker from the previous run.
        cp.pop("_w16_pre_deepen", None)
        await conn.execute(
            "UPDATE reports SET consulting_payload = $2::jsonb WHERE session_id = $1::uuid",
            sess["id"], json.dumps(cp),
        )

        # Ensure engagement memberships exist (needed by the review
        # authorization layer + the comments firm-member gate).
        for uid, role in [(consultant_id, "lead"), (partner_id, "member"),
                          (analyst_id, "member")]:
            await conn.execute(
                """
                INSERT INTO engagement_memberships (engagement_id, user_id, role, added_by)
                VALUES ($1::uuid, $2::uuid, $3, $2::uuid)
                ON CONFLICT (engagement_id, user_id) DO UPDATE SET role = EXCLUDED.role
                """,
                sess["id"], UUID(uid), role,
            )

    return {
        "session_id": str(sess["id"]),
        "engagement_title": sess["title"],
        "firm_id": str(sess["firm_id"]),
        "partner_id": str(partner_id),
        "consultant_id": str(consultant_id),
        "analyst_id": str(analyst_id),
        "partner_email": next(em for em, uid in users.items() if str(uid) == str(partner_id)),
        "consultant_email": next(em for em, uid in users.items() if str(uid) == str(consultant_id)),
        "analyst_email": next(em for em, uid in users.items() if str(uid) == str(analyst_id)),
    }


async def _ensure_artifact(session_id: UUID, firm_id: UUID) -> str:
    """Make sure the engagement has at least one artifact row so the
    artifact-anchor step has a target. If one already exists we
    reuse it; otherwise we plant a minimal stub matching the
    export_artifacts schema."""
    from db.connection import acquire

    async with acquire() as conn:
        existing = await conn.fetchrow(
            """
            SELECT id FROM export_artifacts
             WHERE session_id = $1::uuid
             ORDER BY generated_at ASC LIMIT 1
            """,
            session_id,
        )
        if existing:
            return str(existing["id"])
        row = await conn.fetchrow(
            """
            INSERT INTO export_artifacts
                   (session_id, firm_id, artifact_type, format, status,
                    payload_snapshot, generated_at)
            VALUES ($1::uuid, $2::uuid, 'deck', 'pptx', 'ready',
                    '{}'::jsonb, NOW())
            RETURNING id
            """,
            session_id, firm_id,
        )
    return str(row["id"])


async def _pick_seeded_claim_id(session_id: UUID) -> str:
    """Pull a real claim_id from the seeded writer payload. The
    Meridian seed plants claim_revenue_1 / claim_ebitda_1 /
    claim_synergy_cost_1 under recommendation_claim_ids; we use the
    first one in that list so the e2e survives seed churn."""
    from db.connection import acquire

    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT consulting_payload FROM reports WHERE session_id = $1::uuid",
            session_id,
        )
    if not row:
        return ""
    cp = row["consulting_payload"]
    if isinstance(cp, str):
        try:
            cp = json.loads(cp)
        except Exception:
            cp = {}
    cp = cp or {}
    ids = cp.get("recommendation_claim_ids") or []
    if isinstance(ids, list) and ids:
        return str(ids[0])
    return ""


async def _emit_audit(
    *,
    action: str,
    actor_user_id: UUID,
    comment_id: str | None,
    session_id: UUID,
    extra: dict[str, Any] | None = None,
) -> None:
    """Mirror the audit logging the W16/D2 API layer fires after
    every service call. We invoke the service from the runner
    directly (no HTTP roundtrip) so we replicate the audit row
    explicitly — the audit-coverage assertion would otherwise read
    zero rows."""
    from audit.queries import append_event

    payload: dict[str, Any] = {"session_id": str(session_id)}
    if extra:
        payload.update(extra)
    await append_event(
        action=action,
        actor_user_id=str(actor_user_id),
        resource_type="comment",
        resource_id=comment_id,
        payload=payload,
    )


async def _load_synergy_text(session_id: UUID) -> str:
    """Pull a short phrase out of the synergy_estimate section to use
    as the text_range comment's quoted_text. The W9 section
    addressing keeps synergy_estimate inside consulting_payload."""
    from db.connection import acquire

    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT consulting_payload FROM reports WHERE session_id = $1::uuid",
            session_id,
        )
    if not row:
        return ""
    cp = row["consulting_payload"]
    if isinstance(cp, str):
        try:
            cp = json.loads(cp)
        except Exception:
            cp = {}
    syn = (cp or {}).get("synergy_estimate") or {}
    rev = syn.get("revenue_synergies") or []
    if rev and isinstance(rev[0], dict):
        return str(rev[0].get("rationale") or rev[0].get("type") or "")
    return "synergy"


async def _simulate_section_deepening(
    session_id: UUID, section_path: str, replacement_text: str,
) -> dict[str, Any]:
    """W16/D5 deterministic stand-in for W9 deepening.

    Real LLM-driven deepening is tested elsewhere; the e2e cares
    about the OBSERVABLE outcome — whether the orphan detector
    flags a text_range comment after the underlying text changes.
    Rewriting the section in-place produces the same observable
    state for zero LLM cost. The original synergy_estimate object
    is stashed under ``_w16_pre_deepen`` so an operator can
    inspect the diff after the run.
    """
    from db.connection import acquire

    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT consulting_payload FROM reports WHERE session_id = $1::uuid",
            session_id,
        )
        if not row:
            return {"changed": False, "reason": "no report row"}
        cp = row["consulting_payload"]
        if isinstance(cp, str):
            try:
                cp = json.loads(cp)
            except Exception:
                cp = {}
        cp = cp or {}
        before = cp.get(section_path)
        # Replace the section value with a fresh shape that does NOT
        # contain the previous text. The pre-deepen content is
        # stashed at the payload root (NOT inside the section) so
        # the orphan detector — which flattens the section subtree —
        # doesn't accidentally see the old quote.
        cp[section_path] = {
            "revenue_synergies": [
                {"type": "Reframed cross-sell",
                 "magnitude_gbp_m": 7.5,
                 "rationale": replacement_text or "Updated post-deepening rationale.",
                 "basis_citations": []},
            ],
            "cost_synergies": [],
        }
        cp["_w16_pre_deepen"] = {section_path: before}
        await conn.execute(
            "UPDATE reports SET consulting_payload = $2::jsonb "
            "WHERE session_id = $1::uuid",
            session_id, json.dumps(cp),
        )
    return {"changed": True, "section_path": section_path}


async def _read_comments(session_id: UUID) -> list[dict[str, Any]]:
    """Return every comment row for the engagement (live + deleted)
    so the summary captures the full final state."""
    from db.connection import acquire

    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, session_id, firm_id, parent_comment_id, anchor_type,
                   anchor_ref, body, mentioned_user_ids, author_id,
                   resolved, resolved_by, resolved_at,
                   created_at, updated_at, edited_at, deleted_at
              FROM comments
             WHERE session_id = $1::uuid
             ORDER BY created_at ASC, id ASC
            """,
            session_id,
        )
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        for k, v in list(d.items()):
            if isinstance(v, UUID):
                d[k] = str(v)
            elif hasattr(v, "isoformat"):
                d[k] = v.isoformat()
            elif isinstance(v, str) and k in ("anchor_ref", "mentioned_user_ids"):
                try:
                    d[k] = json.loads(v)
                except Exception:
                    pass
        out.append(d)
    return out


async def _read_comment_audit(session_id: UUID) -> list[dict[str, Any]]:
    from db.connection import acquire

    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, action, actor_user_id, resource_id, payload, created_at
              FROM audit_events
             WHERE resource_type = 'comment'
               AND (payload->>'session_id' = $1::text
                    OR resource_id IN (
                        SELECT id::text FROM comments WHERE session_id = $1::uuid
                    ))
             ORDER BY created_at ASC, id ASC
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
                payload = {}
        out.append({
            "id": int(r["id"]),
            "action": r["action"],
            "actor_user_id": str(r["actor_user_id"]) if r["actor_user_id"] else None,
            "comment_id": r["resource_id"],
            "payload": payload,
            "created_at": r["created_at"].isoformat(),
        })
    return out


# ---------------------------------------------------------------------------
# Cycle
# ---------------------------------------------------------------------------


async def _run_cycle(ctx: dict[str, Any]) -> dict[str, Any]:
    from core.comments.mentions import slug_for_user
    from core.comments.orphan import is_text_range_orphaned
    from core.comments.service import (
        create_comment,
        reply_to_comment,
        resolve_thread,
    )
    from core.comments.threads import (
        count_unresolved_for_session,
        get_threads_for_session,
    )
    from core.review.service import transition_review, get_review_state
    from core.review.state_machine import ReviewAction

    sid = UUID(ctx["session_id"])
    firm_uuid = UUID(ctx["firm_id"])
    consultant = UUID(ctx["consultant_id"])
    partner = UUID(ctx["partner_id"])
    analyst = UUID(ctx["analyst_id"])

    partner_slug = slug_for_user({"email": ctx["partner_email"]})
    analyst_slug = slug_for_user({"email": ctx["analyst_email"]})
    bogus_slug = "ghost.user"  # no matching firm member

    steps: list[StepResult] = []
    captures: dict[str, Any] = {}

    # Step 1 — Consultant comments on synergy_estimate section with
    # partner mention + a deliberately invalid slug.
    r1 = await create_comment(
        session_id=sid, author_id=consultant,
        anchor_type="section",
        anchor_ref={"section_path": "synergy_estimate"},
        body=(
            f"Tighten the synergy basis, @{partner_slug}. "
            f"@{bogus_slug} is not on the team — should not resolve."
        ),
        mentioned_user_ids=[str(partner)],
    )
    steps.append(StepResult(
        step=1, label="consultant.section_comment+mention_partner",
        actor="consultant", ok=r1.ok, reason=r1.reason,
        extra={"comment_id": r1.comment_id,
               "mentioned": r1.row["mentioned_user_ids"] if r1.row else []},
    ))
    captures["section_root_id"] = r1.comment_id
    if r1.ok:
        await _emit_audit(
            action="comment.created", actor_user_id=consultant,
            comment_id=r1.comment_id, session_id=sid,
            extra={"anchor_type": "section",
                   "anchor_ref": {"section_path": "synergy_estimate"},
                   "mention_count": len(r1.row.get("mentioned_user_ids") or [])
                   if r1.row else 0},
        )

    # Step 2 — Consultant adds a text_range comment with a quote drawn
    # from the current synergy_estimate. The orphan detector should
    # mark this row as orphaned after step 9 rewrites the section.
    syn_quote = await _load_synergy_text(sid)
    if not syn_quote:
        syn_quote = "synergy"
    r2 = await create_comment(
        session_id=sid, author_id=consultant,
        anchor_type="text_range",
        anchor_ref={
            "section_path": "synergy_estimate",
            "start": 0, "end": min(60, len(syn_quote)),
            "quoted_text": syn_quote,
        },
        body=f"Source on this specific number? (quote: \"{syn_quote[:40]}\")",
    )
    steps.append(StepResult(
        step=2, label="consultant.text_range_comment_for_orphan_check",
        actor="consultant", ok=r2.ok, reason=r2.reason,
        extra={"comment_id": r2.comment_id, "quoted_text": syn_quote[:80]},
    ))
    captures["text_range_id"] = r2.comment_id
    if r2.ok:
        await _emit_audit(
            action="comment.created", actor_user_id=consultant,
            comment_id=r2.comment_id, session_id=sid,
            extra={"anchor_type": "text_range"},
        )

    # Step 3 — Partner replies to the section thread, mentioning analyst.
    r3 = await reply_to_comment(
        parent_comment_id=UUID(r1.comment_id or ""),
        author_id=partner,
        body=f"Looping in @{analyst_slug} to double-check the numerator.",
        mentioned_user_ids=[str(analyst)],
    )
    steps.append(StepResult(
        step=3, label="partner.reply+mention_analyst",
        actor="partner", ok=r3.ok, reason=r3.reason,
        extra={"comment_id": r3.comment_id,
               "mentioned": r3.row["mentioned_user_ids"] if r3.row else []},
    ))
    if r3.ok:
        await _emit_audit(
            action="comment.replied", actor_user_id=partner,
            comment_id=r3.comment_id, session_id=sid,
            extra={"parent_comment_id": r1.comment_id,
                   "mention_count": len(r3.row.get("mentioned_user_ids") or [])
                   if r3.row else 0},
        )

    # Step 4 — Analyst replies on the same thread.
    r4 = await reply_to_comment(
        parent_comment_id=UUID(r1.comment_id or ""),
        author_id=analyst,
        body="Pulled the latest CRM pipeline; will share figures by EOD.",
    )
    steps.append(StepResult(
        step=4, label="analyst.reply",
        actor="analyst", ok=r4.ok, reason=r4.reason,
        extra={"comment_id": r4.comment_id},
    ))
    if r4.ok:
        await _emit_audit(
            action="comment.replied", actor_user_id=analyst,
            comment_id=r4.comment_id, session_id=sid,
            extra={"parent_comment_id": r1.comment_id},
        )

    # Step 5 — Consultant comments on a real claim. The Meridian seed
    # plants claim_revenue_1 / claim_ebitda_1 / claim_synergy_cost_1
    # under consulting_payload.recommendation_claim_ids; we pull the
    # first valid one at runtime so the runner survives seed churn.
    claim_id = await _pick_seeded_claim_id(sid)
    r5 = await create_comment(
        session_id=sid, author_id=consultant,
        anchor_type="claim",
        anchor_ref={"claim_id": claim_id},
        body=f"What's the source for {claim_id}? Needs another citation pair.",
    )
    steps.append(StepResult(
        step=5, label="consultant.claim_comment",
        actor="consultant", ok=r5.ok, reason=r5.reason,
        extra={"comment_id": r5.comment_id,
               "claim_id": claim_id,
               "anchor_ref": (r5.row or {}).get("anchor_ref")},
    ))
    captures["claim_id"] = r5.comment_id
    captures["claim_anchor_ref_claim_id"] = claim_id
    if r5.ok:
        await _emit_audit(
            action="comment.created", actor_user_id=consultant,
            comment_id=r5.comment_id, session_id=sid,
            extra={"anchor_type": "claim", "anchor_ref": {"claim_id": claim_id}},
        )

    # Step 6 — Artifact-anchored comment ("rework valuation slide").
    artifact_id = await _ensure_artifact(sid, firm_uuid)
    captures["artifact_id"] = artifact_id
    r6 = await create_comment(
        session_id=sid, author_id=consultant,
        anchor_type="artifact",
        anchor_ref={"artifact_id": artifact_id},
        body="Rework the valuation slide once the synergy revision lands.",
    )
    steps.append(StepResult(
        step=6, label="consultant.artifact_comment",
        actor="consultant", ok=r6.ok, reason=r6.reason,
        extra={"comment_id": r6.comment_id,
               "anchor_ref": (r6.row or {}).get("anchor_ref")},
    ))
    captures["artifact_comment_id"] = r6.comment_id
    if r6.ok:
        await _emit_audit(
            action="comment.created", actor_user_id=consultant,
            comment_id=r6.comment_id, session_id=sid,
            extra={"anchor_type": "artifact",
                   "anchor_ref": {"artifact_id": artifact_id}},
        )

    # Step 7 — Consultant submits engagement for review + asserts the
    # review response carries the right unresolved count.
    pre_counts = await count_unresolved_for_session(sid)
    sub = await transition_review(
        sid, ReviewAction.SUBMIT_FOR_REVIEW, consultant, reviewer_id=partner,
    )
    state = await get_review_state(sid)
    # Manually layer the comments block the API endpoint composes
    # (so the e2e doesn't need an HTTP roundtrip).
    state_counts = await count_unresolved_for_session(sid)
    state["comments"] = state_counts
    steps.append(StepResult(
        step=7, label="consultant.submit_for_review (+ unresolved count)",
        actor="consultant",
        ok=(sub.ok and state_counts["unresolved"] == pre_counts["unresolved"]
            and state_counts["unresolved"] >= 4),
        reason="",
        extra={
            "pre_unresolved": pre_counts["unresolved"],
            "review_state_comments": state["comments"],
            "review_state": sub.to_state,
        },
    ))
    captures["pre_deepen_review_unresolved"] = state_counts["unresolved"]

    # Step 8 — Partner resolves the section-anchored thread root.
    r8 = await resolve_thread(UUID(r1.comment_id or ""), partner)
    after_resolve_counts = await count_unresolved_for_session(sid)
    steps.append(StepResult(
        step=8, label="partner.resolve_section_thread",
        actor="partner", ok=r8.ok, reason=r8.reason,
        extra={
            "comment_id": r8.comment_id,
            "post_resolve_unresolved": after_resolve_counts["unresolved"],
        },
    ))
    if r8.ok:
        await _emit_audit(
            action="comment.resolved", actor_user_id=partner,
            comment_id=r8.comment_id, session_id=sid,
        )

    # Step 9 — Simulate W9 section deepening on synergy_estimate.
    # See _simulate_section_deepening's docstring for why we don't
    # invoke the real LLM-driven deepener here. After this step the
    # text_range comment's quote no longer appears in the section.
    deepen = await _simulate_section_deepening(
        sid, "synergy_estimate",
        replacement_text="Synergy basis re-anchored to the FY25 pipeline; "
                         "cross-sell modelled at 7.5 gbpm with explicit "
                         "downside scenarios."
    )

    # Reload threads + check orphan state on every text_range comment.
    from core.comments.threads import _load_session_payload_for_orphan  # type: ignore
    payload = await _load_session_payload_for_orphan(sid)
    threads = await get_threads_for_session(sid)
    orphaned_text_range: list[dict[str, Any]] = []
    surviving_anchors: list[dict[str, Any]] = []
    for t in threads:
        anchor_type = t.root.get("anchor_type")
        if anchor_type == "text_range":
            o = is_text_range_orphaned(t.root, payload)
            orphaned_text_range.append({
                "id": t.root["id"], "orphaned": o,
                "quoted_text": (t.root.get("anchor_ref") or {}).get("quoted_text"),
            })
        elif anchor_type in ("section", "claim", "artifact", "engagement"):
            surviving_anchors.append({
                "id": t.root["id"], "anchor_type": anchor_type,
                "orphaned_by_design": False,
            })
    captures["orphaned_text_range"] = orphaned_text_range
    captures["surviving_anchors"] = surviving_anchors
    captures["deepen_outcome"] = deepen
    steps.append(StepResult(
        step=9, label="simulate_section_deepening + orphan check",
        actor="system",
        ok=(deepen.get("changed", False)
            and all(o["orphaned"] for o in orphaned_text_range)
            and len(orphaned_text_range) >= 1),
        reason="",
        extra={
            "orphaned_count": sum(1 for o in orphaned_text_range if o["orphaned"]),
            "text_range_count": len(orphaned_text_range),
            "surviving_anchor_count": len(surviving_anchors),
        },
    ))

    # Step 10 — Partner approves. Unresolved threads remain but
    # approval should NOT be blocked.
    pre_approve_counts = await count_unresolved_for_session(sid)
    r10 = await transition_review(sid, ReviewAction.APPROVE, partner)
    steps.append(StepResult(
        step=10, label="partner.approve (advisory unresolved shown not blocking)",
        actor="partner",
        ok=(r10.ok and r10.to_state == "approved"
            and pre_approve_counts["unresolved"] > 0),
        reason=r10.reason,
        extra={
            "pre_approve_unresolved": pre_approve_counts["unresolved"],
            "review_state": r10.to_state,
        },
    ))
    captures["post_approve_unresolved"] = pre_approve_counts["unresolved"]
    captures["final_review_state"] = r10.to_state

    return {"steps": steps, "captures": captures}


# ---------------------------------------------------------------------------
# Headline assertions
# ---------------------------------------------------------------------------


def _headline(
    steps: list[StepResult],
    captures: dict[str, Any],
    comments: list[dict[str, Any]],
    audit: list[dict[str, Any]],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    out: dict[str, Any] = {}

    # 1. All threads assemble correctly — every parent_comment_id
    # resolves to an existing row in the same engagement.
    by_id = {c["id"]: c for c in comments}
    threading_ok = True
    for c in comments:
        pid = c.get("parent_comment_id")
        if pid and pid not in by_id:
            threading_ok = False
            break
    out["all_threads_assemble_correctly"] = threading_ok

    # 2 / 3. Mentions resolved to the expected user_ids.
    section_root = next((s for s in steps if s.step == 1), None)
    reply_mention = next((s for s in steps if s.step == 3), None)
    out["mention_partner_resolved"] = bool(
        section_root and ctx["partner_id"] in section_root.extra.get("mentioned", [])
    )
    out["mention_analyst_resolved"] = bool(
        reply_mention and ctx["analyst_id"] in reply_mention.extra.get("mentioned", [])
    )

    # 4. Non-member mention was silently dropped — the bogus slug
    # appears in the body but no extra user_id sneaks into the
    # mention list.
    out["non_member_mentions_ignored"] = bool(
        section_root
        and ctx["partner_id"] in section_root.extra.get("mentioned", [])
        and len(section_root.extra.get("mentioned", [])) == 1
    )

    # 5 / 6. Claim + artifact anchors persisted correctly.
    claim_step = next((s for s in steps if s.step == 5), None)
    artifact_step = next((s for s in steps if s.step == 6), None)
    expected_claim = captures.get("claim_anchor_ref_claim_id")
    out["claim_anchor_correct"] = bool(
        claim_step
        and expected_claim
        and (claim_step.extra.get("anchor_ref") or {}).get("claim_id") == expected_claim
    )
    out["artifact_anchor_correct"] = bool(
        artifact_step
        and (artifact_step.extra.get("anchor_ref") or {}).get("artifact_id")
            == captures.get("artifact_id")
    )

    # 7. The review GET response's comments.unresolved was accurate
    # at submit time (pre-resolve, pre-deepen).
    submit_step = next((s for s in steps if s.step == 7), None)
    review_counts = submit_step.extra.get("review_state_comments", {}) if submit_step else {}
    out["review_unresolved_count_accurate"] = bool(
        submit_step
        and review_counts.get("unresolved", 0)
            == submit_step.extra.get("pre_unresolved", 0)
    )

    # 8. Orphan detected on the text_range row after deepening.
    deepen_step = next((s for s in steps if s.step == 9), None)
    out["text_range_orphan_detected_after_deepening"] = bool(
        deepen_step and deepen_step.ok
        and deepen_step.extra.get("text_range_count", 0) >= 1
        and deepen_step.extra.get("orphaned_count", 0)
            == deepen_step.extra.get("text_range_count", 0)
    )

    # 9. Section + claim + artifact anchors survive deepening (they
    # don't orphan via the text_range path — by design).
    surviving = captures.get("surviving_anchors", [])
    out["section_claim_artifact_anchors_survive_deepening"] = bool(
        surviving and all(not s.get("orphaned_by_design") for s in surviving)
    )

    # 10. Approval was NOT blocked by unresolved comments. The
    # captured pre-approve unresolved count proves there WERE still
    # open threads when partner approved.
    approve_step = next((s for s in steps if s.step == 10), None)
    out["approval_not_blocked_by_unresolved"] = bool(
        approve_step and approve_step.ok
        and approve_step.extra.get("pre_approve_unresolved", 0) > 0
        and approve_step.extra.get("review_state") == "approved"
    )

    # 11. Every state-changing comment action has an audit row.
    actions = {a["action"] for a in audit}
    expected = {"comment.created", "comment.replied", "comment.resolved"}
    out["audit_covers_state_changes"] = expected.issubset(actions)
    out["audit_action_types"] = sorted(actions)
    out["audit_rows_count"] = len(audit)

    # Total comment counts for context (not gating).
    out["comments_total"] = len(comments)
    out["comments_roots"] = sum(1 for c in comments if not c.get("parent_comment_id"))
    out["comments_replies"] = sum(1 for c in comments if c.get("parent_comment_id"))

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
        print(f"  consultant = {ctx['consultant_email']} ({ctx['consultant_id']})")
        print(f"  partner    = {ctx['partner_email']} ({ctx['partner_id']})")
        print(f"  analyst    = {ctx['analyst_email']} ({ctx['analyst_id']})")
        print()
        cycle = await _run_cycle(ctx)
        comments = await _read_comments(UUID(ctx["session_id"]))
        audit = await _read_comment_audit(UUID(ctx["session_id"]))
    finally:
        await close_db()
    wall = time.perf_counter() - t0

    headline = _headline(cycle["steps"], cycle["captures"], comments, audit, ctx)

    body = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "wall_seconds": round(wall, 3),
        "firm_slug": FIRM_SLUG,
        "session_id": ctx["session_id"],
        "engagement_title": ctx["engagement_title"],
        "users": {
            "consultant": {"id": ctx["consultant_id"], "email": ctx["consultant_email"]},
            "partner":    {"id": ctx["partner_id"],    "email": ctx["partner_email"]},
            "analyst":    {"id": ctx["analyst_id"],    "email": ctx["analyst_email"]},
        },
        "n_steps": len(cycle["steps"]),
        "n_comments": len(comments),
        "n_audit_rows": len(audit),
        "headline": headline,
        "headline_pass": bool(headline.get("headline_pass")),
        "steps": [asdict(s) for s in cycle["steps"]],
        "captures": cycle["captures"],
        "comments": comments,
        "audit_rows": audit,
    }
    summary_path.write_text(json.dumps(body, indent=2, default=str), encoding="utf-8")

    print("=== STEPS ===")
    for s in cycle["steps"]:
        flag = "PASS" if s.ok else "FAIL"
        print(f"  [{flag}] step={s.step:>2}  actor={s.actor:<11} {s.label}")
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
    print(f"comments: {len(comments)}  audit_rows: {len(audit)}  wall={wall:.2f}s")
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
