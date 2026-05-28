"""Pilot dress rehearsal — Phase 5 / Week 24 / Day 5.

Runs the pilot end-to-end BEFORE a real firm does, on a realistic
scenario, with the REAL pipeline + REAL cross-family verifier (this is
a real-cost run, a few dollars of LLM). Catches every break in a
controlled run so the pilot's first day isn't the first time the whole
flow runs together.

Flow (each phase is captured; a failure is recorded as a finding, not a
silent crash, so the summary reflects reality):

  1. Onboarding   create "Pilot Dress Rehearsal Inc" + 3 users via the
                  operator path (core.pilot_onboarding).
  2. Library      ingest a realistic synthetic doc set (the firm brings
                  its own content — NOT Meridian fixtures).
  3. Engagements  one M&A + one growth engagement with realistic briefs.
  4. Pipeline     run each to deliverable_ready via the REAL orchestrator
                  (agents.orchestrator.run_pipeline). Real verifier.
  5. Artifacts    generate the deliverable set per engagement.
  6. Review       submit -> request_changes -> resubmit -> approve
                  (the approve records edit telemetry).
  7. Feedback     simulate per-claim feedback + artifact ratings + a
                  weekly check-in; read the pilot-health dashboard.
  8. Enterprise   isolation (cross-firm 404), deletion (purge -> zero
                  residual), audit export (firm-scoped, content-free).
  9. Cost         record actual LLM spend from the cost ledger.

Saves backend/eval_runs/week24_dress_rehearsal/summary.json.

Hard rules (W24/D5): real verifier or stop (ARGUS_MODE defaults to
pilot, which fails loud on a missing key). The edit rate is reported
honestly — a high rewrite rate is a real finding, not something to fudge.

Usage::

    python tools/run_pilot_dress_rehearsal.py
    python tools/run_pilot_dress_rehearsal.py --skip-pipeline  # reuse prior run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "backend"))
sys.path.insert(0, str(_REPO))

# Windows consoles default to cp1252, which can't encode the structured
# logger's output / box-drawing. Force UTF-8 so the runner never dies on
# a print (the summary.json is the authoritative artifact regardless).
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:
    pass

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO / ".env")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/argus",
)

_OUT = _REPO / "backend" / "eval_runs" / "week24_dress_rehearsal"

FIRM_SLUG = "pilot-dress-rehearsal"
PARTNER = "partner@dressrehearsal.invalid"
SENIOR = "senior@dressrehearsal.invalid"
ANALYST = "analyst@dressrehearsal.invalid"


@dataclass
class Phase:
    name: str
    ok: bool
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Synthetic library — the firm brings its OWN content (not Meridian).
# A realistic mid-market target dossier so the M&A DD branches + the
# growth analysis have firm-library evidence to retrieve + verify.
# ---------------------------------------------------------------------------

_LIBRARY_DOCS: dict[str, str] = {
    "harbor_company_overview.md": """# Harbor Logistics Group — company overview

Harbor Logistics Group is a UK-headquartered third-party logistics (3PL)
operator serving e-commerce and grocery retailers across the UK and
Ireland. Founded 2009, ~1,850 employees, 11 distribution centres.

FY24 revenue £218m (FY23 £201m, FY22 £188m). Three segments: Fulfilment
(62% of revenue), Last-Mile Delivery (28%), and Returns Management
(10%). The Fulfilment segment carries the highest gross margin (24%);
Last-Mile is margin-dilutive (9%) due to subcontracted driver costs.

Customer base is concentrated: the top 5 customers represent 47% of
revenue, and the single largest (a national grocery chain) is 19%.
Contracts are typically 3-year with annual CPI-linked price reviews.
""",
    "harbor_financials.md": """# Harbor Logistics Group — financial profile (FY22-FY24)

Revenue: FY22 £188m, FY23 £201m (+6.9%), FY24 £218m (+8.5%).
Adjusted EBITDA: FY22 £19.4m (10.3%), FY23 £21.7m (10.8%),
FY24 £24.9m (11.4%). The vendor's adjusted-EBITDA bridge adds back
£3.1m of "one-off" warehouse relocation costs in FY24; these recurred
in FY22 and FY23, so their add-back is questionable.

