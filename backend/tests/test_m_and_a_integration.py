"""Phase 2 / Week 7 / Day 4 — M&A end-to-end integration test.

Real LLM run, real DB, real schema validation. Gated behind
``ARGUS_RUN_REAL_LLM_INTEGRATION=1`` because it costs real money.
The test asserts on the structural shape of the M&A writer payload
— if the LLM produces something the schema rejects, or the schema
accepts but a content-discipline check (monotonic valuation,
non-empty dis-synergies, etc.) fails, the test surfaces it
immediately. No re-runs, no retries — the spec hard rule is "Run
once. If it fails legitimately, that's a finding for Day 5."

Pre-conditions:
  - Demo firm "Argus Demo Boutique" exists (seed_week5_demo.py)
  - W6 boutique pricing override seeded (seed_week6_demo.py) — not
    used here but doesn't conflict
  - TargetCo CIM seeded into the demo firm's library
    (seed_week7_demo.py)
  - DATABASE_URL points to a writable Postgres
  - ARGUS_USE_ENSEMBLE_VERDICT=true (per W7/D4 spec preflight)
  - ARGUS_RUN_REAL_LLM_INTEGRATION=1 (gates execution)

Cost ceiling: $3.00 per run.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

DEMO_FIRM_SLUG = "argus-demo-boutique"
COST_CEILING_USD = 3.00

BRIEF = (
    "Conduct a diligence assessment of TargetCo Holdings, a UK "
    "industrial services group with £180m FY24 revenue. Quantify "
    "the deal opportunity, identify key risks, recommend deal "
    "structure and a valuation range."
)

# Recommendation tokens the M&A prompt requires the writer to land
# on. Schema accepts any string in `recommendation`; we match a
# normalized prefix so trivial casing / punctuation differences pass.
_VALID_RECOMMENDATION_TOKENS = (
    "PROCEED WITH CONDITIONS",
    "PROCEED",
    "RENEGOTIATE",
    "WALK AWAY",
)


pytestmark = pytest.mark.skipif(
    os.getenv("ARGUS_RUN_REAL_LLM_INTEGRATION") != "1",
    reason="Real-LLM integration test; gate with ARGUS_RUN_REAL_LLM_INTEGRATION=1",
)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session", autouse=True)
def _ensemble_flag():
    os.environ.setdefault("ARGUS_USE_ENSEMBLE_VERDICT", "true")


@pytest.fixture(scope="session")
async def _firm_id() -> str:
    from db.connection import acquire, init_db, close_db

    await init_db()
    try:
        async with acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM firms WHERE slug = $1", DEMO_FIRM_SLUG
            )
        if not row:
            pytest.skip(
                f"firm {DEMO_FIRM_SLUG!r} missing — run "
                "tools/seed_week5_demo.py before this test."
            )
        return str(row["id"])
    finally:
        await close_db()


@pytest.fixture(scope="session")
async def _cim_seeded(_firm_id: str, _project_root: Path) -> str:
    """Ensure the TargetCo CIM is in the demo firm's library. Reuses
    the W7/D4 seeder to keep the path canonical and idempotent."""
    from db.connection import acquire, init_db, close_db
    from core.firm_library.service import ingest_firm_content

    fixture = _project_root / "backend" / "tests" / "fixtures" / "m_and_a" / "targetco_cim.md"
    if not fixture.exists():
        pytest.skip(f"missing CIM fixture at {fixture}")

    await init_db()
    try:
        result = await ingest_firm_content(
            firm_id=_firm_id,
            title="TargetCo Holdings — Project Lighthouse CIM",
            category="prior_report",
            file_bytes=fixture.read_bytes(),
            source_filename="targetco_cim.md",
            uploaded_by=None,
            description="W7/D4 integration test fixture.",
            intended_modes=["m_and_a_diligence"],
            sector_tags=["industrial_services", "uk"],
        )
        return result.firm_content_id
    finally:
        await close_db()


# ---------------------------------------------------------------------------
# Run helper
# ---------------------------------------------------------------------------


async def _setup_session(firm_id: str) -> str:
    from db.connection import acquire

    session_id = str(uuid.uuid4())
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sessions (
                id, title, query, status, report_mode, pipeline_state,
                metadata, gap_report, intake_questions, intake_answers,
                firm_id, updated_at
            ) VALUES (
                $1::uuid, $2, $3, 'draft', 'm_and_a_diligence', 'idle',
                $4::jsonb, '{}'::jsonb, '[]'::jsonb, '[]'::jsonb,
                $5::uuid, NOW()
            )
            """,
            session_id,
            "W7/D4 integration · TargetCo M&A diligence",
            BRIEF,
            json.dumps({"week7_d4_integration": True}),
            firm_id,
        )
    return session_id


