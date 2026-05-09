"""Phase 2 / Week 6 / Day 5 — end-to-end demo runner for layered modes.

Two pipeline runs in the demo firm:

  Run A (with_override):  report_mode=boutique_pricing_review
                          (firm-defined override seeded by
                          tools/seed_week6_demo.py).
  Run B (built_in):       report_mode=growth_strategy
                          (the closest built-in; no firm override
                          touches this mode in the demo firm).

For each run we capture: total claims, grounded claims,
firm_library citation count, planner branches actually emitted by
the planner, writer recommendation/summary text, presence of the
overlay phrasing (2x2, 90-day roadmap, named owners, sensitivity
levels), wall time, and cost.

Output:
  - backend/eval_runs/week6_e2e/A_with_override.json
  - backend/eval_runs/week6_e2e/B_built_in.json
  - backend/eval_runs/week6_e2e/summary.json (committed)

Usage::

    python tools/run_week6_e2e.py
    python tools/run_week6_e2e.py --runs A_with_override
    python tools/run_week6_e2e.py --summary-only
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
    "Develop a pricing strategy for a UK retail business with 4 segments "
    "and £200M revenue. Identify price actions and an implementation "
    "roadmap."
)

DEMO_FIRM_SLUG = "argus-demo-boutique"


def _runs() -> list[dict[str, str]]:
    return [
        {
            "name": "A_with_override",
            "firm_slug": DEMO_FIRM_SLUG,
            "report_mode": "boutique_pricing_review",
            "title": "Week 6 E2E · Pricing strategy · WITH firm override",
        },
        {
            "name": "B_built_in",
            "firm_slug": DEMO_FIRM_SLUG,
            "report_mode": "growth_strategy",
            "title": "Week 6 E2E · Pricing strategy · WITHOUT firm override",
        },
    ]


BENCH_ROOT = _REPO_ROOT / "backend" / "eval_runs" / "week6_e2e"
SUMMARY_PATH = BENCH_ROOT / "summary.json"


# ---------------------------------------------------------------------------
# Overlay-phrasing detectors
# ---------------------------------------------------------------------------

# Each detector is a regex over the lower-cased writer text. They proxy for
# "did the writer overlay land?" — the override declares specific phrases
# the writer should produce.

_PHRASE_2X2 = re.compile(r"\b2\s*x\s*2\b|\b2x2\b|two[\s-]by[\s-]two", re.I)
_PHRASE_90D = re.compile(r"90[\s-]?day(?:s)?\s+(?:implementation\s+)?roadmap|90[\s-]day\s+plan", re.I)
_PHRASE_OWNERS = re.compile(r"named\s+owners?|owner[:\s]|by\s+\w+\s+(team|director|lead|head)", re.I)
_PHRASE_SENS = re.compile(r"conservative\s*[,/]\s*base\s*[,/]\s*aggressive|conservative\b.*\bbase\b.*\baggressive\b|sensitivit", re.I)

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
    r"\d+-(?:year|month|week|quarter)|"
    r"by\s+(?:end\s+of\s+|H[12]\s+|Q[1-4]\s+)?\d{4}|"
    r"over\s+\d+\s+(?:months?|years?|quarters?))\b",
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


async def _setup_session(firm_id: str, title: str, brief: str, run_name: str, report_mode: str) -> str:
    from db.connection import acquire

    session_id = str(uuid.uuid4())
    metadata = {"week6_e2e": True, "run_name": run_name}
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
            session_id, title, brief, report_mode, json.dumps(metadata), firm_id,
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
    from db.connection import acquire

    async with acquire() as conn:
        report_row = await conn.fetchrow(
            """
            SELECT id, recommendation, confidence_level, summary,
                   key_reasons, risks, counterarguments, next_steps,
                   raw_output, caveats, evidence_count, unsupported_claim_count,
                   consulting_payload, claim_support, created_at
            FROM reports
            WHERE session_id = $1::uuid
            """,
            session_id,
        )
        sess_meta_row = await conn.fetchrow(
            "SELECT metadata FROM sessions WHERE id = $1::uuid",
            session_id,
        )
        # planner output is in agent_outputs.agent_name='planner'
        planner_row = await conn.fetchrow(
            """
            SELECT output FROM agent_outputs
            WHERE session_id = $1::uuid AND agent_name = 'planner'
            ORDER BY created_at DESC LIMIT 1
            """,
            session_id,
        )
        claim_rows = await conn.fetch(
            """
            SELECT claim_id, claim_text, evidence_object_ids, support_type,
                   verifier_verdict, contradiction_flag, weak_flag,
                   ensemble_verdict
            FROM claim_support_rows
            WHERE session_id = $1::uuid
            """,
            session_id,
        )
        evidence_rows = await conn.fetch(
            """
            SELECT id, source_url, source_title, source_type, claim, quote, metadata
            FROM evidence_objects
            WHERE session_id = $1::uuid
            """,
            session_id,
        )
        llm_rows = await conn.fetch(
            """
            SELECT task_kind, prompt_tokens, completion_tokens, total_tokens, usd_cost
            FROM llm_calls
            WHERE session_id = $1::uuid
            ORDER BY id ASC
            """,
            session_id,
        )

    sess_meta: dict[str, Any] = {}
    if sess_meta_row and sess_meta_row.get("metadata") is not None:
        sm = sess_meta_row["metadata"]
        sess_meta = json.loads(sm) if isinstance(sm, str) else dict(sm)

    planner_payload: dict[str, Any] = {}
    if planner_row and planner_row.get("output"):
        out = planner_row["output"]
        planner_payload = json.loads(out) if isinstance(out, str) else dict(out)

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
        "session_metadata": sess_meta,
        "planner_payload": planner_payload,
    }


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


CUSTOM_BRANCHES = {
    "competitor_price_anchor_analysis",
    "willingness_to_pay_evidence",
    "price_architecture_review",
    "implementation_friction_audit",
}
BUILT_IN_BRANCHES = {"market", "capabilities"}


def _planner_branch_set(planner_payload: dict[str, Any]) -> set[str]:
    """Extract the per-task source_priorities + question keywords as a
    rough branch fingerprint. The planner doesn't emit explicit branch
    labels — branches show up in the research orchestrator's
    branch_trace metadata. So here we look at task questions for
    custom-branch keywords."""
    tasks = planner_payload.get("tasks") or []
    text = " ".join(str(t.get("question", "")) for t in tasks if isinstance(t, dict)).lower()
    found: set[str] = set()
    for b in CUSTOM_BRANCHES | BUILT_IN_BRANCHES:
        # Match the branch slug verbatim or its individual word components.
        words = b.replace("_", " ").lower()
        if b in text or words in text:
            found.add(b)
    return found


def _research_branches(session_metadata: dict[str, Any]) -> list[str]:
    """The orchestrator persists `research_branches` after planning. Day 4
    wired this from the resolved mode's required_branches."""
    rb = session_metadata.get("research_branches")
    if isinstance(rb, list):
        return [str(x) for x in rb if str(x).strip()]
    return []