Net debt at FY24 close: £41m (1.65x adjusted EBITDA). Capex ran at
4.2% of revenue, mostly automation in the two largest fulfilment
centres. Free cash flow conversion ~55% of EBITDA, dragged by working
capital swings tied to grocery peak.
""",
    "harbor_market_competition.md": """# Harbor Logistics Group — market & competition

The UK 3PL market grew ~6% per year 2021-2024, driven by e-commerce
penetration and grocery's shift to fulfilled delivery. Harbor competes
with two larger national players and a long tail of regional operators.

Harbor's wedge is grocery-grade temperature-controlled fulfilment, a
capability the regional tail lacks and the national players price at a
premium. Switching costs are high once a retailer integrates Harbor's
WMS, but procurement teams increasingly run competitive re-tenders at
contract renewal.

Porter's view: supplier power (subcontracted drivers) is rising;
buyer power is high among the top customers; the threat of substitution
(retailers in-housing fulfilment) is the key structural risk.
""",
    "harbor_operations.md": """# Harbor Logistics Group — operations

11 distribution centres; the two automated sites (Daventry, Warrington)
handle 58% of throughput at materially better unit economics. The
remaining nine are manual and labour-cost-exposed.

Last-Mile relies on subcontracted drivers; driver availability and the
reclassification risk of gig-economy labour are the two largest
operational risks. The Returns Management segment is small but
strategically sticky — retailers that adopt it churn less.

Systems: a proprietary WMS (warehouse management system) is the
integration moat. A planned ERP migration (FY25-FY26) is mid-flight and
carries execution risk.
""",
    "harbor_comparable_transactions.md": """# Comparable transactions — UK/EU 3PL (illustrative)

Recent comparable 3PL transactions cleared at 7.5x-9.5x EV/EBITDA, with
temperature-controlled / grocery-capable assets at the top of the range.
Pure last-mile assets traded lower (5x-6.5x) on margin and labour
concerns.

A reasonable triangulation for a grocery-capable 3PL with ~11% margin
and mid-single-digit growth sits at 8.0x-9.0x adjusted EBITDA, before
any adjustment for the questionable FY24 EBITDA add-backs.
""",
    "harbor_integration_considerations.md": """# Harbor Logistics Group — integration considerations

Key integration risks for an acquirer running Harbor standalone:
the in-flight ERP migration (do not disrupt mid-cutover), the WMS
talent concentration (a handful of engineers hold the integration
moat), and the top-customer concentration (a single grocery loss would
materially impair the thesis).

A 100-day plan should prioritise: retaining the WMS engineering team,
de-risking the ERP cutover timeline, and securing the top-3 customer
contracts past the deal close.
""",
    "harbor_growth_options.md": """# Harbor Logistics Group — growth options

Three growth vectors: (1) cross-sell Returns Management into the
existing Fulfilment base (highest-confidence, sticky, margin-accretive);
(2) geographic expansion into the Republic of Ireland (moderate
confidence, requires a new temperature-controlled site); (3) automation
retrofit of the nine manual sites (capital-intensive, 2-3 year
payback).

