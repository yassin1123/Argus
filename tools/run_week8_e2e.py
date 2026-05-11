"""Phase 2 / Week 8 / Day 5 — frameworks-library e2e demo runner.

Two engagements in the demo firm:

  Run A (m_and_a):           report_mode=m_and_a_diligence
                             brief = TargetCo Holdings diligence (W7 brief)
                             expects frameworks.two_by_two populated
  Run B (growth_strategy):   report_mode=growth_strategy
                             brief = German market-entry strategy
                             expects frameworks.porters_five_forces populated

Each run captures the writer payload plus the new W8 framework slots
plus the W8 post-writer artifacts (Pyramid + MECE check results stored
on session.metadata).

Output:
  backend/eval_runs/week8_e2e/A_m_and_a.json
  backend/eval_runs/week8_e2e/B_growth_strategy.json
  backend/eval_runs/week8_e2e/summary.json   (committed)

Cost ceiling: $5 across both runs.

Usage::

    python tools/run_week8_e2e.py
    python tools/run_week8_e2e.py --runs A_m_and_a
    python tools/run_week8_e2e.py --summary-only
    python tools/run_week8_e2e.py --harvest A_m_and_a:<session_id>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import traceback
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))

os.environ.setdefault("ARGUS_USE_ENSEMBLE_VERDICT", "true")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")


DEMO_FIRM_SLUG = "argus-demo-boutique"

# Run A — same M&A brief as W7. If Run A produces a clean M&A payload
# (7 base fields + 2x2), Week 7's verification carry-forward closes.
M_AND_A_BRIEF = (
    "Conduct a diligence assessment of TargetCo Holdings, a UK "
    "industrial services group with £180m FY24 revenue. Quantify "
    "the deal opportunity, identify key risks, recommend deal "
    "structure and a valuation range."
)

# Run B — W8/D5 iterate-3: re-flavored to a UK-supported question.
# Original W8/D5 spec brief was German market entry; the demo firm's
# library has UK industrial services content only (TargetCo CIM,
# Retail Sector Primer UK+US, Albright & Marsh Pricing Pack, etc.),
# so the analyst correctly refused to fabricate German market data
# and Porter's never got produced. Re-flavoring keeps the brief
# adjacent (still growth_strategy, still uses TargetCo data) while
# ensuring the firm library can actually support the analysis.
GROWTH_BRIEF = (
    "Develop a UK regional expansion strategy for TargetCo into "
    "Scotland and the North-East. Cover competitive landscape, "
    "operational considerations, go-to-market options."
)

M_AND_A_TOP_LEVEL_FIELDS = (
    "target_overview",
    "financial_profile",
    "synergy_estimate",
    "risks_and_mitigations",
    "integration_plan",
    "valuation_range",
    "deal_structure_implications",
)

# WriterReportBase fields required for the W7 carry-forward close.
W7_BASE_FIELDS = (
    "recommendation",
    "confidence_level",
    "summary",
    "key_reasons",
    "risks",
    "counterarguments",
    "next_steps",
    "sources",
)

PORTERS_FORCES = (
    "rivalry",
    "supplier_power",
    "buyer_power",
    "substitute_threat",
    "new_entrant_threat",
)


def _runs() -> list[dict[str, str]]:
    return [
        {
            "name": "A_m_and_a",
            "firm_slug": DEMO_FIRM_SLUG,
            "report_mode": "m_and_a_diligence",
            "title": "Week 8 E2E · TargetCo · M&A diligence (with 2x2)",
            "brief": M_AND_A_BRIEF,
            "expected_framework": "two_by_two",
        },
        {
            "name": "B_growth_strategy",
            "firm_slug": DEMO_FIRM_SLUG,
            "report_mode": "growth_strategy",
            "title": "Week 8 E2E · TargetCo · Germany market entry (with Porter's)",
            "brief": GROWTH_BRIEF,
            "expected_framework": "porters_five_forces",
        },
    ]


BENCH_ROOT = _REPO_ROOT / "backend" / "eval_runs" / "week8_e2e"
SUMMARY_PATH = BENCH_ROOT / "summary.json"
COST_CEILING_TOTAL_USD = 5.00


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _firm_id_for_slug(slug: str) -> str:
    from db.connection import acquire

    async with acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM firms WHERE slug = $1", slug)
    if not row:
        raise SystemExit(
            f"firm slug not found: {slug!r} — run tools/seed_week5_demo.py first"
        )
    return str(row["id"])


async def _setup_session(
    firm_id: str, title: str, brief: str, run_name: str, report_mode: str
) -> str:
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
                $1::uuid, $2, $3, 'draft', $4, 'idle',
                $5::jsonb, '{}'::jsonb, '[]'::jsonb, '[]'::jsonb,
                $6::uuid, NOW()
            )
            """,
            session_id, title, brief, report_mode,
            json.dumps({"week8_e2e": True, "run_name": run_name}), firm_id,
        )
    return session_id


