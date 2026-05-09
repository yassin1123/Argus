"""Phase 2 / Week 5 / Day 5 — end-to-end firm-library demo runner.

Three pipeline runs:

  A_with_library    — M&A target screen brief, in the demo firm (4 playbooks).
  B_with_library    — Growth strategy brief, in the demo firm.
  A_no_library      — Same M&A brief in the baseline firm (zero firm content).

For each run we capture: total claims, grounded claims, source diversity
(with the firm_library bucket from ``backend/core/firm_library/diversity.py``),
recommendation specificity (numeric tokens, time-bound phrases),
firm_library citation count, which library items got cited most, wall
time, and cost.

Output:
  - ``backend/eval_runs/week5_e2e/{run_name}.json``
  - ``backend/eval_runs/week5_e2e/summary.json`` (committed)

Usage::

    python tools/run_week5_e2e.py
    python tools/run_week5_e2e.py --runs A_with_library
    python tools/run_week5_e2e.py --summary-only
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

# ---------------------------------------------------------------------------
# Run definitions — keep verbatim per Day 5 spec for reproducibility
# ---------------------------------------------------------------------------

BRIEF_A = (
    "Generate a target screen for a UK retail-sector acquisition target with "
    "€100–500M revenue. Focus on omnichannel readiness and operational "
    "efficiency."
)
BRIEF_B = (
    "Develop a 3-year growth strategy for a regional UK retailer entering "
    "the US market. Cover entry mode options, market attractiveness, and "
    "risk profile."
)

DEMO_FIRM_SLUG = "argus-demo-boutique"
BASELINE_FIRM_SLUG = "argus-baseline"


def _runs() -> list[dict[str, str]]:
    return [
        {
            "name": "A_with_library",
            "firm_slug": DEMO_FIRM_SLUG,
            "brief": BRIEF_A,
            "title": "Week 5 E2E · M&A target screen · with-library",
        },
        {
            "name": "B_with_library",
            "firm_slug": DEMO_FIRM_SLUG,
            "brief": BRIEF_B,
            "title": "Week 5 E2E · Growth strategy · with-library",
        },
        {
            "name": "A_no_library",
            "firm_slug": BASELINE_FIRM_SLUG,
            "brief": BRIEF_A,
            "title": "Week 5 E2E · M&A target screen · baseline (no library)",
        },
    ]


BENCH_ROOT = _REPO_ROOT / "backend" / "eval_runs" / "week5_e2e"
SUMMARY_PATH = BENCH_ROOT / "summary.json"

# ---------------------------------------------------------------------------
# Recommendation specificity heuristics (same numeric regex as Week 3)
# ---------------------------------------------------------------------------

NUMERIC_RE = re.compile(
    r"(?:\b\d+(?:\.\d+)?\s*%|"
    r"[€$£]\s*\d+(?:[\.,]\d+)*[KkMmBb]?|"
    r"\b\d+(?:[\.,]\d+)?\s*(?:million|billion|m|bn|k)\b|"
    r"\b\d+\s*(?:month|months|year|years|day|days|week|weeks|quarter|quarters|q[1-4])\b|"
    r"\b\d+\b)",
    re.IGNORECASE,
)

TIME_BOUND_RE = re.compile(
    r"\b(?:by\s+\w+\s+\d{4}|within\s+\d+\s+(?:months?|years?|quarters?|days?|weeks?)|"
    r"in\s+the\s+(?:first|second|third|fourth)\s+(?:quarter|year|half)|"
    r"\d+-(?:year|month|week|quarter)|"
    r"by\s+(?:end\s+of\s+|H[12]\s+|Q[1-4]\s+)?\d{4}|"
    r"\bover\s+\d+\s+(?:months?|years?|quarters?))\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _firm_id_for_slug(slug: str) -> str:
    from db.connection import acquire

    async with acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM firms WHERE slug = $1", slug)
    if not row:
        raise SystemExit(f"firm slug not found: {slug!r} — run tools/seed_week5_demo.py first")
    return str(row["id"])


async def _setup_session(firm_id: str, title: str, brief: str, run_name: str) -> str:
    """Create a fresh session in the given firm and seed metadata.

    Goes direct to SQL because ``db.queries.create_session`` doesn't take
    firm_id and ``sessions.firm_id`` is NOT NULL post-migration 024.
    """
    from db.connection import acquire

    session_id = str(uuid.uuid4())
    metadata = {"week5_e2e": True, "run_name": run_name}
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sessions (
                id, title, query, status, report_mode, pipeline_state,
                metadata, gap_report, intake_questions, intake_answers,
                firm_id, updated_at
            ) VALUES (
                $1::uuid, $2, $3, 'draft', 'general', 'idle',
                $4::jsonb, '{}'::jsonb, '[]'::jsonb, '[]'::jsonb,
                $5::uuid, NOW()
            )
            """,
            session_id,
            title,
            brief,
            json.dumps(metadata),
            firm_id,
        )
    return session_id