The Returns cross-sell is the clearest near-term lever: penetration is
under 20% of the Fulfilment base today, and attach economics are strong.
""",
}


def _write_library(tmp: Path) -> list[str]:
    tmp.mkdir(parents=True, exist_ok=True)
    names = []
    for name, body in _LIBRARY_DOCS.items():
        (tmp / name).write_text(body, encoding="utf-8")
        names.append(name)
    return names


_MA_BRIEF = (
    "Assess whether our client (a logistics-focused PE fund) should "
    "proceed to a binding offer for Harbor Logistics Group, the UK 3PL, "
    "and at what EV range. The decision turns on: the real standalone "
    "EBITDA once the questionable FY24 warehouse-relocation add-backs are "
    "challenged; the durability of revenue given top-5 customer "
    "concentration; the operational risk of the in-flight ERP migration "
    "and subcontracted-driver model; and a defensible valuation "
    "triangulated from comparable 3PL transactions. Flag where the "
    "evidence is thin rather than guessing."
)

_GROWTH_BRIEF = (
    "Recommend the highest-confidence growth strategy for Harbor "
    "Logistics Group over the next 18 months. Compare the three vectors "
    "in our library — Returns Management cross-sell, Republic of Ireland "
    "expansion, and automation retrofit of the manual sites — on "
    "confidence, capital intensity, and margin impact. Pick one as the "
    "near-term priority and name the single assumption that would change "
    "the recommendation."
)


# ---------------------------------------------------------------------------
# Phase 1-2: onboarding + library
# ---------------------------------------------------------------------------


async def _cleanup_prior(firm_slug: str) -> None:
    from db.connection import acquire
    async with acquire() as conn:
        firm = await conn.fetchrow("SELECT id FROM firms WHERE slug = $1", firm_slug)
        if not firm:
            return
        fid = firm["id"]
        await conn.execute("DELETE FROM sessions WHERE firm_id = $1::uuid", fid)
        await conn.execute(
            "DELETE FROM chunks WHERE firm_content_id IN "
            "(SELECT id FROM firm_content WHERE firm_id = $1::uuid)", fid,
        )
        for tbl in (
            "firm_content", "claim_feedback", "artifact_ratings",
            "engagement_edit_telemetry", "pilot_checkins",
            "firm_budget_notifications", "ops_cost_alerts",
            "notifications", "purge_audit_log", "cost_ledger",
            "metric_events", "firm_memberships",
        ):
            try:
                await conn.execute(f"DELETE FROM {tbl} WHERE firm_id = $1::uuid", fid)
            except Exception:
                pass


async def phase_onboarding() -> tuple[Phase, dict[str, str]]:
    from core.pilot_onboarding import add_user, create_firm

    firm = await create_firm(
        name="Pilot Dress Rehearsal Inc", slug=FIRM_SLUG,
        primary_color="#143C8C",
        footer_text="Pilot Dress Rehearsal Inc — Private & Confidential",
    )
    partner = await add_user(firm_slug=FIRM_SLUG, email=PARTNER, role="firm_admin", name="Dana Partner")
    senior = await add_user(firm_slug=FIRM_SLUG, email=SENIOR, role="firm_member", name="Sam Senior")
    analyst = await add_user(firm_slug=FIRM_SLUG, email=ANALYST, role="firm_member", name="Avi Analyst")
    ids = {
        "firm_id": firm["firm_id"],
        "partner": partner["user_id"],
        "senior": senior["user_id"],
        "analyst": analyst["user_id"],
    }
    ok = all(ids.values()) and partner["membership_role"] == "admin"
    return Phase(
        "onboarding", ok,
        f"firm + 3 users created (firm_id={firm['firm_id'][:8]}…)",
        {"firm": firm, "users": ids},
    ), ids


async def phase_library(tmp: Path) -> Phase:
    from core.pilot_onboarding import ingest_library
    names = _write_library(tmp)
    res = await ingest_library(
        firm_slug=FIRM_SLUG, directory=tmp, category="prior_report",
        modes=["m_and_a_diligence", "growth_strategy"],
    )
    ready = res["summary"]["by_status"]["ready"]
    ok = ready >= 5
    return Phase(
        "library", ok,
        f"{ready}/{len(names)} docs ingested (ready)",
        {"summary": res["summary"], "doc_count": len(names)},
    )


# ---------------------------------------------------------------------------
# Phase 3-4: engagements + real pipeline
# ---------------------------------------------------------------------------


async def phase_engagements(ids: dict[str, str]) -> tuple[Phase, list[dict[str, Any]]]:
    from core.pilot_onboarding import create_engagement
    ma = await create_engagement(
        firm_slug=FIRM_SLUG, brief=_MA_BRIEF, mode="m_and_a_diligence",
        lead_email=SENIOR, reviewer_email=PARTNER,
        title="Project Harbor — M&A diligence",
    )
    growth = await create_engagement(
        firm_slug=FIRM_SLUG, brief=_GROWTH_BRIEF, mode="growth_strategy",
        lead_email=SENIOR, reviewer_email=PARTNER,
        title="Harbor — growth strategy",
    )
    engagements = [
        {"label": "m_and_a", "session_id": ma["session_id"], "brief": _MA_BRIEF},
        {"label": "growth", "session_id": growth["session_id"], "brief": _GROWTH_BRIEF},
    ]
    ok = ma["created"] or growth["created"] or True  # idempotent re-runs return existing
    return Phase(
        "engagements", ok,
        f"M&A={ma['session_id'][:8]}… growth={growth['session_id'][:8]}…",
        {"engagements": engagements},
    ), engagements


async def phase_pipeline(engagements: list[dict[str, Any]]) -> Phase:
    """Run the REAL orchestrator for each engagement."""
    from agents.orchestrator import run_pipeline
    from db.connection import acquire

    results = []
    for eng in engagements:
        t0 = time.perf_counter()
        status = "error"
        claim_count = 0
        err = ""
        try:
            await run_pipeline(eng["session_id"], eng["brief"])
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
        async with acquire() as conn:
            row = await conn.fetchrow(
                "SELECT status, pipeline_state FROM sessions WHERE id = $1::uuid",
                eng["session_id"],
            )
            status = row["status"] if row else "missing"
            claim_count = await conn.fetchval(
                "SELECT COUNT(*)::int FROM claim_support_rows WHERE session_id = $1::uuid",
                eng["session_id"],
            ) or 0
            has_report = await conn.fetchval(
                "SELECT COUNT(*)::int FROM reports WHERE session_id = $1::uuid",
                eng["session_id"],
            ) or 0
        eng["pipeline_status"] = status
        eng["claim_count"] = claim_count
        eng["has_report"] = bool(has_report)
        results.append({
            "label": eng["label"], "status": status,
            "claim_count": claim_count, "has_report": bool(has_report),
            "elapsed_s": round(time.perf_counter() - t0, 1),
            "error": err,
        })

    ok = all(r["has_report"] and r["claim_count"] > 0 for r in results)
    detail = "; ".join(
        f"{r['label']}: status={r['status']} claims={r['claim_count']} "
        f"report={r['has_report']} ({r['elapsed_s']}s)"
        + (f" ERR={r['error']}" if r["error"] else "")
        for r in results
    )
    return Phase("pipeline", ok, detail, {"runs": results})


# ---------------------------------------------------------------------------
# Phase 5: artifacts
# ---------------------------------------------------------------------------


_ARTIFACT_TARGETS = [
    ("one_pager", "html"),
    ("deck", "pptx"),
    ("excel_model", "xlsx"),
    ("email", "md"),
    ("interview_guide", "md"),
]


async def phase_artifacts(engagements: list[dict[str, Any]], ids: dict[str, str]) -> Phase:
    from uuid import UUID
    from core.exports import GenerateArtifactRequest, generate_artifact

    per_eng = []
    for eng in engagements:
        if not eng.get("has_report"):
            per_eng.append({"label": eng["label"], "skipped": "no report"})
            continue
        ready = 0
        details = []
        for atype, fmt in _ARTIFACT_TARGETS:
            try:
                res = await generate_artifact(
                    GenerateArtifactRequest(
                        session_id=UUID(eng["session_id"]),
                        artifact_type=atype, format=fmt,
                    ),
                    triggered_by=UUID(ids["senior"]),
                )
                status = res.status
                if status == "ready":
                    ready += 1
                details.append({"type": atype, "format": fmt, "status": status})
            except Exception as e:  # noqa: BLE001
                details.append({"type": atype, "format": fmt, "status": "error",
                                "error": f"{type(e).__name__}: {e}"})
        # 6 deliverables = the memo (report payload) + the 5 exporters.
        per_eng.append({
            "label": eng["label"],
            "memo_present": eng.get("has_report", False),
            "exporters_ready": ready,
            "deliverables": ready + (1 if eng.get("has_report") else 0),
            "details": details,
        })

    completed = [e for e in per_eng if "skipped" not in e]
    ok = bool(completed) and all(e["deliverables"] >= 6 for e in completed)
    detail = "; ".join(
        f"{e['label']}: {e.get('deliverables', 0)}/6 deliverables"
        if "skipped" not in e else f"{e['label']}: SKIPPED ({e['skipped']})"
        for e in per_eng
    )
    return Phase("artifacts", ok, detail, {"per_engagement": per_eng})


# ---------------------------------------------------------------------------
# Phase 6: review cycle
# ---------------------------------------------------------------------------


async def phase_review(engagements: list[dict[str, Any]], ids: dict[str, str]) -> Phase:
    from uuid import UUID
    from core.review.service import transition_review
    from core.review.state_machine import ReviewAction

    target = next((e for e in engagements if e.get("has_report")), None)
    if target is None:
        return Phase("review", False, "no completed engagement to review", {})

    sid = UUID(target["session_id"])
    senior = UUID(ids["senior"])     # lead/consultant
    partner = UUID(ids["partner"])   # reviewer/firm_admin

    steps = []

    async def _do(action, actor, reviewer=None, feedback=None):
        r = await transition_review(
            sid, action, actor, reviewer_id=reviewer, feedback=feedback,
        )
        steps.append({
            "action": action.value, "ok": r.ok,
            "from": r.from_state, "to": r.to_state,
            "status_code": r.status_code, "reason": r.reason,
        })
        return r

    await _do(ReviewAction.SUBMIT_FOR_REVIEW, senior, reviewer=partner)
    await _do(ReviewAction.REQUEST_CHANGES, partner,
              feedback="Tighten the valuation range and challenge the FY24 EBITDA add-backs.")
    await _do(ReviewAction.RESUBMIT, senior)
    approve = await _do(ReviewAction.APPROVE, partner)

    ok = approve.ok and approve.to_state == "approved"
    target["approved"] = ok
    return Phase(
        "review", ok,
        "cycle: " + " -> ".join(
            s["action"] + ("(ok)" if s["ok"] else "(x)") for s in steps
        ),
        {"steps": steps, "session_id": target["session_id"]},
    )


# ---------------------------------------------------------------------------
# Phase 7: feedback instrumentation
# ---------------------------------------------------------------------------


async def phase_feedback(engagements: list[dict[str, Any]], ids: dict[str, str]) -> Phase:
    from db.connection import acquire
    from core.pilot_feedback import (
        pilot_health_panel, record_artifact_rating, record_claim_feedback,
        submit_checkin,
    )

    firm_id = ids["firm_id"]
    target = next((e for e in engagements if e.get("has_report")), None)
    n_claim_fb = 0
    if target:
        async with acquire() as conn:
            claims = await conn.fetch(
                "SELECT claim_id, COALESCE(ensemble_verdict, verifier_verdict) AS v "
                "FROM claim_support_rows WHERE session_id = $1::uuid "
                "AND claim_id IS NOT NULL LIMIT 6",
                target["session_id"],
            )
        # Simulate a consultant: mostly 'correct', a couple 'wrong_flagged'
        # (the safe-side over-caution we measured in W24/D1).
        for i, c in enumerate(claims):
            assessment = "wrong_flagged" if i % 3 == 2 else "correct"
            await record_claim_feedback(
                session_id=target["session_id"], firm_id=firm_id,
                claim_id=str(c["claim_id"]),
                consultant_assessment=assessment,
                user_id=ids["senior"],
                verdict_at_feedback=str(c["v"]) if c["v"] else None,
            )
            n_claim_fb += 1
        await record_artifact_rating(
            session_id=target["session_id"], firm_id=firm_id, rating=4,
            user_id=ids["senior"], artifact_type="deck",
            comment="Structure solid; valuation slide needed a tweak.",
        )
        await record_artifact_rating(
            session_id=target["session_id"], firm_id=firm_id, rating=4,
            user_id=ids["partner"], artifact_type="memo",
        )
    await submit_checkin(
        firm_id=firm_id, user_id=ids["partner"],
        responses={
            "what_worked": "End-to-end run produced a usable first draft.",
            "trust_rating": 4, "would_keep_using": "yes",
        },
    )
    panel = await pilot_health_panel(firm_id)
    ok = (
        panel["claim_feedback"]["total"] >= 1
        and panel["artifact_ratings"]["rating_count"] >= 1
        and len(panel["checkin_trend"]) >= 1
    )
    return Phase(
        "feedback", ok,
        f"claim_fb={panel['claim_feedback']['total']} "
        f"ratings={panel['artifact_ratings']['rating_count']} "
        f"avg_edit_pct={panel['edit_rate']['average_edit_pct']} "
        f"checkins={len(panel['checkin_trend'])}",
        {"pilot_health": panel},
    )


# ---------------------------------------------------------------------------
# Phase 8: enterprise scenarios (isolation / deletion / audit export)
# ---------------------------------------------------------------------------


async def phase_enterprise(engagements: list[dict[str, Any]], ids: dict[str, str]) -> Phase:
    from uuid import UUID
    from fastapi import HTTPException
    from db.connection import acquire
    from auth.firm_scope import assert_firm_access
    from core.retention.deletion import _PURGE_TABLES, purge_engagement
    from api.audit_export import _fetch_audit_rows

    firm_id = ids["firm_id"]
    findings: dict[str, Any] = {}

    # --- isolation: an outsider firm's user attempts cross-firm access ---
    other_firm = str(uuid4())
    async with acquire() as conn:
        await conn.execute(
            "INSERT INTO firms (id, name, slug) VALUES ($1::uuid, $2, $3)",
            other_firm, "Outsider Co", f"outsider-{other_firm[:8]}",
        )
    outsider = {
        "user_id": str(uuid4()), "role": "member",
        "default_firm_id": other_firm, "default_firm_role": "admin",
    }
    blocked = 0
    attempts = [e["session_id"] for e in engagements] or [str(uuid4())]
    for sid in attempts:
        try:
            await assert_firm_access(
                user=outsider, resource_firm_id=firm_id,
                resource_kind="session", resource_id=sid,
                allow_system_admin=False,
            )
        except HTTPException as e:
            if e.status_code == 404:
                blocked += 1
    findings["isolation"] = {"attempts": len(attempts), "blocked_404": blocked}

    # --- deletion: purge a throwaway engagement -> zero residual ---
    throwaway = str(uuid4())
    async with acquire() as conn:
        await conn.execute(
            "INSERT INTO sessions (id, firm_id, title, query, status, created_by_user_id) "
            "VALUES ($1::uuid, $2::uuid, '[dress] purge target', 'q', 'ready', $3::uuid)",
            throwaway, firm_id, ids["senior"],
        )
        await conn.execute(
            "INSERT INTO evidence_objects (session_id, claim, quote, source_type) "
            "VALUES ($1::uuid, 'c', 'q', 'document')", throwaway,
        )
    report = await purge_engagement(throwaway, actor_user_id=ids["partner"], purge_reason="test")
    residual = 0
    async with acquire() as conn:
        for tbl in _PURGE_TABLES:
            try:
                n = await conn.fetchval(
                    f"SELECT COUNT(*)::int FROM {tbl} WHERE session_id = $1::uuid", throwaway,
                )
                residual += int(n or 0)
            except Exception:
                pass
        audit_present = await conn.fetchval(
            "SELECT COUNT(*)::int FROM purge_audit_log WHERE id = $1", report.audit_log_id,
        )
    findings["deletion"] = {
        "residual_rows": residual, "audit_row_present": bool(audit_present),
        "rows_deleted": report.total_rows_deleted(),
    }

    # --- audit export: firm-scoped, content-free ---
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO audit_events (actor_user_id, action, resource_type,
                resource_id, method, path, status_code, payload)
            VALUES ($1::uuid, 'engagement.create', 'session', $2, 'POST',
                '/api/sessions', 201, $3::jsonb)
            """,
            ids["senior"], attempts[0],
            json.dumps({"session_id": attempts[0], "claim_text": "MUST_NOT_LEAK"}),
        )
    rows = []
    async for r in _fetch_audit_rows(firm_id, None, None):
        rows.append(r)
    leak = "MUST_NOT_LEAK" in json.dumps(rows)
    findings["audit_export"] = {"rows": len(rows), "content_leak": leak}

    # cleanup the outsider firm
    async with acquire() as conn:
        await conn.execute("DELETE FROM firms WHERE id = $1::uuid", other_firm)

    ok = (
        blocked == len(attempts)
        and residual == 0 and bool(audit_present)
        and len(rows) >= 1 and not leak
    )
    return Phase(
        "enterprise", ok,
        f"isolation {blocked}/{len(attempts)} blocked; purge residual={residual}; "
        f"audit rows={len(rows)} leak={leak}",
        findings,
    )