async def _capture_report(session_id: str) -> dict[str, Any]:
    from db.connection import acquire

    async with acquire() as conn:
        report = await conn.fetchrow(
            """
            SELECT recommendation, summary, key_reasons, risks,
                   counterarguments, next_steps, sources, caveats,
                   evidence_count, unsupported_claim_count,
                   consulting_payload, created_at
            FROM reports
            WHERE session_id = $1::uuid
            """,
            session_id,
        )
        evidence = await conn.fetch(
            """
            SELECT id, source_type, source_title, source_url, metadata
            FROM evidence_objects
            WHERE session_id = $1::uuid
            """,
            session_id,
        )
        llm = await conn.fetch(
            """
            SELECT task_kind, usd_cost FROM llm_calls
            WHERE session_id = $1::uuid
            """,
            session_id,
        )
    return {
        "report": dict(report) if report else None,
        "evidence": [dict(e) for e in evidence],
        "llm": [dict(c) for c in llm],
    }


def _parse_consulting_payload(report_row: dict[str, Any]) -> dict[str, Any]:
    cp = report_row.get("consulting_payload")
    if isinstance(cp, str):
        return json.loads(cp)
    if isinstance(cp, dict):
        return cp
    return {}


# ---------------------------------------------------------------------------
# THE integration test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_m_and_a_integration_end_to_end(_firm_id: str, _cim_seeded: str) -> None:
    from agents.orchestrator import run_pipeline
    from core.consulting_modes import resolve_mode
    from db.connection import close_db, init_db

    await init_db()
    session_id = await _setup_session(_firm_id)

    # Sanity: resolver returns the M&A mode for this session's firm.
    resolved = await resolve_mode("m_and_a_diligence", firm_id=_firm_id, engagement_id=session_id)
    assert resolved.name == "m_and_a_diligence"

    t0 = time.perf_counter()
    try:
        await run_pipeline(session_id, BRIEF)
    except Exception as e:  # noqa: BLE001
        # Surface but don't swallow — the test wants to see what happened.
        await close_db()
        pytest.fail(f"run_pipeline raised: {type(e).__name__}: {e}")
    wall = time.perf_counter() - t0

    captured = await _capture_report(session_id)
    await close_db()

    cost = sum(float(c.get("usd_cost") or 0) for c in captured["llm"])
    print(
        f"\n[w7d4] wall={wall:.0f}s  cost=${cost:.4f}  "
        f"evidence={len(captured['evidence'])}",
        flush=True,
    )

    # ------------------------------------------------------------------
    # Cost ceiling — cap a single run at the spec's $3.00 limit.
    # ------------------------------------------------------------------
    assert cost < COST_CEILING_USD, (
        f"M&A integration run cost ${cost:.4f}, exceeds ${COST_CEILING_USD} ceiling. "
        "Investigate retry/repair loops before raising the cap."
    )

    # ------------------------------------------------------------------
    # 1. Report row written + has the M&A-shape consulting payload.
    # ------------------------------------------------------------------
    report = captured["report"]
    assert report is not None, "no reports row written; pipeline may have stalled"
    cp = _parse_consulting_payload(report)
    assert cp, "consulting_payload missing — writer didn't run or produced no extras"

    # ------------------------------------------------------------------
    # 2. Validate against MAndADiligenceReportPayload by reconstructing
    #    the writer-output shape from report row + consulting_payload.
    #    The schema rejects anything off-spec; if it parses, we have
    #    structural confidence.
    # ------------------------------------------------------------------
    from agents.writer.schemas import MAndADiligenceReportPayload

    payload_for_validation = {
        "mode": "m_and_a_diligence",
        "recommendation": report["recommendation"] or "",
        "confidence_level": "Medium",
        "summary": report["summary"] or "",
        "key_reasons": list(report["key_reasons"] or []),
        "risks": list(report["risks"] or []),
        "counterarguments": list(report["counterarguments"] or []),
        "next_steps": list(report["next_steps"] or []),
        "sources": list(report["sources"] or []),
        "caveats": report["caveats"] or "",
        # M&A-specific sections come from consulting_payload.
        "target_overview": cp.get("target_overview"),
        "financial_profile": cp.get("financial_profile"),
        "synergy_estimate": cp.get("synergy_estimate"),
        "risks_and_mitigations": cp.get("risks_and_mitigations"),
        "integration_plan": cp.get("integration_plan"),
        "valuation_range": cp.get("valuation_range"),
        "deal_structure_implications": cp.get("deal_structure_implications"),
    }
    validated = MAndADiligenceReportPayload.model_validate(payload_for_validation)
    assert validated.mode == "m_and_a_diligence"

    # ------------------------------------------------------------------
    # 3. Target overview shape.
    # ------------------------------------------------------------------
    assert validated.target_overview.name, "target_overview.name empty"
    assert "targetco" in validated.target_overview.name.lower() or "target co" in validated.target_overview.name.lower(), (
        f"target name {validated.target_overview.name!r} does not reference TargetCo"
    )
    assert len(validated.target_overview.segments) >= 3, (
        f"expected >=3 segments, got {len(validated.target_overview.segments)}"
    )

    # ------------------------------------------------------------------
    # 4. Financial profile.
    # ------------------------------------------------------------------
    assert len(validated.financial_profile.revenue_trajectory.points) >= 3

    # ------------------------------------------------------------------
    # 5. Synergies — three buckets non-empty + every entry has a basis.
    # ------------------------------------------------------------------
    syn = validated.synergy_estimate
    assert syn.revenue_synergies, "revenue_synergies empty"
    assert syn.cost_synergies, "cost_synergies empty"
    assert syn.dis_synergies, (
        "dis_synergies empty — every M&A produces them; spec hard rule violated"
    )
    for bucket_name in ("revenue_synergies", "cost_synergies", "dis_synergies"):
        for s in getattr(syn, bucket_name):
            assert s.basis_citations, (
                f"{bucket_name} entry {s.type!r} has empty basis_citations "
                "(schema should have rejected this — if it didn't, basis "
                "validator regressed)"
            )

    # ------------------------------------------------------------------
    # 6. Valuation range — three populated points with distinct
    #    methodology and monotonic gbp_m.
    # ------------------------------------------------------------------
    val = validated.valuation_range
    for label in ("low", "base", "high"):
        point = getattr(val, label)
        assert point.gbp_m > 0, f"valuation {label}.gbp_m must be > 0"
        assert point.methodology.strip(), f"valuation {label}.methodology empty"
    methods = {val.low.methodology.strip().lower(), val.base.methodology.strip().lower(),
               val.high.methodology.strip().lower()}
    assert len(methods) >= 2, (
        "valuation_range methodology identical across low/base/high; "
        "triangulation discipline failed"
    )
    assert val.low.gbp_m < val.base.gbp_m < val.high.gbp_m, (
        f"valuation not monotonic: low={val.low.gbp_m}, "
        f"base={val.base.gbp_m}, high={val.high.gbp_m}"
    )

    # ------------------------------------------------------------------
    # 7. Integration plan — Day 1 priorities + first_100_days bands.
    # ------------------------------------------------------------------
    plan = validated.integration_plan
    assert plan.day_one_priorities, "day_one_priorities empty"
    assert len(plan.first_100_days) >= 3, (
        f"expected >=3 first_100_days initiatives, got {len(plan.first_100_days)}"
    )
    for ib in plan.first_100_days:
        assert ib.owner_role.strip(), f"InitiativeBlock owner_role empty for {ib.workstream!r}"
        assert ib.milestone.strip(), f"InitiativeBlock milestone empty for {ib.workstream!r}"
    assert plan.integration_complexity_rating in {"low", "medium", "high"}

    # ------------------------------------------------------------------
    # 8. Deal structure implications — walk-aways are falsifiable.
    # ------------------------------------------------------------------
    deal = validated.deal_structure_implications
    triggers = list(deal.walk_away_triggers)
    assert len(triggers) >= 2, f"expected >=2 walk_away_triggers, got {len(triggers)}"
    for t in triggers:
        assert re.search(r"\d|%", t), (
            f"walk_away_trigger {t!r} has no quantitative threshold "
            "(no digit or %); not falsifiable"
        )

    # ------------------------------------------------------------------
    # 9. Recommendation lands on one of the four M&A verdicts.
    # ------------------------------------------------------------------
    rec_upper = (validated.recommendation or "").upper()
    assert any(tok in rec_upper for tok in _VALID_RECOMMENDATION_TOKENS), (
        f"recommendation {validated.recommendation!r} doesn't start with one of "
        f"{_VALID_RECOMMENDATION_TOKENS}"
    )

    # ------------------------------------------------------------------
    # 10. Source diversity — at least one firm_library citation
    #     (the CIM is the obvious source).
    # ------------------------------------------------------------------
    src_types = {(e.get("source_type") or "").lower() for e in captured["evidence"]}
    assert "firm_library" in src_types, (
        f"no firm_library citation in evidence; CIM was not consumed. "
        f"Saw: {sorted(src_types)}"
    )