def _normalize_value(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, uuid.UUID):
        return str(v)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, list):
        return [_normalize_value(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _normalize_value(x) for k, x in v.items()}
    try:
        json.dumps(v)
        return v
    except TypeError:
        return str(v)


def _row_to_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    return {k: _normalize_value(v) for k, v in dict(row).items()}


async def _capture(session_id: str) -> dict[str, Any]:
    """Pull report + claim_support_rows + evidence_objects + cost ledger."""
    from db.connection import acquire

    async with acquire() as conn:
        report_row = await conn.fetchrow(
            """
            SELECT id, recommendation, confidence_level, summary,
                   key_reasons, risks, counterarguments, next_steps, sources,
                   raw_output, caveats, evidence_count, unsupported_claim_count,
                   consulting_payload, claim_support, created_at
            FROM reports
            WHERE session_id = $1::uuid
            """,
            session_id,
        )
        claim_rows = await conn.fetch(
            """
            SELECT claim_id, claim_text, evidence_object_ids, support_type,
                   verifier_verdict, contradiction_flag, weak_flag,
                   entailment_score, nli_label, nli_confidence,
                   numeric_overlap_score, entity_overlap_score,
                   ensemble_verdict, ensemble_reason
            FROM claim_support_rows
            WHERE session_id = $1::uuid
            """,
            session_id,
        )
        evidence_rows = await conn.fetch(
            """
            SELECT id, source_url, source_title, source_type,
                   claim, quote, source_score, metadata
            FROM evidence_objects
            WHERE session_id = $1::uuid
            """,
            session_id,
        )
        llm_rows = await conn.fetch(
            """
            SELECT task_kind, model, prompt_tokens, completion_tokens,
                   total_tokens, usd_cost, latency_ms, success, error_kind
            FROM llm_calls
            WHERE session_id = $1::uuid
            ORDER BY id ASC
            """,
            session_id,
        )

    # Decode metadata jsonb on evidence_objects (asyncpg returns str for jsonb).
    ev_clean: list[dict[str, Any]] = []
    for r in evidence_rows:
        d = _row_to_dict(r)
        m = d.get("metadata")
        if isinstance(m, str):
            try:
                d["metadata"] = json.loads(m)
            except Exception:
                d["metadata"] = {}
        elif not isinstance(m, dict):
            d["metadata"] = {}
        ev_clean.append(d)

    return {
        "session_id": session_id,
        "report": _row_to_dict(report_row) if report_row else None,
        "claim_support_rows": [_row_to_dict(r) for r in claim_rows],
        "evidence_objects": ev_clean,
        "llm_calls": [_row_to_dict(r) for r in llm_rows],
    }


# ---------------------------------------------------------------------------
# Analysis — the headline metrics
# ---------------------------------------------------------------------------


def _analyze(captured: dict[str, Any]) -> dict[str, Any]:
    """Compute the metrics the wrap-up doc needs.

    Headline assertions:
      - ``firm_library_citation_count``: total citations to firm_library evidence
      - ``firm_library_items_cited``: how many distinct firm_content_ids show up
      - ``library_grounded_claims``: claims with at least one firm_library citation
    """
    ev_by_id: dict[str, dict[str, Any]] = {
        str(e["id"]): e for e in (captured.get("evidence_objects") or [])
    }
    rows = captured.get("claim_support_rows") or []

    # Source-diversity buckets — mirrors backend/core/firm_library/diversity.py.
    diversity_counts: Counter[str] = Counter()
    for ev in ev_by_id.values():
        st = (ev.get("source_type") or "").lower()
        if st == "firm_library":
            diversity_counts["firm_library"] += 1
        elif st == "sec_filing":
            diversity_counts["sec_filings"] += 1
        elif st in ("transcript", "earnings_transcript"):
            diversity_counts["transcripts"] += 1
        elif st in ("ch_filing", "companies_house"):
            diversity_counts["ch_filings"] += 1
        elif st == "news":
            diversity_counts["news"] += 1
        else:
            diversity_counts[st or "unknown"] += 1

    grounded_rows: list[dict[str, Any]] = []
    library_grounded_rows: list[dict[str, Any]] = []
    library_citation_count = 0
    library_items_cited: Counter[str] = Counter()
    library_titles_cited: Counter[str] = Counter()
    library_categories_cited: Counter[str] = Counter()

    for row in rows:
        eo_ids = row.get("evidence_object_ids") or []
        if isinstance(eo_ids, str):
            try:
                eo_ids = json.loads(eo_ids)
            except Exception:
                eo_ids = []
        eo_ids = [str(x) for x in eo_ids if x]
        if not eo_ids:
            continue
        cited = [ev_by_id.get(eid) for eid in eo_ids if eid in ev_by_id]
        cited = [c for c in cited if c]
        if not cited:
            continue
        grounded_rows.append(row)
        library_hits = [c for c in cited if (c.get("source_type") or "").lower() == "firm_library"]
        if library_hits:
            library_grounded_rows.append(row)
        library_citation_count += len(library_hits)
        for c in library_hits:
            md = c.get("metadata") or {}
            fc_id = str(md.get("firm_content_id") or "")
            if fc_id:
                library_items_cited[fc_id] += 1
                library_titles_cited[str(md.get("firm_library_title") or "")] += 1
                library_categories_cited[str(md.get("category") or "")] += 1

    report = captured.get("report") or {}
    rec_text = " ".join(
        s for s in (
            (report.get("recommendation") or ""),
            (report.get("summary") or ""),
            " ".join((report.get("key_reasons") or []) if isinstance(report.get("key_reasons"), list) else []),
            " ".join((report.get("next_steps") or []) if isinstance(report.get("next_steps"), list) else []),
        )
        if s
    )
    n_numbers = len(NUMERIC_RE.findall(rec_text))
    n_time_bound = len(TIME_BOUND_RE.findall(rec_text))

    cost = sum(float(r.get("usd_cost") or 0) for r in (captured.get("llm_calls") or []))

    return {
        "total_claims": len(rows),
        "grounded_claims": len(grounded_rows),
        "library_grounded_claims": len(library_grounded_rows),
        "firm_library_citation_count": library_citation_count,
        "firm_library_items_cited": len(library_items_cited),
        "firm_library_top_items": library_titles_cited.most_common(10),
        "firm_library_categories_cited": dict(library_categories_cited),
        "diversity_counts": dict(diversity_counts),
        "evidence_objects_total": len(ev_by_id),
        "rec_numeric_tokens": n_numbers,
        "rec_time_bound_phrases": n_time_bound,
        "cost_usd_total": round(cost, 4),
    }


# ---------------------------------------------------------------------------
# Run loop
# ---------------------------------------------------------------------------


async def _execute_run(run: dict[str, str]) -> dict[str, Any]:
    from agents.orchestrator import run_pipeline

    firm_id = await _firm_id_for_slug(run["firm_slug"])
    session_id = await _setup_session(firm_id, run["title"], run["brief"], run["name"])
    print(
        f"\n=== run {run['name']} (firm={run['firm_slug']}) "
        f"session={session_id} ===",
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
    analysis = _analyze(captured)

    record = {
        "run_name": run["name"],
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

    print(
        f"  wall={wall:.1f}s  cost=${analysis['cost_usd_total']:.4f}  "
        f"claims={analysis['total_claims']}  grounded={analysis['grounded_claims']}  "
        f"firm_lib_cites={analysis['firm_library_citation_count']}  "
        f"firm_lib_items={analysis['firm_library_items_cited']}",
        flush=True,
    )
    if error_str:
        print(f"  ERROR: {error_str[:240]}", flush=True)

    return record


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------


def _per_run_summary(record: dict[str, Any]) -> dict[str, Any]:
    a = record.get("analysis") or {}
    rep = ((record.get("captured") or {}).get("report") or {}) or {}
    return {
        "run_name": record["run_name"],
        "firm_slug": record["firm_slug"],
        "session_id": record["session_id"],
        "brief": record["brief"],
        "wall_seconds": record["wall_seconds"],
        "cost_usd_total": a.get("cost_usd_total"),
        "total_claims": a.get("total_claims"),
        "grounded_claims": a.get("grounded_claims"),
        "library_grounded_claims": a.get("library_grounded_claims"),
        "firm_library_citation_count": a.get("firm_library_citation_count"),
        "firm_library_items_cited": a.get("firm_library_items_cited"),
        "firm_library_top_items": a.get("firm_library_top_items"),
        "firm_library_categories_cited": a.get("firm_library_categories_cited"),
        "diversity_counts": a.get("diversity_counts"),
        "rec_numeric_tokens": a.get("rec_numeric_tokens"),
        "rec_time_bound_phrases": a.get("rec_time_bound_phrases"),
        "recommendation_preview": (
            (rep.get("recommendation") or rep.get("summary") or "")[:480]
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
        runs.append(_per_run_summary(record))

    headline_passes = []
    for r in runs:
        if r["run_name"].endswith("_with_library"):
            headline_passes.append(int((r.get("firm_library_citation_count") or 0) >= 1))
    headline_assert = bool(headline_passes) and all(headline_passes)

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "headline_assertion_pass": headline_assert,
        "headline_assertion_text": (
            "Both with-library engagements produce >= 1 firm_library citation."
        ),
        "n_runs": len(runs),
        "runs": runs,
    }


def _write_summary() -> None:
    summary = _build_summary()
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nsummary: {SUMMARY_PATH}", flush=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--runs",
        default="",
        help=(
            "Comma-separated subset of run names to execute "
            "(default: all three)."
        ),
    )
    p.add_argument("--summary-only", action="store_true")
    return p.parse_args()


async def main_async(args: argparse.Namespace) -> None:
    if args.summary_only:
        _write_summary()
        return

    print("ARGUS_USE_ENSEMBLE_VERDICT =", os.getenv("ARGUS_USE_ENSEMBLE_VERDICT"))
    import core.feature_flags as ff

    if not ff.USE_ENSEMBLE_VERDICT:
        import importlib

        importlib.reload(ff)
    print(f"  USE_ENSEMBLE_VERDICT (resolved) = {ff.USE_ENSEMBLE_VERDICT}", flush=True)

    BENCH_ROOT.mkdir(parents=True, exist_ok=True)

    selected = _runs()
    if args.runs.strip():
        wanted = {r.strip() for r in args.runs.split(",") if r.strip()}
        selected = [r for r in selected if r["name"] in wanted]
    if not selected:
        raise SystemExit(f"No runs selected from --runs={args.runs!r}")

    from db.connection import close_db, init_db

    await init_db()
    try:
        for run in selected:
            record = await _execute_run(run)
            out_path = BENCH_ROOT / f"{record['run_name']}.json"
            out_path.write_text(
                json.dumps(record, indent=2, default=str), encoding="utf-8"
            )
            print(f"  -> wrote {out_path.name}", flush=True)
    finally:
        await close_db()
    _write_summary()


def main() -> None:
    asyncio.run(main_async(_parse_args()))


if __name__ == "__main__":
    main()