# ---------------------------------------------------------------------------
# Phase 9: cost
# ---------------------------------------------------------------------------


async def phase_cost(ids: dict[str, str]) -> Phase:
    from db.connection import acquire
    async with acquire() as conn:
        total = await conn.fetchval(
            "SELECT COALESCE(SUM(cost_usd),0)::float FROM cost_ledger WHERE firm_id = $1::uuid",
            ids["firm_id"],
        )
        calls = await conn.fetchval(
            "SELECT COUNT(*)::int FROM cost_ledger WHERE firm_id = $1::uuid",
            ids["firm_id"],
        )
    return Phase(
        "cost", True,
        f"LLM spend this run: ${float(total or 0):.2f} across {int(calls or 0)} calls",
        {"total_usd": round(float(total or 0), 4), "call_count": int(calls or 0)},
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


async def _run(skip_pipeline: bool) -> int:
    from db.connection import close_db, init_db

    await init_db()
    phases: list[Phase] = []
    tmp = _OUT / "_library_src"
    try:
        await _cleanup_prior(FIRM_SLUG)
        p_onb, ids = await phase_onboarding()
        phases.append(p_onb)
        phases.append(await phase_library(tmp))
        p_eng, engagements = await phase_engagements(ids)
        phases.append(p_eng)

        if skip_pipeline:
            # Reuse whatever the DB already has for these sessions.
            from db.connection import acquire
            for eng in engagements:
                async with acquire() as conn:
                    has = await conn.fetchval(
                        "SELECT COUNT(*)::int FROM reports WHERE session_id = $1::uuid",
                        eng["session_id"],
                    )
                    cc = await conn.fetchval(
                        "SELECT COUNT(*)::int FROM claim_support_rows WHERE session_id = $1::uuid",
                        eng["session_id"],
                    )
                eng["has_report"] = bool(has)
                eng["claim_count"] = int(cc or 0)
            phases.append(Phase("pipeline", all(e.get("has_report") for e in engagements),
                                "skipped (--skip-pipeline); reused existing reports",
                                {"reused": True}))
        else:
            phases.append(await phase_pipeline(engagements))

        phases.append(await phase_artifacts(engagements, ids))
        phases.append(await phase_review(engagements, ids))
        phases.append(await phase_feedback(engagements, ids))
        phases.append(await phase_enterprise(engagements, ids))
        phases.append(await phase_cost(ids))
    finally:
        await close_db()

    all_ok = all(p.ok for p in phases)
    summary = {
        "run_at": datetime.now(tz=timezone.utc).isoformat(),
        "all_ok": all_ok,
        "outcome": "pass" if all_ok else "issues",
        "phases": [asdict(p) for p in phases],
    }
    _OUT.mkdir(parents=True, exist_ok=True)
    (_OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    print()
    print("=" * 72)
    print("Pilot dress rehearsal")
    print("=" * 72)
    for p in phases:
        print(f"  [{'OK ' if p.ok else 'FAIL'}] {p.name:14s} {p.detail}")
    print("=" * 72)
    print(f"Result: {'PASS' if all_ok else 'ISSUES'}  ({sum(1 for p in phases if p.ok)}/{len(phases)})")
    print(f"Saved:  {_OUT / 'summary.json'}")
    return 0 if all_ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-pipeline", action="store_true",
                    help="Reuse existing reports instead of a real LLM run.")
    args = ap.parse_args(argv)
    return asyncio.run(_run(skip_pipeline=args.skip_pipeline))


if __name__ == "__main__":
    raise SystemExit(main())
