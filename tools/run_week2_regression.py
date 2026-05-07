"""Phase 1 / Week 2 / Day 5 — standard regression with ensemble flag ON.

Three end-to-end Germany-vs-France pipeline runs with
ARGUS_USE_ENSEMBLE_VERDICT=true. Identical session setup to the Week 1
runner (same fixture inputs, same evidence seed, same NEW routing) so
the only delta from the Week 1 NEW baseline is the ensemble verdict
gate — which lets Day 5's regression doc isolate the writer-side
effect of flipping the flag.

Output
------
- ``backend/eval_runs/week2_regression/run_{1,2,3}.json`` (gitignored)
- ``backend/eval_runs/week2_regression/summary.json`` (committed)

The summary mirrors the Week 1 schema plus a new
``ensemble_verdict_distribution`` per-run block so the regression doc
can show the supported_high / supported_low / weak / contradicted
spread that the writer is now reading.

Usage::

    python tools/run_week2_regression.py            # 3 runs
    python tools/run_week2_regression.py --runs 1   # quick smoke
    python tools/run_week2_regression.py --summary-only

Cost guardrail: aborts before a new run if cumulative spend across
this directory exceeds ``--cost-ceiling`` (default 60 USD).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))

# Force ensemble flag ON before any backend module reads it.
os.environ.setdefault("ARGUS_USE_ENSEMBLE_VERDICT", "true")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")

# Output paths -------------------------------------------------------------

BENCH_ROOT = _REPO_ROOT / "backend" / "eval_runs" / "week2_regression"
SUMMARY_PATH = BENCH_ROOT / "summary.json"
SUMMARY_CSV_PATH = BENCH_ROOT / "summary.csv"


def _fixture_session() -> dict[str, Any]:
    return json.loads(
        (
            _REPO_ROOT / "backend" / "tests" / "fixtures" / "germany_vs_france" / "session.json"
        ).read_text(encoding="utf-8")
    )


def _fixture_evidence() -> list[dict[str, Any]]:
    return json.loads(
        (
            _REPO_ROOT / "backend" / "tests" / "fixtures" / "germany_vs_france" / "evidence.json"
        ).read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------------
# DB helpers — duplicate of the Week 1 runner's session-setup + capture.
# Kept inline rather than imported because the two benchmark runners are
# allowed to drift independently as the schema evolves.
# ---------------------------------------------------------------------------


async def _setup_session(run_index: int) -> str:
    from db.connection import acquire  # noqa: WPS433

    fixture = _fixture_session()
    evidence = _fixture_evidence()
    session_id = str(uuid.uuid4())
    metadata = {
        **(fixture.get("metadata") or {}),
        "week2_regression": True,
        "week2_run_index": run_index,
        "ensemble_flag_on": True,
    }

    async with acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO sessions (
                    id, title, query, status, report_mode, pipeline_state,
                    metadata, gap_report, intake_questions, intake_answers, updated_at
                ) VALUES (
                    $1::uuid, $2, $3, 'draft', 'general', 'idle',
                    $4::jsonb, '{}'::jsonb, $5::jsonb, $6::jsonb, NOW()
                )
                """,
                session_id,
                f"Week 2 regression · ensemble · run {run_index}",
                fixture["query"],
                json.dumps(metadata),
                json.dumps(fixture.get("intake_questions") or []),
                json.dumps(fixture.get("intake_answers") or []),
            )
            for e in evidence:
                await conn.execute(
                    """
                    INSERT INTO evidence_objects (
                        id, session_id, task_id, claim, quote, source_title, source_url,
                        source_date, source_type, source_score, confidence, is_inference
                    ) VALUES (
                        $1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12
                    )
                    """,
                    str(uuid.uuid4()),
                    session_id,
                    e.get("task_id"),
                    e.get("claim", ""),
                    e.get("quote", ""),
                    e.get("source_title", ""),
                    e.get("source_url", ""),
                    e.get("source_date"),
                    e.get("source_type", "web"),
                    float(e.get("source_score", 0.0)),
                    e.get("confidence", "medium"),
                    bool(e.get("is_inference", False)),
                )
    return session_id