def _analyze(captured: dict[str, Any]) -> dict[str, Any]:
    ev_by_id: dict[str, dict[str, Any]] = {
        str(e["id"]): e for e in (captured.get("evidence_objects") or [])
    }
    rows = captured.get("claim_support_rows") or []

    diversity_counts: Counter[str] = Counter()
    for ev in ev_by_id.values():
        st = (ev.get("source_type") or "").lower()
        diversity_counts[st or "unknown"] += 1

    grounded_rows: list[dict[str, Any]] = []
    library_citation_count = 0
    library_items_cited: Counter[str] = Counter()

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
        library_citation_count += len(library_hits)
        for c in library_hits:
            md = c.get("metadata") or {}
            t = str(md.get("firm_library_title") or "")
            if t:
                library_items_cited[t] += 1

    report = captured.get("report") or {}
    rec = (report.get("recommendation") or "")
    summ = (report.get("summary") or "")
    rec_text = " ".join(s for s in (rec, summ) if s)
    next_steps = report.get("next_steps") or []
    if isinstance(next_steps, list):
        rec_text += " " + " ".join(str(x) for x in next_steps)
    full_text = rec_text  # The phrases we look for typically live here.

    overlay_signals = {
        "phrase_2x2": bool(_PHRASE_2X2.search(full_text)),
        "phrase_90day_roadmap": bool(_PHRASE_90D.search(full_text)),
        "phrase_named_owners": bool(_PHRASE_OWNERS.search(full_text)),
        "phrase_sensitivity_levels": bool(_PHRASE_SENS.search(full_text)),
    }

    planner_branches = _planner_branch_set(captured.get("planner_payload") or {})
    research_branches = _research_branches(captured.get("session_metadata") or {})

    cost = sum(float(r.get("usd_cost") or 0) for r in (captured.get("llm_calls") or []))

    return {
        "total_claims": len(rows),
        "grounded_claims": len(grounded_rows),
        "firm_library_citation_count": library_citation_count,
        "firm_library_items_cited": dict(library_items_cited),
        "diversity_counts": dict(diversity_counts),
        "rec_numeric_tokens": len(NUMERIC_RE.findall(full_text)),
        "rec_time_bound_phrases": len(TIME_BOUND_RE.findall(full_text)),
        "overlay_signals": overlay_signals,
        "overlay_signal_count": sum(overlay_signals.values()),
        "planner_custom_branches_present": sorted(planner_branches & CUSTOM_BRANCHES),
        "planner_built_in_branches_present": sorted(planner_branches & BUILT_IN_BRANCHES),
        "research_branches_persisted": research_branches,
        "cost_usd_total": round(cost, 4),
    }


