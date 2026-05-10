"""Phase 2 / Week 7 / Day 5 — cross-mode comparison demo runner.

Two engagement runs in the demo firm against the same TargetCo CIM:

  Run A (m_and_a):           report_mode=m_and_a_diligence
  Run B (growth_strategy):   report_mode=growth_strategy

Both runs use the same brief verbatim. The headline assertion is
structural, not phrasing: Run A's payload must validate against
``MAndADiligenceReportPayload`` (carrying the seven M&A-specific
top-level sections), Run B's must validate against
``GeneralReportPayload`` (which doesn't have those fields). If
either dispatcher misroutes, the run record exposes it.

Output:
  backend/eval_runs/week7_e2e/A_m_and_a.json
  backend/eval_runs/week7_e2e/B_growth_strategy.json
  backend/eval_runs/week7_e2e/summary.json   (committed)

Cost ceiling: $5 across both runs ($3 each per W7/D4 ceiling +
slack). Aborts the second run if the first blew the budget.

Usage::

    python tools/run_week7_e2e.py
    python tools/run_week7_e2e.py --runs A_m_and_a
    python tools/run_week7_e2e.py --summary-only
    python tools/run_week7_e2e.py --harvest A_m_and_a:<session_id>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
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


BRIEF = (
    "Conduct a diligence assessment of TargetCo Holdings, a UK "
    "industrial services group with £180m FY24 revenue. Quantify "
    "the deal opportunity, identify key risks, recommend deal "
    "structure and a valuation range."
)

DEMO_FIRM_SLUG = "argus-demo-boutique"

# M&A vocabulary terms we count in each memo for the informational
# (NOT gating) phrasing-side check. Per spec hard rule: structural
# divergence is the ship gate; word counts are noise.
M_AND_A_VOCAB_TERMS = (
    "synergy",
    "synergies",
    "valuation range",
    "walk-away",
    "walk away",
    "dis-synergy",
    "dis-synergies",
    "dissynergy",
    "day 1",
    "day one",
    "100 days",
    "100-day",
    "first 100 days",
    "earn-out",
    "earnout",
    "EV/EBITDA",
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


def _runs() -> list[dict[str, str]]:
    return [
        {
            "name": "A_m_and_a",
            "firm_slug": DEMO_FIRM_SLUG,
            "report_mode": "m_and_a_diligence",
            "title": "Week 7 E2E · TargetCo · M&A diligence",
        },
        {
            "name": "B_growth_strategy",
            "firm_slug": DEMO_FIRM_SLUG,
            "report_mode": "growth_strategy",
            "title": "Week 7 E2E · TargetCo · Growth strategy (comparator)",
        },
    ]


BENCH_ROOT = _REPO_ROOT / "backend" / "eval_runs" / "week7_e2e"
SUMMARY_PATH = BENCH_ROOT / "summary.json"

COST_CEILING_TOTAL_USD = 5.00


# ---------------------------------------------------------------------------
# DB helpers (mirror W6/D5 shape)
# ---------------------------------------------------------------------------


async def _firm_id_for_slug(slug: str) -> str:
    from db.connection import acquire

    async with acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM firms WHERE slug = $1", slug)
    if not row:
        raise SystemExit(f"firm slug not found: {slug!r} — run tools/seed_week5_demo.py first")
    return str(row["id"])


async def _setup_session(firm_id: str, title: str, brief: str, run_name: str, report_mode: str) -> str:
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
            json.dumps({"week7_e2e": True, "run_name": run_name}), firm_id,
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
            "SELECT status, pipeline_state, metadata, gap_report FROM sessions WHERE id = $1::uuid",
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


def _flatten_text(report: dict[str, Any] | None, cp: dict[str, Any]) -> str:
    """All textual content from the writer payload concatenated, for the
    informational-only M&A vocabulary count."""
    if not report:
        return ""
    parts: list[str] = []
    for k in ("recommendation", "summary", "caveats"):
        v = report.get(k)
        if isinstance(v, str):
            parts.append(v)
    for k in ("key_reasons", "risks", "counterarguments", "next_steps"):
        v = report.get(k)
        if isinstance(v, list):
            parts.extend(str(x) for x in v)
    parts.append(json.dumps(cp, ensure_ascii=False))
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def _analyze(captured: dict[str, Any]) -> dict[str, Any]:
    rep = captured.get("report") or {}
    cp = _parse_consulting_payload(rep)
    flat_text = _flatten_text(rep, cp).lower()

    # Top-level field presence (the structural wedge).
    m_and_a_fields_present = sorted(
        f for f in M_AND_A_TOP_LEVEL_FIELDS if isinstance(cp.get(f), (dict, list)) and cp.get(f)
    )
    m_and_a_fields_absent = sorted(
        f for f in M_AND_A_TOP_LEVEL_FIELDS if not (isinstance(cp.get(f), (dict, list)) and cp.get(f))
    )

    # Source diversity.
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

    # Phrasing-side counts (informational only).
    vocab_hits: dict[str, int] = {}
    total_hits = 0
    for term in M_AND_A_VOCAB_TERMS:
        n = len(re.findall(re.escape(term.lower()), flat_text))
        vocab_hits[term] = n
        total_hits += n

    cost = sum(float(c.get("usd_cost") or 0) for c in (captured.get("llm_calls") or []))
    return {
        "report_recommendation": rep.get("recommendation") or "",
        "report_summary_first_240": (rep.get("summary") or "")[:240],
        "evidence_total": len(captured.get("evidence_objects") or []),
        "diversity_counts": dict(diversity),
        "firm_library_titles_cited": dict(firm_lib_titles),
        "m_and_a_fields_present": m_and_a_fields_present,
        "m_and_a_fields_absent": m_and_a_fields_absent,
        "vocab_hits": vocab_hits,
        "vocab_total": total_hits,
        "cost_usd_total": round(cost, 4),
    }


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
        firm_id, run["title"], BRIEF, run["name"], run["report_mode"]
    )
    print(
        f"\n=== run {run['name']} (mode={run['report_mode']}) "
        f"session={session_id} (cumulative ${spend:.2f}) ===",
        flush=True,
    )

    t0 = time.perf_counter()
    error_str: str | None = None
    try:
        await run_pipeline(session_id, BRIEF)
    except Exception as e:  # noqa: BLE001
        error_str = f"{type(e).__name__}: {e}\n{traceback.format_exc()[:3000]}"
    wall = time.perf_counter() - t0

    captured = await _capture(session_id)
    analysis = _analyze(captured)

    record = {
        "run_name": run["name"],
        "report_mode": run["report_mode"],
        "firm_slug": run["firm_slug"],
        "firm_id": firm_id,
        "brief": BRIEF,
        "session_id": session_id,
        "wall_seconds": round(wall, 2),
        "error": error_str,
        "analysis": analysis,
        "captured": captured,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    print(
        f"  wall={wall:.0f}s  cost=${analysis['cost_usd_total']:.4f}  "
        f"evidence={analysis['evidence_total']}  "
        f"m_and_a_fields_present={len(analysis['m_and_a_fields_present'])}/7  "
        f"vocab_hits={analysis['vocab_total']}  "
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
    analysis = _analyze(captured)
    return {
        "run_name": run_name,
        "report_mode": report_mode,
        "firm_slug": DEMO_FIRM_SLUG,
        "firm_id": str(sess["firm_id"]),
        "brief": BRIEF,
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
# Headline structural assertions for summary.json
# ---------------------------------------------------------------------------


def _headline_assertions(per_run: list[dict[str, Any]]) -> dict[str, Any]:
    a = next((r for r in per_run if r["run_name"] == "A_m_and_a"), None)
    b = next((r for r in per_run if r["run_name"] == "B_growth_strategy"), None)

    out: dict[str, Any] = {}
    if a is not None:
        a_fields = a.get("m_and_a_fields_present") or []
        out["A_mode_is_m_and_a_diligence"] = a.get("report_mode") == "m_and_a_diligence"
        out["A_has_m_and_a_top_level_fields"] = len(a_fields) >= 5
        out["A_has_valuation_range"] = "valuation_range" in a_fields
        out["A_has_synergy_estimate"] = "synergy_estimate" in a_fields
        out["A_has_integration_plan"] = "integration_plan" in a_fields
    if b is not None:
        b_fields = b.get("m_and_a_fields_present") or []
        out["B_mode_is_growth_strategy"] = b.get("report_mode") == "growth_strategy"
        # The schema-level proof: B's GeneralReportPayload doesn't carry
        # any of the M&A-specific top-level sections.
        out["B_has_no_m_and_a_top_level_fields"] = len(b_fields) == 0

    if a is not None and b is not None:
        a_fields = set(a.get("m_and_a_fields_present") or [])
        b_fields = set(b.get("m_and_a_fields_present") or [])
        diff = a_fields - b_fields
        out["structural_field_divergence_count"] = len(diff)
        out["A_unique_top_level_fields"] = sorted(diff)
        out["headline_pass"] = (
            out.get("A_mode_is_m_and_a_diligence")
            and out.get("B_mode_is_growth_strategy")
            and out.get("A_has_m_and_a_top_level_fields")
            and out.get("B_has_no_m_and_a_top_level_fields")
            and len(diff) >= 5
        )
    return out


def _per_run_summary(record: dict[str, Any]) -> dict[str, Any]:
    a = record.get("analysis") or {}
    rep = ((record.get("captured") or {}).get("report") or {}) or {}
    cp = _parse_consulting_payload(rep)
    return {
        "run_name": record["run_name"],
        "report_mode": record["report_mode"],
        "session_id": record["session_id"],
        "wall_seconds": record["wall_seconds"],
        "cost_usd_total": a.get("cost_usd_total"),
        "evidence_total": a.get("evidence_total"),
        "diversity_counts": a.get("diversity_counts"),
        "firm_library_titles_cited": a.get("firm_library_titles_cited"),
        "m_and_a_fields_present": a.get("m_and_a_fields_present"),
        "m_and_a_fields_absent": a.get("m_and_a_fields_absent"),
        "vocab_hits": a.get("vocab_hits"),
        "vocab_total": a.get("vocab_total"),
        "report_recommendation": (rep.get("recommendation") or "")[:480],
        "report_summary_preview": (rep.get("summary") or "")[:480],
        # Tiny excerpt of valuation_range.base for the wrap-up doc.
        "valuation_base_excerpt": (cp.get("valuation_range") or {}).get("base")
            if isinstance(cp.get("valuation_range"), dict) else None,
        "first_walk_away_trigger": (
            ((cp.get("deal_structure_implications") or {}).get("walk_away_triggers") or [None])[0]
            if isinstance(cp.get("deal_structure_implications"), dict) else None
        ),
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
        # Re-analyse from captured payload so summary heuristics reflect
        # the latest helper logic on rebuild.
        captured = record.get("captured") or {}
        if captured:
            record["analysis"] = _analyze(captured)
        runs.append(_per_run_summary(record))

    headline = _headline_assertions(runs)
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
        "--harvest", default="",
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
            print(f"\n=== {run['name']} HARVEST from session {harvest_map[run['name']]} ===", flush=True)
            record = await _harvest_session(run["name"], run["report_mode"], harvest_map[run["name"]])
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