def _row_to_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    out: dict[str, Any] = {}
    for k, v in dict(row).items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif isinstance(v, uuid.UUID):
            out[k] = str(v)
        else:
            try:
                json.dumps(v)
                out[k] = v
            except TypeError:
                out[k] = str(v)
    return out


async def _capture(session_id: str) -> dict[str, Any]:
    from db.connection import acquire  # noqa: WPS433

    async with acquire() as conn:
        report_row = await conn.fetchrow(
            """
            SELECT id, session_id, recommendation, confidence_level, summary,
                   key_reasons, risks, counterarguments, next_steps, sources,
                   raw_output, caveats, evidence_bundle, verification,
                   evidence_count, unsupported_claim_count,
                   consulting_payload, reasoning_graph, claim_support, created_at
            FROM reports
            WHERE session_id = $1::uuid
            """,
            session_id,
        )
        agent_rows = await conn.fetch(
            """
            SELECT agent_name, duration_ms, token_count, output, created_at
            FROM agent_outputs
            WHERE session_id = $1::uuid
            ORDER BY created_at ASC
            """,
            session_id,
        )
        # Pulls all 8 new ensemble columns alongside the legacy ones.
        claim_support_rows = await conn.fetch(
            """
            SELECT claim_id, claim_text, evidence_object_ids, support_type,
                   verifier_verdict, contradiction_flag, weak_flag,
                   entailment_score,
                   nli_label, nli_confidence,
                   numeric_overlap_score, numeric_overlap_missing,
                   entity_overlap_score, entity_overlap_missing,
                   ensemble_verdict, ensemble_reason
            FROM claim_support_rows
            WHERE session_id = $1::uuid
            """,
            session_id,
        )
        llm_rows = await conn.fetch(
            """
            SELECT task_kind, model, provider,
                   prompt_tokens, completion_tokens, total_tokens,
                   usd_cost, latency_ms, success, error_kind
            FROM llm_calls
            WHERE session_id = $1::uuid
            ORDER BY id ASC
            """,
            session_id,
        )

    llm_dicts = [_row_to_dict(r) for r in llm_rows]
    cost_total = sum(float(r.get("usd_cost") or 0) for r in llm_dicts)
    by_task: dict[str, list[dict[str, Any]]] = {}
    for row in llm_dicts:
        by_task.setdefault(str(row.get("task_kind") or ""), []).append(row)
    fallback_hits: list[dict[str, Any]] = []
    for task_kind, rows in by_task.items():
        if len(rows) > 1:
            models_used = sorted({str(r.get("model") or "") for r in rows})
            if len(models_used) > 1:
                fallback_hits.append({"task": task_kind, "models": models_used})

    return {
        "session_id": session_id,
        "report": _row_to_dict(report_row) if report_row else None,
        "agent_outputs": [_row_to_dict(r) for r in agent_rows],
        "claim_support_rows": [_row_to_dict(r) for r in claim_support_rows],
        "llm_calls": llm_dicts,
        "cost_usd_total": cost_total,
        "fallback_hits": fallback_hits,
    }


# ---------------------------------------------------------------------------
# Per-run + summary metrics — same shape as Week 1's _analyze_week1.py
# ---------------------------------------------------------------------------

import re  # noqa: E402