def _normalize(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, uuid.UUID):
        return str(v)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, list):
        return [_normalize(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _normalize(x) for k, x in v.items()}
    try:
        json.dumps(v)
        return v
    except TypeError:
        return str(v)


def _row_to_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    return {k: _normalize(v) for k, v in dict(row).items()}


async def _capture(session_id: str) -> dict[str, Any]:
    from db.connection import acquire

    async with acquire() as conn:
        report = await conn.fetchrow(
            """
            SELECT id, recommendation, confidence_level, summary,
                   key_reasons, risks, counterarguments, next_steps,
                   sources, caveats, evidence_count,
                   unsupported_claim_count, consulting_payload,
                   raw_output, created_at
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
            SELECT task_kind, model, usd_cost, success
            FROM llm_calls
            WHERE session_id = $1::uuid
            ORDER BY id ASC
            """,
            session_id,
        )
        sess = await conn.fetchrow(
            """
            SELECT status, pipeline_state, metadata, gap_report,
                   pyramid_findings_count, mece_overlaps_count
            FROM sessions WHERE id = $1::uuid
            """,
            session_id,
        )
    return {
        "session_id": session_id,
        "report": _row_to_dict(report) if report else None,
        "evidence_objects": [_row_to_dict(e) for e in evidence],
        "llm_calls": [_row_to_dict(c) for c in llm],
        "session": _row_to_dict(sess) if sess else {},
    }


def _parse_consulting_payload(report: dict[str, Any] | None) -> dict[str, Any]:
    if not report:
        return {}
    cp = report.get("consulting_payload")
    if isinstance(cp, str):
        try:
            return json.loads(cp)
        except Exception:
            return {}
    return cp or {}


def _parse_session_metadata(captured: dict[str, Any]) -> dict[str, Any]:
    sess = captured.get("session") or {}
    md = sess.get("metadata")
    if isinstance(md, str):
        try:
            return json.loads(md)
        except Exception:
            return {}
    return md or {}


# ---------------------------------------------------------------------------
# Analysis — W8 additions: frameworks, pyramid, mece
# ---------------------------------------------------------------------------


def _frameworks_status(report: dict[str, Any] | None) -> dict[str, Any]:
    """Pull frameworks block off the writer payload, however it landed.

    Writer payloads carry frameworks both on the top-level row (when the
    JSON was projected via to_jsonb in save_report) and inside
    ``consulting_payload``. Either source is acceptable.
    """
    if not report:
        return {"present": False, "two_by_two": None, "porters_five_forces": None, "value_chain": None}

    # Some writer flows store the top-level dump under raw_output as JSON.
    raw_output = report.get("raw_output")
    raw_fw: Any = None
    if isinstance(raw_output, str):
        try:
            raw_fw = (json.loads(raw_output) or {}).get("frameworks")
        except Exception:
            raw_fw = None

    cp = _parse_consulting_payload(report)
    cp_fw = cp.get("frameworks") if isinstance(cp, dict) else None

    fw = raw_fw if isinstance(raw_fw, dict) else (cp_fw if isinstance(cp_fw, dict) else None)
    if not isinstance(fw, dict):
        return {"present": False, "two_by_two": None, "porters_five_forces": None, "value_chain": None}

    return {
        "present": True,
        "two_by_two": fw.get("two_by_two"),
        "porters_five_forces": fw.get("porters_five_forces"),
        "value_chain": fw.get("value_chain"),
    }


def _two_by_two_quality(two_by_two: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(two_by_two, dict):
        return {"items_count": 0, "items_with_citations": 0, "axes_labeled": False}
    items = two_by_two.get("items") or []
    items_with = sum(
        1
        for it in items
        if isinstance(it, dict)
        and isinstance(it.get("evidence_citations"), list)
        and len([c for c in it["evidence_citations"] if isinstance(c, str) and c.strip()]) > 0
    )
    axes_labeled = bool(
        (two_by_two.get("x_axis_label") or "").strip()
        and (two_by_two.get("y_axis_label") or "").strip()
    )
    return {
        "items_count": len(items),
        "items_with_citations": items_with,
        "axes_labeled": axes_labeled,
    }


def _porters_quality(porters: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(porters, dict):
        return {
            "all_five_populated": False,
            "forces_with_evidence": 0,
            "market_definition_set": False,
            "overall_attractiveness": None,
        }
    populated = []
    with_evidence = 0
    for force in PORTERS_FORCES:
        f = porters.get(force)
        if isinstance(f, dict) and (f.get("intensity") and (f.get("rationale") or "").strip()):
            populated.append(force)
            cites = f.get("evidence_citations") or []
            if isinstance(cites, list) and any(isinstance(c, str) and c.strip() for c in cites):
                with_evidence += 1
    return {
        "all_five_populated": len(populated) == 5,
        "forces_with_evidence": with_evidence,
        "market_definition_set": bool((porters.get("market_definition") or "").strip()),
        "overall_attractiveness": porters.get("overall_attractiveness"),
    }


def _pyramid_result(metadata: dict[str, Any]) -> dict[str, Any]:
    r = metadata.get("pyramid_check_result")
    if not isinstance(r, dict):
        return {"present": False, "passed": None, "findings": 0, "model_used": None, "cost_usd": 0.0}
    findings = r.get("findings") or []
    errs = sum(1 for f in findings if isinstance(f, dict) and f.get("severity") == "error")
    return {
        "present": True,
        "passed": bool(r.get("passed")),
        "findings": len(findings),
        "errors": errs,
        "model_used": r.get("model_used"),
        "cost_usd": float(r.get("cost_usd") or 0),
    }


def _mece_result(metadata: dict[str, Any]) -> dict[str, Any]:
    r = metadata.get("mece_check_result")
    if not isinstance(r, dict):
        return {"present": False, "passed": None, "overlaps": 0, "fields_checked": []}
    overlaps = r.get("overlaps") or []
    # Per-field overlap counts.
    per_field: Counter[str] = Counter()
    for o in overlaps:
        if isinstance(o, dict):
            per_field[str(o.get("field_path") or "?")] += 1
    return {
        "present": True,
        "passed": bool(r.get("passed")),
        "overlaps": len(overlaps),
        "overlaps_per_field": dict(per_field),
        "fields_checked": r.get("fields_checked") or [],
        "threshold": r.get("threshold"),
        "cost_usd": float(r.get("cost_usd") or 0),
    }


def _w7_carry_forward(report: dict[str, Any] | None, fw_status: dict[str, Any]) -> dict[str, Any]:
    """Determine whether Run A's payload closes Week 7's carry-forward.

    The W7 gap was: no M&A engagement ever produced a fully valid
    MAndADiligenceReportPayload end-to-end. Closure requires:
    - All 8 WriterReportBase fields present + non-trivially populated
    - All 7 M&A top-level sections present + populated
    """
    if not report:
        return {"closes_week7": False, "reason": "no report row at all"}
    cp = _parse_consulting_payload(report)
    base_missing = []
    for f in W7_BASE_FIELDS:
        v = report.get(f)
        if v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, list) and not v):
            base_missing.append(f)
    m_and_a_missing = [
        f for f in M_AND_A_TOP_LEVEL_FIELDS
        if not (isinstance(cp.get(f), (dict, list)) and cp.get(f))
    ]
    return {
        "closes_week7": (not base_missing) and (not m_and_a_missing) and fw_status.get("two_by_two") is not None,
        "base_fields_missing": base_missing,
        "m_and_a_sections_missing": m_and_a_missing,
        "two_by_two_present": fw_status.get("two_by_two") is not None,
    }


def _analyze(captured: dict[str, Any], expected_framework: str | None) -> dict[str, Any]:
    rep = captured.get("report") or {}
    metadata = _parse_session_metadata(captured)
    fw = _frameworks_status(rep)

    diversity: Counter[str] = Counter()
    firm_lib_titles: Counter[str] = Counter()
    for e in captured.get("evidence_objects") or []:
        st = (e.get("source_type") or "").lower()
        diversity[st or "unknown"] += 1
        if st == "firm_library":
            md = e.get("metadata")
            if isinstance(md, str):
                try:
                    md = json.loads(md)
                except Exception:
                    md = {}
            if not isinstance(md, dict):
                md = {}
            t = str(md.get("firm_library_title") or e.get("source_title") or "")
            if t:
                firm_lib_titles[t] += 1

    cost = sum(float(c.get("usd_cost") or 0) for c in (captured.get("llm_calls") or []))

    out: dict[str, Any] = {
        "report_recommendation": rep.get("recommendation") or "",
        "report_summary_first_240": (rep.get("summary") or "")[:240],
        "evidence_total": len(captured.get("evidence_objects") or []),
        "diversity_counts": dict(diversity),
        "firm_library_titles_cited": dict(firm_lib_titles),
        "frameworks_status": fw,
        "two_by_two_quality": _two_by_two_quality(fw.get("two_by_two") if isinstance(fw.get("two_by_two"), dict) else None),
        "porters_quality": _porters_quality(fw.get("porters_five_forces") if isinstance(fw.get("porters_five_forces"), dict) else None),
        "pyramid": _pyramid_result(metadata),
        "mece": _mece_result(metadata),
        "expected_framework": expected_framework,
        "expected_framework_present": (
            isinstance(fw.get(expected_framework), dict) if expected_framework else None
        ),
        "cost_usd_total": round(cost, 4),
    }
    # M&A field presence (only meaningful on Run A; harmless on B).
    cp = _parse_consulting_payload(rep)
    out["m_and_a_fields_present"] = sorted(
        f for f in M_AND_A_TOP_LEVEL_FIELDS if isinstance(cp.get(f), (dict, list)) and cp.get(f)
    )
    out["m_and_a_fields_absent"] = sorted(
        f for f in M_AND_A_TOP_LEVEL_FIELDS if not (isinstance(cp.get(f), (dict, list)) and cp.get(f))
    )
    return out


# ---------------------------------------------------------------------------
# Run loop
# ---------------------------------------------------------------------------


def _cumulative_spend() -> float:
    if not BENCH_ROOT.exists():
        return 0.0
    total = 0.0
    for f in BENCH_ROOT.glob("*.json"):
        if f.name == "summary.json":
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            total += float((d.get("analysis") or {}).get("cost_usd_total") or 0.0)
        except Exception:
            continue
    return total


async def _execute_run(run: dict[str, str]) -> dict[str, Any]:
    from agents.orchestrator import run_pipeline

    spend = _cumulative_spend()
    if spend >= COST_CEILING_TOTAL_USD:
        raise SystemExit(
            f"COST CEILING: ${spend:.2f} >= ${COST_CEILING_TOTAL_USD:.2f} — refusing to start {run['name']}."
        )

    firm_id = await _firm_id_for_slug(run["firm_slug"])
    session_id = await _setup_session(
        firm_id, run["title"], run["brief"], run["name"], run["report_mode"]
    )
    print(
        f"\n=== run {run['name']} (mode={run['report_mode']}) "
        f"session={session_id} (cumulative ${spend:.2f}) ===",
        flush=True,
    )

    t0 = time.perf_counter()
    error_str: str | None = None
    try:
        await run_pipeline(session_id, run["brief"])
    except Exception as e:  # noqa: BLE001
        error_str = f"{type(e).__name__}: {e}\n{traceback.format_exc()[:3000]}"
    wall = time.perf_counter() - t0

    captured = await _capture(session_id)
    analysis = _analyze(captured, run.get("expected_framework"))

    record = {
        "run_name": run["name"],
        "report_mode": run["report_mode"],
        "firm_slug": run["firm_slug"],
        "firm_id": firm_id,
        "brief": run["brief"],
        "session_id": session_id,
        "wall_seconds": round(wall, 2),
        "error": error_str,
        "analysis": analysis,
        "captured": captured,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    fw = analysis["frameworks_status"]
    print(
        f"  wall={wall:.0f}s  cost=${analysis['cost_usd_total']:.4f}  "
        f"evidence={analysis['evidence_total']}  "
        f"two_by_two={'yes' if fw['two_by_two'] else 'no'}  "
        f"porters={'yes' if fw['porters_five_forces'] else 'no'}  "
        f"pyramid={analysis['pyramid']['present']}  mece={analysis['mece']['present']}  "
        f"error={'yes' if error_str else 'no'}",
        flush=True,
    )
    return record


async def _harvest_session(run_name: str, report_mode: str, session_id: str) -> dict[str, Any]:
    from db.connection import acquire

    async with acquire() as conn:
        sess = await conn.fetchrow(
            "SELECT firm_id, created_at FROM sessions WHERE id = $1::uuid", session_id
        )
    if not sess:
        raise SystemExit(f"session not found for harvest: {session_id}")
    captured = await _capture(session_id)
    run_cfg = next((r for r in _runs() if r["name"] == run_name), None)
    expected_fw = run_cfg.get("expected_framework") if run_cfg else None
    brief = run_cfg.get("brief") if run_cfg else ""
    analysis = _analyze(captured, expected_fw)
    return {
        "run_name": run_name,
        "report_mode": report_mode,
        "firm_slug": DEMO_FIRM_SLUG,
        "firm_id": str(sess["firm_id"]),
        "brief": brief,
        "session_id": session_id,
        "wall_seconds": 0.0,
        "harvested": True,
        "error": None,
        "analysis": analysis,
        "captured": captured,
        "captured_at": (
            sess["created_at"].isoformat()
            if sess and sess.get("created_at")
            else time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        ),
    }


# ---------------------------------------------------------------------------
# Headline assertions — W8 ship gate
# ---------------------------------------------------------------------------


def _headline_assertions(per_run: list[dict[str, Any]]) -> dict[str, Any]:
    a = next((r for r in per_run if r["run_name"] == "A_m_and_a"), None)
    b = next((r for r in per_run if r["run_name"] == "B_growth_strategy"), None)
    out: dict[str, Any] = {}

    if a is not None:
        fw = a.get("frameworks_status") or {}
        tbq = a.get("two_by_two_quality") or {}
        out["A_two_by_two_present"] = bool(fw.get("two_by_two"))
        out["A_two_by_two_items_ge_4"] = (tbq.get("items_count") or 0) >= 4
        out["A_two_by_two_items_all_have_citations"] = (
            (tbq.get("items_count") or 0) > 0
            and tbq.get("items_count") == tbq.get("items_with_citations")
        )
        out["A_pyramid_present"] = bool((a.get("pyramid") or {}).get("present"))
        out["A_mece_present"] = bool((a.get("mece") or {}).get("present"))

    if b is not None:
        fw = b.get("frameworks_status") or {}
        pq = b.get("porters_quality") or {}
        out["B_porters_present"] = bool(fw.get("porters_five_forces"))
        out["B_porters_all_five_populated"] = bool(pq.get("all_five_populated"))
        out["B_porters_all_five_with_evidence"] = (pq.get("forces_with_evidence") or 0) == 5
        out["B_pyramid_present"] = bool((b.get("pyramid") or {}).get("present"))
        out["B_mece_present"] = bool((b.get("mece") or {}).get("present"))

    # Pyramid + MECE pass rates across runs.
    if a is not None and b is not None:
        a_pyr_errs = (a.get("pyramid") or {}).get("errors", 0)
        b_pyr_errs = (b.get("pyramid") or {}).get("errors", 0)
        out["pyramid_at_least_one_zero_errors"] = (a_pyr_errs == 0) or (b_pyr_errs == 0)
        out["pyramid_other_at_most_2_errors"] = max(a_pyr_errs, b_pyr_errs) <= 2
        # MECE pass on top_3_reasons-equivalent path (key_reasons in our schema).
        def _mece_zero_on_key_reasons(rec: dict[str, Any]) -> bool:
            pf = (rec.get("mece") or {}).get("overlaps_per_field") or {}
            return int(pf.get("key_reasons", 0)) == 0
        out["mece_zero_on_key_reasons_at_least_one"] = (
            _mece_zero_on_key_reasons(a) or _mece_zero_on_key_reasons(b)
        )

    # Ship gate: required frameworks populated on both runs + both checks fired.
    out["headline_pass"] = bool(
        out.get("A_two_by_two_present")
        and out.get("A_two_by_two_items_ge_4")
        and out.get("A_two_by_two_items_all_have_citations")
        and out.get("B_porters_present")
        and out.get("B_porters_all_five_populated")
        and out.get("A_pyramid_present")
        and out.get("A_mece_present")
        and out.get("B_pyramid_present")
        and out.get("B_mece_present")
    )

    # W7 carry-forward signal — computed on Run A's analysis.
    if a is not None:
        out["week7_carry_forward"] = a.get("week7_carry_forward") or {}

    return out


def _per_run_summary(record: dict[str, Any]) -> dict[str, Any]:
    a = record.get("analysis") or {}
    rep = ((record.get("captured") or {}).get("report") or {}) or {}
    return {
        "run_name": record["run_name"],
        "report_mode": record["report_mode"],
        "session_id": record["session_id"],
        "wall_seconds": record["wall_seconds"],
        "cost_usd_total": a.get("cost_usd_total"),
        "evidence_total": a.get("evidence_total"),
        "diversity_counts": a.get("diversity_counts"),
        "firm_library_titles_cited": a.get("firm_library_titles_cited"),
        "frameworks_status": {
            "two_by_two": isinstance((a.get("frameworks_status") or {}).get("two_by_two"), dict),
            "porters_five_forces": isinstance((a.get("frameworks_status") or {}).get("porters_five_forces"), dict),
            "value_chain": isinstance((a.get("frameworks_status") or {}).get("value_chain"), dict),
        },
        "two_by_two_quality": a.get("two_by_two_quality"),
        "porters_quality": a.get("porters_quality"),
        "pyramid": a.get("pyramid"),
        "mece": a.get("mece"),
        "expected_framework": a.get("expected_framework"),
        "expected_framework_present": a.get("expected_framework_present"),
        "m_and_a_fields_present": a.get("m_and_a_fields_present"),
        "m_and_a_fields_absent": a.get("m_and_a_fields_absent"),
        "report_recommendation": (rep.get("recommendation") or "")[:480],
        "report_summary_preview": (rep.get("summary") or "")[:480],
        "week7_carry_forward": _w7_carry_forward(rep, a.get("frameworks_status") or {}),
        "error": record.get("error"),
    }


def _build_summary() -> dict[str, Any]:
    BENCH_ROOT.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, Any]] = []
    for run in _runs():
        f = BENCH_ROOT / f"{run['name']}.json"
        if not f.exists():
            continue
        record = json.loads(f.read_text(encoding="utf-8"))
        captured = record.get("captured") or {}
        if captured:
            record["analysis"] = _analyze(captured, run.get("expected_framework"))
        per = _per_run_summary(record)
        # Stash carry-forward inside the run record's analysis too, for the
        # headline aggregator on Run A.
        record["analysis"]["week7_carry_forward"] = per["week7_carry_forward"]
        runs.append(per)

    headline = _headline_assertions([
        # Pass the analysis dicts (not the trimmed per_run_summary) so
        # ``_headline_assertions`` sees both quality + pyramid/mece blocks.
        {
            **(json.loads((BENCH_ROOT / f"{run['name']}.json").read_text(encoding="utf-8")).get("analysis") or {}),
            "run_name": run["name"],
        }
        for run in _runs()
        if (BENCH_ROOT / f"{run['name']}.json").exists()
    ])
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "headline_assertions": headline,
        "headline_pass": bool(headline.get("headline_pass", False)),
        "n_runs": len(runs),
        "runs": runs,
    }


