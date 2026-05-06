"""Phase 1 / Week 1, Day 4 — Germany-vs-France benchmark runner.

Captures six end-to-end pipeline runs of the seeded Germany-vs-France
engagement: three under the OLD all-OpenAI routing (forced via
ARGUS_MODEL_* env overrides) and three under the NEW multi-provider
routing (no overrides — the YAML decides).

Usage (from the repo root, with .env loaded and Postgres+Redis+MinIO up):

    # OLD routing — three runs:
    python tools/run_week1_benchmark.py --config old --runs 3

    # NEW routing — three runs:
    python tools/run_week1_benchmark.py --config new --runs 3

    # Build the cross-config summary after both finished:
    python tools/run_week1_benchmark.py --summary-only

The runner does NOT go through FastAPI or Celery. It imports
``agents.orchestrator.run_pipeline`` directly so:
- The same-family ``ARGUS_MODEL_*`` overrides used for the OLD config
  do not trigger the boot-time cross-family check in backend/main.py
  (the runner never imports main.py).
- Each run is a fresh, isolated DB session row created here, so re-runs
  don't trample the seeded engagement at id 11111111-1111-4111-8111-111111111111.

Outputs:
- ``backend/eval_runs/week1_benchmark/{old,new}/run_{1,2,3}.json`` — full per-run
  capture (gitignored): final report, all agent_outputs rows, all
  claim_support_rows, llm_calls cost rollup, wall-clock time.
- ``backend/eval_runs/week1_benchmark/summary.json`` — committed cross-config
  rollup: per-run cost, time, fallback counts, claim counts.

Cost ceiling: aborts before starting a new run if the cumulative spend
across the directory exceeds ``--cost-ceiling`` (default 60 USD). Failures
get one retry; if a run fails twice we stop and surface to the operator.
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

# Make `backend/` importable when running from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))

# Load .env so OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY are visible.
from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")

# OLD routing: every task pinned to its pre-Day-2 OpenAI model. This
# matches the YAML at commit 3733a58 (initial publish), with provider
# prefixes added so litellm routes correctly under the current wrapper.
OLD_ROUTING_OVERRIDES: dict[str, str] = {
    "ARGUS_MODEL_INTAKE": "openai/gpt-4o-mini",
    "ARGUS_MODEL_CONVERSATION": "openai/gpt-4o-mini",
    "ARGUS_MODEL_PLANNER": "openai/gpt-4o",
    "ARGUS_MODEL_RESEARCHER": "openai/gpt-4o",
    "ARGUS_MODEL_RESEARCH_SUBAGENT": "openai/gpt-4o-mini",
    "ARGUS_MODEL_ANALYST": "openai/gpt-4o",
    "ARGUS_MODEL_CRITIC": "openai/gpt-4o",
    "ARGUS_MODEL_VERIFIER": "openai/gpt-4o-mini",
    "ARGUS_MODEL_WRITER": "openai/gpt-4o",
    "ARGUS_MODEL_ENTAILMENT": "openai/gpt-4o-mini",
    # Also flip fallbacks back to OpenAI so a primary-model blip doesn't
    # accidentally route us through the new cross-family chain.
    "ARGUS_FALLBACK_INTAKE": "openai/gpt-4o",
    "ARGUS_FALLBACK_CONVERSATION": "openai/gpt-4o",
    "ARGUS_FALLBACK_PLANNER": "openai/gpt-4o-mini",
    "ARGUS_FALLBACK_RESEARCHER": "openai/gpt-4o-mini",
    "ARGUS_FALLBACK_RESEARCH_SUBAGENT": "openai/gpt-4o-mini",
    "ARGUS_FALLBACK_ANALYST": "openai/gpt-4o-mini",
    "ARGUS_FALLBACK_CRITIC": "openai/gpt-4o-mini",
    "ARGUS_FALLBACK_VERIFIER": "openai/gpt-4o",
    "ARGUS_FALLBACK_WRITER": "openai/gpt-4o-mini",
}


def _apply_old_routing() -> None:
    for key, value in OLD_ROUTING_OVERRIDES.items():
        os.environ[key] = value


def _clear_old_routing() -> None:
    for key in OLD_ROUTING_OVERRIDES:
        os.environ.pop(key, None)


def _fixture_session() -> dict[str, Any]:
    path = _REPO_ROOT / "backend" / "tests" / "fixtures" / "germany_vs_france" / "session.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _fixture_evidence() -> list[dict[str, Any]]:
    """Pre-seeded evidence the analyst can ground claims in. Mirrors what the
    seeded demo engagement already carries; we re-key each evidence row with a
    fresh UUID per run so multiple benchmark sessions coexist without colliding
    on evidence_objects.id (PRIMARY KEY).
    """
    path = _REPO_ROOT / "backend" / "tests" / "fixtures" / "germany_vs_france" / "evidence.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _output_dir(config: str) -> Path:
    d = _REPO_ROOT / "backend" / "eval_runs" / "week1_benchmark" / config
    d.mkdir(parents=True, exist_ok=True)
    return d


def _summary_path() -> Path:
    return _REPO_ROOT / "backend" / "eval_runs" / "week1_benchmark" / "summary.json"


def _summary_csv_path() -> Path:
    return _REPO_ROOT / "backend" / "eval_runs" / "week1_benchmark" / "summary.csv"


# ---------------------------------------------------------------------------
# DB helpers (asyncpg, no FastAPI)
# ---------------------------------------------------------------------------


async def _setup_session_for_run(config: str, run_index: int) -> str:
    """Create a fresh session row carrying the Germany-vs-France query +
    intake AND seed it with the fixture's evidence_objects (fresh UUIDs).

    A fresh session_id keeps multiple runs isolated from each other and
    from the demo seed at id 11111111-...; seeding the same evidence base
    keeps OLD vs NEW a fair A/B (the analyst sees identical grounding,
    only the model routing differs).
    """
    from db.connection import acquire  # noqa: WPS433 — late import (after sys.path tweak)

    fixture = _fixture_session()
    evidence = _fixture_evidence()
    session_id = str(uuid.uuid4())
    metadata = {
        **(fixture.get("metadata") or {}),
        "week1_benchmark": True,
        "week1_config": config,
        "week1_run_index": run_index,
    }

    async with acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO sessions (
                    id, title, query, status, report_mode, pipeline_state,
                    metadata, gap_report, intake_questions, intake_answers, updated_at
                ) VALUES (
                    $1::uuid, $2, $3, 'draft', $4, 'idle',
                    $5::jsonb, '{}'::jsonb, $6::jsonb, $7::jsonb, NOW()
                )
                """,
                session_id,
                f"Week 1 benchmark · {config} · run {run_index}",
                fixture["query"],
                # report_mode override: the fixture stores "market_entry" but
                # that mode requires branch coverage (market/competition/regulation)
                # which the researcher tags via [branch:...] prefixes only when
                # web search is active. Without SerpAPI/Brave keys configured the
                # mode-satisfaction check halts the pipeline at "insufficient"
                # before the analyst runs (verified empirically on first attempt).
                # We pin to "general" so both OLD and NEW configs face an
                # identical, runnable setup — the wedge effect we're measuring
                # is in the synthesis layer, not in branch routing.
                "general",
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
                    str(uuid.uuid4()),  # fresh id — fixture UUIDs would collide on second run
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