FORBIDDEN_PHRASES = [
    "phased approach",
    "leverage synergies",
    "best practices",
    "explore opportunities",
    "consider",
    "perhaps",
    "might want to",
]
NAMED_OPTION_PATTERNS = [
    r"\bgermany\b", r"\bfrance\b", r"\bgerman\b", r"\bfrench\b",
    r"\bmittelstand\b",
    r"\bnorth rhine[- ]westphalia\b", r"\bnrw\b",
    r"\bbavaria\b",
    r"\b(?:paris|berlin|munich|frankfurt|hamburg|lyon)\b",
    r"\b(?:retail|logistics|saas|b2b)\b",
    r"\beu\b", r"\beuropean union\b",
]
NAMED_RE = re.compile("|".join(NAMED_OPTION_PATTERNS), re.IGNORECASE)
NUMERIC_RE = re.compile(
    r"(?:\b\d+(?:\.\d+)?\s*%|"
    r"[€$£]\s*\d+(?:[\.,]\d+)*[KkMmBb]?|"
    r"\b\d+(?:[\.,]\d+)?\s*(?:million|billion|m|bn|k)\b|"
    r"\b\d+\s*(?:month|months|year|years|day|days|week|weeks|quarter|quarters|q[1-4])\b|"
    r"\b\d+\s*(?:hire|hires|headcount|fte|ftes|engineer|engineers|account|accounts|customer|customers|loi|lois|seat|seats)\b|"
    r"\b\d+\b)",
    re.IGNORECASE,
)
TIME_BOUND_RE = re.compile(
    r"\b("
    r"(?:within|by|in|over|after|before|month|day|week|quarter)\s+\d+|"
    r"\d+\s*(?:day|days|week|weeks|month|months|year|years|quarter|quarters)|"
    r"q[1-4]\s*(?:20)?\d{0,2}|"
    r"\d+[- ]?(?:day|month|year|week)|"
    r"by\s+(?:end of|q[1-4]|month\s*\d+)|"
    r"month\s+\d+|"
    r"go[/-]?no[- ]?go|"
    r"day\s*\d+|"
    r"next\s+\d+\s*(?:weeks|months|days|quarters)"
    r")\b",
    re.IGNORECASE,
)


def _writer_text(run: dict[str, Any]) -> str:
    """Concatenate writer-relevant text fields for phrase scoring."""
    r = run.get("report") or {}
    parts = [r.get("recommendation") or "", r.get("summary") or "", r.get("caveats") or ""]
    for k in ("key_reasons", "risks", "counterarguments", "next_steps"):
        v = r.get(k) or []
        if isinstance(v, list):
            parts.extend(str(x) for x in v)
        elif isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    parts.extend(str(x) for x in parsed)
                else:
                    parts.append(str(v))
            except Exception:
                parts.append(str(v))
    cp = r.get("consulting_payload") or {}
    if isinstance(cp, dict):
        for k in ("kill_criteria", "what_would_change_our_mind", "evidence_ledger_summary"):
            v = cp.get(k)
            if isinstance(v, list):
                parts.extend(str(x) for x in v)
            elif isinstance(v, str):
                parts.append(v)
    return "\n".join(p for p in parts if p)


def _per_run_metrics(run: dict[str, Any]) -> dict[str, Any]:
    rec = (run.get("report") or {}).get("recommendation") or ""
    text_all = _writer_text(run)
    next_steps = (run.get("report") or {}).get("next_steps") or []
    if isinstance(next_steps, str):
        try:
            next_steps = json.loads(next_steps)
        except Exception:
            next_steps = [next_steps]

    # Claim-level. We compute BOTH unfiltered and key-only counts because:
    #   - Week 1's regression doc reports total_claims = 20 (all
    #     claim_support_rows, including assumption rows). Apples-to-apples.
    #   - The ensemble verdict distribution is most meaningful on the
    #     analyst's substantive key_claims (assumptions have no evidence
    #     and the verifier rightly says "weak" on all of them, which
    #     would dominate the distribution).
    rows = run.get("claim_support_rows") or []
    key_rows = [r for r in rows if (r.get("support_type") or "").lower() != "assumption"]
    ev_dist: dict[str, int] = {}
    for r in key_rows:
        ev = r.get("ensemble_verdict") or "(null)"
        ev_dist[ev] = ev_dist.get(ev, 0) + 1

    legacy_class_dist: dict[str, int] = {"supported": 0, "weak": 0, "unsupported": 0, "contradicted": 0, "other": 0}
    for ev, n in ev_dist.items():
        ev_l = (ev or "").strip().lower()
        if ev_l in ("supported_high", "supported_low"):
            legacy_class_dist["supported"] += n
        elif ev_l in legacy_class_dist:
            legacy_class_dist[ev_l] += n
        else:
            legacy_class_dist["other"] += n

    fallbacks = run.get("fallback_hits") or []
    return {
        "run_index": run.get("run_index"),
        "wall_seconds": round(float(run.get("wall_seconds") or 0.0), 2),
        "cost_usd_total": round(float(run.get("cost_usd_total") or 0.0), 4),
        "fallback_stage_count": len(fallbacks),
        "fallback_stages": fallbacks,
        # Recommendation specificity (matches Week 1 doc).
        "named_options": len(NAMED_RE.findall(rec)),
        "numeric_values": len(NUMERIC_RE.findall(rec)),
        "time_bound_next_steps": sum(1 for s in next_steps if TIME_BOUND_RE.search(str(s))),
        "forbidden_phrase_hits": sum(
            len(re.findall(re.escape(p), text_all, re.IGNORECASE)) for p in FORBIDDEN_PHRASES
        ),
        # Claim-level.
        "total_claims": len(rows),  # matches Week 1 (all rows, incl. assumptions)
        "key_claims_only": len(key_rows),
        "ensemble_verdict_distribution": ev_dist,
        "legacy_class_distribution": legacy_class_dist,
        # Recommendation preview for eyeball comparison with Week 1.
        "recommendation_preview": rec[:240],
        "confidence_level": (run.get("report") or {}).get("confidence_level"),
    }