def _write_summary() -> None:
    summary = _build_summary()
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nsummary: {SUMMARY_PATH}", flush=True)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--runs", default="", help="Comma-separated subset of run names.")
    p.add_argument("--summary-only", action="store_true")
    p.add_argument(
        "--harvest",
        default="",
        help="Comma-separated RUN_NAME:SESSION_ID pairs to capture from existing sessions.",
    )
    return p.parse_args()


async def main_async(args: argparse.Namespace) -> None:
    if args.summary_only:
        _write_summary()
        return

    BENCH_ROOT.mkdir(parents=True, exist_ok=True)
    selected = _runs()
    if args.runs.strip():
        wanted = {r.strip() for r in args.runs.split(",") if r.strip()}
        selected = [r for r in selected if r["name"] in wanted]

    harvest_map: dict[str, str] = {}
    for entry in args.harvest.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            raise SystemExit(f"Bad --harvest entry {entry!r}: expected RUN_NAME:SESSION_ID")
        rn, sid = entry.split(":", 1)
        harvest_map[rn.strip()] = sid.strip()

    if not selected and not harvest_map:
        raise SystemExit(f"No runs selected from --runs={args.runs!r}")

    from db.connection import close_db, init_db

    await init_db()
    try:
        for run in _runs():
            if run["name"] not in harvest_map:
                continue
            print(
                f"\n=== {run['name']} HARVEST from session {harvest_map[run['name']]} ===",
                flush=True,
            )
            record = await _harvest_session(
                run["name"], run["report_mode"], harvest_map[run["name"]]
            )
            (BENCH_ROOT / f"{record['run_name']}.json").write_text(
                json.dumps(record, indent=2, default=str), encoding="utf-8"
            )

        for run in selected:
            if run["name"] in harvest_map:
                continue
            record = await _execute_run(run)
            (BENCH_ROOT / f"{record['run_name']}.json").write_text(
                json.dumps(record, indent=2, default=str), encoding="utf-8"
            )
    finally:
        await close_db()
    _write_summary()


def main() -> None:
    asyncio.run(main_async(_parse_args()))


if __name__ == "__main__":
    main()