async def _capture_run_outputs(session_id: str) -> dict[str, Any]:
    """Read everything the pipeline wrote into Postgres for this session_id."""
    from db.connection import acquire

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
        claim_support_rows = await conn.fetch(
            """
            SELECT claim_id, claim_text, evidence_object_ids,
                   support_type, verifier_verdict, contradiction_flag,
                   entailment_score, weak_flag
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
        pipeline_events = await conn.fetch(
            """
            SELECT stage, status, payload, created_at
            FROM pipeline_events
            WHERE session_id = $1::uuid
            ORDER BY id ASC
            """,
            session_id,
        )

    def _row_to_dict(row: Any) -> dict[str, Any]:
        if row is None:
            return {}
        out: dict[str, Any] = {}
        for k, v in dict(row).items():
            # asyncpg returns json/jsonb columns already-decoded most of the time;
            # serialise dates/UUIDs/Decimal as strings so json.dump is happy.
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

    llm_dicts = [_row_to_dict(r) for r in llm_rows]
    cost_total = sum(float(r.get("usd_cost") or 0) for r in llm_dicts)
    fallback_hits: list[dict[str, Any]] = []
    # A fallback fires when the same task_kind has more than one model row;
    # the first attempt either errored (success=False) or timed out before
    # we recorded usage. Surface both signals so the operator can see them.
    by_task: dict[str, list[dict[str, Any]]] = {}
    for row in llm_dicts:
        by_task.setdefault(str(row.get("task_kind") or ""), []).append(row)
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
        "pipeline_events": [_row_to_dict(r) for r in pipeline_events],
        "cost_usd_total": cost_total,
        "fallback_hits": fallback_hits,
    }


# ---------------------------------------------------------------------------
# Cost guardrail
# ---------------------------------------------------------------------------


def _cumulative_spend(root: Path) -> float:
    total = 0.0
    if not root.exists():
        return total
    for f in root.glob("**/run_*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            total += float(data.get("cost_usd_total") or 0)
        except Exception:
            continue
    return total


# ---------------------------------------------------------------------------
# Run loop
# ---------------------------------------------------------------------------


async def _execute_one_run(config: str, run_index: int) -> dict[str, Any]:
    from agents.orchestrator import run_pipeline  # noqa: WPS433

    session_id = await _setup_session_for_run(config, run_index)
    fixture = _fixture_session()
    query = fixture["query"]

    t0 = time.perf_counter()
    error_str: str | None = None
    try:
        await run_pipeline(session_id, query)
    except Exception as e:  # noqa: BLE001 — we surface, don't swallow
        error_str = f"{type(e).__name__}: {e}\n{traceback.format_exc()[:4000]}"
    wall_seconds = time.perf_counter() - t0

    captured = await _capture_run_outputs(session_id)
    captured.update(
        {
            "config": config,
            "run_index": run_index,
            "wall_seconds": wall_seconds,
            "error": error_str,
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "routing_env": {
                k: v for k, v in os.environ.items() if k.startswith("ARGUS_MODEL_") or k.startswith("ARGUS_FALLBACK_")
            },
        }
    )
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
    claims = captured.get("claim_support_rows") or []
    if not claims:
        return False, "report has zero claim_support rows"
    return True, ""


async def _run_config(config: str, runs: int, cost_ceiling_usd: float, start_index: int = 1) -> list[Path]:
    out_dir = _output_dir(config)
    bench_root = _REPO_ROOT / "backend" / "eval_runs" / "week1_benchmark"

    written: list[Path] = []
    for i in range(start_index, runs + 1):
        spend = _cumulative_spend(bench_root)
        if spend >= cost_ceiling_usd:
            print(
                f"COST CEILING: ${spend:.2f} >= ${cost_ceiling_usd:.2f} — "
                f"stopping before {config} run {i}.",
                flush=True,
            )
            break

        print(
            f"\n=== {config.upper()} run {i}/{runs} starting "
            f"(cumulative spend so far: ${spend:.2f}) ===",
            flush=True,
        )

        attempt_record: dict[str, Any] | None = None
        for attempt in (1, 2):
            attempt_record = await _execute_one_run(config, i)
            ok, why = _is_valid(attempt_record)
            print(
                f"  attempt {attempt}: ok={ok}  cost=${attempt_record['cost_usd_total']:.4f}  "
                f"wall={attempt_record['wall_seconds']:.1f}s  "
                f"fallbacks={len(attempt_record['fallback_hits'])}  reason={why or '-'}",
                flush=True,
            )
            if ok:
                break
            if attempt == 2:
                # Two failures in a row — surface and abort.
                run_path = out_dir / f"run_{i}.failed.json"
                run_path.write_text(json.dumps(attempt_record, indent=2, default=str), encoding="utf-8")
                raise SystemExit(
                    f"FATAL: {config} run {i} failed twice. Detail written to {run_path}. "
                    "Stop and surface to the human."
                )

        assert attempt_record is not None
        run_path = out_dir / f"run_{i}.json"
        run_path.write_text(json.dumps(attempt_record, indent=2, default=str), encoding="utf-8")
        written.append(run_path)

        rec = ((attempt_record.get("report") or {}).get("recommendation") or "")[:120]
        fb = attempt_record.get("fallback_hits") or []
        print(
            f"  -> wrote {run_path.name}  recommendation: {rec!r}",
            flush=True,
        )
        if fb:
            print(f"     fallback hits: {fb}", flush=True)

    return written


# ---------------------------------------------------------------------------
# Summary writers (committed)
# ---------------------------------------------------------------------------


def _build_summary() -> dict[str, Any]:
    bench_root = _REPO_ROOT / "backend" / "eval_runs" / "week1_benchmark"
    summary: dict[str, Any] = {"configs": {}, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    for config_dir in sorted(bench_root.iterdir() if bench_root.exists() else []):
        if not config_dir.is_dir():
            continue
        runs: list[dict[str, Any]] = []
        for run_path in sorted(config_dir.glob("run_*.json")):
            data = json.loads(run_path.read_text(encoding="utf-8"))
            report = data.get("report") or {}
            runs.append(
                {
                    "run_index": data.get("run_index"),
                    "wall_seconds": round(float(data.get("wall_seconds") or 0), 2),
                    "cost_usd_total": round(float(data.get("cost_usd_total") or 0), 4),
                    "fallback_hits": data.get("fallback_hits") or [],
                    "claim_support_count": len(data.get("claim_support_rows") or []),
                    "agent_outputs_count": len(data.get("agent_outputs") or []),
                    "evidence_count": int(report.get("evidence_count") or 0),
                    "unsupported_claim_count": int(report.get("unsupported_claim_count") or 0),
                    "confidence_level": report.get("confidence_level"),
                    "recommendation_preview": (report.get("recommendation") or "")[:240],
                }
            )
        agg = {
            "n_runs": len(runs),
            "cost_total_usd": round(sum(r["cost_usd_total"] for r in runs), 4),
            "wall_total_seconds": round(sum(r["wall_seconds"] for r in runs), 2),
            "any_fallbacks": any(bool(r["fallback_hits"]) for r in runs),
        }
        summary["configs"][config_dir.name] = {"runs": runs, "aggregate": agg}
    return summary


def _write_summary() -> None:
    summary = _build_summary()
    bench_root = _REPO_ROOT / "backend" / "eval_runs" / "week1_benchmark"
    bench_root.mkdir(parents=True, exist_ok=True)
    _summary_path().write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with _summary_csv_path().open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "config",
                "run_index",
                "wall_seconds",
                "cost_usd_total",
                "n_fallback_hits",
                "claim_support_count",
                "agent_outputs_count",
                "evidence_count",
                "unsupported_claim_count",
                "confidence_level",
                "recommendation_preview",
            ]
        )
        for config_name, block in summary["configs"].items():
            for run in block["runs"]:
                writer.writerow(
                    [
                        config_name,
                        run["run_index"],
                        run["wall_seconds"],
                        run["cost_usd_total"],
                        len(run["fallback_hits"]),
                        run["claim_support_count"],
                        run["agent_outputs_count"],
                        run["evidence_count"],
                        run["unsupported_claim_count"],
                        run["confidence_level"],
                        (run["recommendation_preview"] or "").replace("\n", " "),
                    ]
                )
    print(f"summary written to {_summary_path()} and {_summary_csv_path()}", flush=True)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase 1 / Week 1 benchmark runner.")
    p.add_argument("--config", choices=("old", "new"), help="Routing config to run.")
    p.add_argument("--runs", type=int, default=3, help="Number of runs (default 3).")
    p.add_argument(
        "--start-index",
        type=int,
        default=1,
        help="First run index to execute (default 1). Useful when resuming after a partial sweep.",
    )
    p.add_argument(
        "--cost-ceiling",
        type=float,
        default=60.0,
        help="USD ceiling across the entire week1_benchmark/ tree (default 60).",
    )
    p.add_argument(
        "--summary-only",
        action="store_true",
        help="Only rebuild summary.json/.csv from existing run files.",
    )
    return p.parse_args()


async def _main_async(args: argparse.Namespace) -> None:
    if args.summary_only:
        _write_summary()
        return

    if args.config == "old":
        _apply_old_routing()
        print(
            "OLD routing applied via env overrides. "
            "Verifier=openai/gpt-4o-mini, Analyst=openai/gpt-4o, etc.",
            flush=True,
        )
    elif args.config == "new":
        _clear_old_routing()
        print("NEW routing — using committed YAML (no overrides).", flush=True)
    else:
        raise SystemExit("--config old|new is required (or pass --summary-only)")

    # Force model_router to re-read env on every resolve() call after we mutate.
    import core.model_router as mr  # noqa: WPS433

    mr.reload_config()

    # Pool comes up lazily through db.connection.acquire; init explicitly so
    # an unreachable Postgres surfaces with a clear connection error before
    # we burn LLM budget on the first pipeline call.
    from db.connection import close_db, init_db  # noqa: WPS433

    await init_db()
    try:
        await _run_config(args.config, args.runs, args.cost_ceiling, start_index=args.start_index)
    finally:
        await close_db()

    _write_summary()


def main() -> None:
    args = _parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