def _aggregate(per_run: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(per_run) or 1

    def _avg(key: str) -> float:
        vals = [r.get(key) or 0 for r in per_run if isinstance(r.get(key), (int, float))]
        return round(sum(vals) / max(len(vals), 1), 2)

    # Sum legacy-class counts across runs (so the doc can present a single
    # supported/weak/unsupported/contradicted spread).
    legacy_total = {"supported": 0, "weak": 0, "unsupported": 0, "contradicted": 0, "other": 0}
    for r in per_run:
        for k, v in (r.get("legacy_class_distribution") or {}).items():
            legacy_total[k] = legacy_total.get(k, 0) + int(v)

    return {
        "n_runs": len(per_run),
        "named_options_avg": _avg("named_options"),
        "numeric_values_avg": _avg("numeric_values"),
        "time_bound_steps_avg": _avg("time_bound_next_steps"),
        "forbidden_phrase_hits_avg": _avg("forbidden_phrase_hits"),
        "total_claims_avg": _avg("total_claims"),
        "key_claims_only_avg": _avg("key_claims_only"),
        "cost_usd_total_avg": _avg("cost_usd_total"),
        "wall_seconds_avg": _avg("wall_seconds"),
        "fallback_stage_count_avg": _avg("fallback_stage_count"),
        "legacy_class_distribution_total": legacy_total,
    }


# ---------------------------------------------------------------------------
# Run loop
# ---------------------------------------------------------------------------


def _cumulative_spend() -> float:
    if not BENCH_ROOT.exists():
        return 0.0
    total = 0.0
    for f in BENCH_ROOT.glob("run_*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            total += float(data.get("cost_usd_total") or 0.0)
        except Exception:
            continue
    return total


async def _execute(run_index: int) -> dict[str, Any]:
    from agents.orchestrator import run_pipeline  # noqa: WPS433

    fixture = _fixture_session()
    session_id = await _setup_session(run_index)
    t0 = time.perf_counter()
    error_str: str | None = None
    try:
        await run_pipeline(session_id, fixture["query"])
    except Exception as e:  # noqa: BLE001
        error_str = f"{type(e).__name__}: {e}\n{traceback.format_exc()[:4000]}"
    wall = time.perf_counter() - t0

    captured = await _capture(session_id)
    captured["run_index"] = run_index
    captured["wall_seconds"] = wall
    captured["error"] = error_str
    captured["captured_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    captured["ensemble_flag_on"] = True
    return captured


def _is_valid(captured: dict[str, Any]) -> tuple[bool, str]:
    if captured.get("error"):
        return False, f"pipeline raised: {captured['error'][:200]}"
    report = captured.get("report") or {}
    if not report:
        return False, "no report row written"
    rec = (report.get("recommendation") or "").strip()
    if not rec:
        return False, "report has empty recommendation"
    rows = captured.get("claim_support_rows") or []
    if not rows:
        return False, "report has zero claim_support rows"
    return True, ""


async def _run_loop(runs: int, cost_ceiling: float, start_index: int = 1) -> list[Path]:
    BENCH_ROOT.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for i in range(start_index, runs + 1):
        spend = _cumulative_spend()
        if spend >= cost_ceiling:
            print(
                f"COST CEILING: ${spend:.2f} >= ${cost_ceiling:.2f} — stopping before run {i}.",
                flush=True,
            )
            break

        print(f"\n=== run {i}/{runs} starting (cumulative spend: ${spend:.2f}) ===", flush=True)
        attempt_record: dict[str, Any] | None = None
        for attempt in (1, 2):
            attempt_record = await _execute(i)
            ok, why = _is_valid(attempt_record)
            print(
                f"  attempt {attempt}: ok={ok}  cost=${attempt_record['cost_usd_total']:.4f}  "
                f"wall={attempt_record['wall_seconds']:.1f}s  reason={why or '-'}",
                flush=True,
            )
            if ok:
                break
            if attempt == 2:
                fail_path = BENCH_ROOT / f"run_{i}.failed.json"
                fail_path.write_text(json.dumps(attempt_record, indent=2, default=str), encoding="utf-8")
                raise SystemExit(
                    f"FATAL: run {i} failed twice. See {fail_path}. Stopping."
                )

        assert attempt_record is not None
        run_path = BENCH_ROOT / f"run_{i}.json"
        run_path.write_text(json.dumps(attempt_record, indent=2, default=str), encoding="utf-8")
        written.append(run_path)
        rec_preview = ((attempt_record.get("report") or {}).get("recommendation") or "")[:120]
        # ASCII-fold the preview so the Windows cp1252 console doesn't choke
        # on €, ≥, etc. The full recommendation is preserved on disk.
        ascii_preview = rec_preview.encode("ascii", "replace").decode("ascii")
        print(f"  -> wrote {run_path.name}  recommendation: {ascii_preview!r}", flush=True)

    return written


def _build_summary() -> dict[str, Any]:
    BENCH_ROOT.mkdir(parents=True, exist_ok=True)
    per_run: list[dict[str, Any]] = []
    for run_path in sorted(BENCH_ROOT.glob("run_*.json")):
        if run_path.name.endswith(".failed.json"):
            continue
        run = json.loads(run_path.read_text(encoding="utf-8"))
        per_run.append(_per_run_metrics(run))

    return {
        "ensemble_flag_on": True,
        "n_runs": len(per_run),
        "runs": per_run,
        "aggregate": _aggregate(per_run),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _write_summary() -> None:
    summary = _build_summary()
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with SUMMARY_CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "run_index", "wall_seconds", "cost_usd_total",
            "named_options", "numeric_values", "time_bound_next_steps",
            "forbidden_phrase_hits", "total_claims",
            "supported", "weak", "unsupported", "contradicted",
            "recommendation_preview",
        ])
        for r in summary["runs"]:
            ld = r["legacy_class_distribution"]
            w.writerow([
                r["run_index"], r["wall_seconds"], r["cost_usd_total"],
                r["named_options"], r["numeric_values"], r["time_bound_next_steps"],
                r["forbidden_phrase_hits"], r["total_claims"],
                ld["supported"], ld["weak"], ld["unsupported"], ld["contradicted"],
                (r["recommendation_preview"] or "").replace("\n", " "),
            ])
    print(f"\nsummary: {SUMMARY_PATH}\nsummary csv: {SUMMARY_CSV_PATH}", flush=True)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--start-index", type=int, default=1)
    p.add_argument("--cost-ceiling", type=float, default=60.0)
    p.add_argument("--summary-only", action="store_true")
    return p.parse_args()


async def main_async(args: argparse.Namespace) -> None:
    if args.summary_only:
        _write_summary()
        return

    print("ensemble flag is ON for this benchmark", flush=True)
    import core.feature_flags as ff  # noqa: WPS433

    if not ff.USE_ENSEMBLE_VERDICT:
        # Hot-reload the module so the env override applied above is read.
        import importlib  # noqa: WPS433

        importlib.reload(ff)
    print(f"  USE_ENSEMBLE_VERDICT = {ff.USE_ENSEMBLE_VERDICT}", flush=True)

    from db.connection import close_db, init_db  # noqa: WPS433

    await init_db()
    try:
        await _run_loop(args.runs, args.cost_ceiling, start_index=args.start_index)
    finally:
        await close_db()
    _write_summary()


def main() -> None:
    asyncio.run(main_async(_parse_args()))


if __name__ == "__main__":
    main()