# ---------------------------------------------------------------------------
# Run loop
# ---------------------------------------------------------------------------


async def _execute_run(run: dict[str, str]) -> dict[str, Any]:
    from agents.orchestrator import run_pipeline

    firm_id = await _firm_id_for_slug(run["firm_slug"])
    session_id = await _setup_session(
        firm_id, run["title"], BRIEF, run["name"], run["report_mode"]
    )
    print(
        f"\n=== run {run['name']} (mode={run['report_mode']}) "
        f"session={session_id} ===",
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
        f"  wall={wall:.1f}s  cost=${analysis['cost_usd_total']:.4f}  "
        f"claims={analysis['total_claims']}  grounded={analysis['grounded_claims']}  "
        f"firm_lib={analysis['firm_library_citation_count']}  "
        f"overlay_signals={analysis['overlay_signal_count']}/4  "
        f"planner_custom={len(analysis['planner_custom_branches_present'])}/4",
        flush=True,
    )
    if error_str:
        print(f"  ERROR: {error_str[:240]}", flush=True)
    return record


def _per_run_summary(record: dict[str, Any]) -> dict[str, Any]:
    a = record.get("analysis") or {}
    rep = ((record.get("captured") or {}).get("report") or {}) or {}
    return {
        "run_name": record["run_name"],
        "report_mode": record["report_mode"],
        "session_id": record["session_id"],
        "wall_seconds": record["wall_seconds"],
        "cost_usd_total": a.get("cost_usd_total"),
        "total_claims": a.get("total_claims"),
        "grounded_claims": a.get("grounded_claims"),
        "firm_library_citation_count": a.get("firm_library_citation_count"),
        "firm_library_items_cited": a.get("firm_library_items_cited"),
        "diversity_counts": a.get("diversity_counts"),
        "overlay_signals": a.get("overlay_signals"),
        "overlay_signal_count": a.get("overlay_signal_count"),
        "planner_custom_branches_present": a.get("planner_custom_branches_present"),
        "planner_built_in_branches_present": a.get("planner_built_in_branches_present"),
        "research_branches_persisted": a.get("research_branches_persisted"),
        "rec_numeric_tokens": a.get("rec_numeric_tokens"),
        "rec_time_bound_phrases": a.get("rec_time_bound_phrases"),
        "recommendation_preview": (
            (rep.get("recommendation") or rep.get("summary") or "")[:600]
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

    a = next((r for r in runs if r["run_name"] == "A_with_override"), None)
    b = next((r for r in runs if r["run_name"] == "B_built_in"), None)

    headline_assertions = {}
    if a is not None:
        headline_assertions["A_planner_emits_custom_branches"] = (
            len(a.get("planner_custom_branches_present") or []) >= 3
        )
        headline_assertions["A_writer_overlay_lands"] = (
            (a.get("overlay_signal_count") or 0) >= 2
        )
    if b is not None:
        headline_assertions["B_planner_avoids_custom_branches"] = (
            len(b.get("planner_custom_branches_present") or []) == 0
        )
        headline_assertions["B_writer_overlay_does_not_land"] = (
            (b.get("overlay_signal_count") or 0) <= 1
        )

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "headline_assertions": headline_assertions,
        "headline_pass": all(headline_assertions.values()) if headline_assertions else False,
        "n_runs": len(runs),
        "runs": runs,
    }


def _write_summary() -> None:
    summary = _build_summary()
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nsummary: {SUMMARY_PATH}", flush=True)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--runs", default="", help="Comma-separated run names")
    p.add_argument("--summary-only", action="store_true")
    p.add_argument(
        "--harvest",
        default="",
        help=(
            "Comma-separated RUN_NAME:SESSION_ID pairs to capture from an "
            "already-completed pipeline run instead of executing a fresh "
            "one. Useful when the runner crashed after the LLM work but "
            "before _capture finished — re-running would burn cost twice."
        ),
    )
    return p.parse_args()


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
        # Harvest first — cheap, no LLM cost.
        for run in _runs():
            if run["name"] not in harvest_map:
                continue
            print(f"\n=== {run['name']} HARVEST from session {harvest_map[run['name']]} ===", flush=True)
            record = await _harvest_session(run["name"], run["report_mode"], harvest_map[run["name"]])
            a = record["analysis"]
            print(
                f"  cost=${a['cost_usd_total']:.4f}  "
                f"claims={a['total_claims']}  grounded={a['grounded_claims']}  "
                f"firm_lib={a['firm_library_citation_count']}  "
                f"overlay_signals={a['overlay_signal_count']}/4  "
                f"planner_custom={len(a['planner_custom_branches_present'])}/4",
                flush=True,
            )
            out_path = BENCH_ROOT / f"{record['run_name']}.json"
            out_path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
            print(f"  -> wrote {out_path.name}", flush=True)

        # Fresh runs for whatever wasn't harvested.
        for run in selected:
            if run["name"] in harvest_map:
                continue
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
