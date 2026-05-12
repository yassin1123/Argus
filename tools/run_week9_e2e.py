"""Phase 2 / Week 9 / Day 5 — section-deepening e2e demo runner.

Fires two deepenings against the W7/W8 M&A demo session and
captures before/after for each. Records cost, wall, new chunks,
new claim_ids, schema-validation result, and word-count growth.

Headline assertions (mirrored from the W9/D5 spec):
  1. Both deepenings reach status='complete'.
  2. Each produces >= MIN_NEW_CLAIM_IDS new claim_ids not in the
     original section.
  3. Each uses >= MIN_NEW_CHUNKS new evidence chunks.
  4. The deepened section passes schema validation (M&A schema for
     this engagement).
  5. Word count of the deepened section >= 1.5x the original.
  6. Combined cost across both runs < MAX_TOTAL_COST_USD.

Usage::

    python tools/run_week9_e2e.py
    python tools/run_week9_e2e.py --summary-only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from uuid import UUID

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")


# The W7 M&A demo session — confirmed populated end-to-end at
# session 9da8a365-... ($0.16 producing 7/7 fields + 4-item 2x2).
M_AND_A_SESSION_ID = UUID("9da8a365-224e-4c4c-8f65-8ff1d1cef5dc")

# Two deepening targets per W9/D5 spec.
RUNS: list[dict[str, str]] = [
    {
        "name": "R1_cost_synergies",
        "section_path": "synergy_estimate.cost_synergies",
        "directive": (
            "The cost synergies feel generic. Add detail: which functions, "
            "what timing (year 1 vs year 2 vs year 3), and what is the basis "
            "(benchmark transactions, internal estimates)."
        ),
    },
    {
        "name": "R2_first_100_days",
        "section_path": "integration_plan.first_100_days",
        "directive": (
            "The 100-day plan is too high-level. Specify named owner roles "
            "(CFO, CHRO, Integration Lead, etc.) and the dependency chain "
            "between initiatives."
        ),
    },
]

# Assertion thresholds.
MIN_NEW_CLAIM_IDS = 3
MIN_NEW_CHUNKS = 5
MIN_WORD_GROWTH_RATIO = 1.5
MAX_TOTAL_COST_USD = 1.20

BENCH_ROOT = _REPO_ROOT / "backend" / "eval_runs" / "week9_e2e"


def _count_words(value: Any) -> int:
    """Total whitespace-delimited word count across any nested
    string content in ``value``."""
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value.split())
    if isinstance(value, list):
        return sum(_count_words(x) for x in value)
    if isinstance(value, dict):
        return sum(_count_words(v) for v in value.values())
    return 0


async def _fire_one(run: dict[str, str]) -> dict[str, Any]:
    """Run one deepening end-to-end via the service layer (not HTTP)
    so the runner doesn't depend on a backend server being up. Same
    code path either way — the HTTP layer is a thin wrapper."""
    from core.section_deepening import DeepeningRequest, deepen_section
    from db.connection import acquire

    # Pick a real user for triggered_by (FK to users.id).
    async with acquire() as conn:
        u = await conn.fetchrow("SELECT id FROM users WHERE email='demo@argus.local'")
    user_id: UUID = u["id"] if u else uuid.uuid4()

    t0 = time.perf_counter()
    req = DeepeningRequest(
        session_id=M_AND_A_SESSION_ID,
        section_path=run["section_path"],
        depth_directive=run["directive"],
    )
    print(f"\n=== {run['name']} (path={run['section_path']}) ===", flush=True)
    result = await deepen_section(req, user_id)
    wall = time.perf_counter() - t0
    print(
        f"  status={result.status}  wall={wall:.1f}s  "
        f"new_chunks={result.new_evidence_chunks_used}  "
        f"new_claim_ids={len(result.new_claim_ids)}  "
        f"error={result.failure_reason or 'none'}",
        flush=True,
    )

    # Pull the cost actually charged on the writer task call for
    # this deepening's session window (rough — last N seconds).
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT COALESCE(SUM(usd_cost),0)::float AS cost
            FROM llm_calls
            WHERE session_id = $1::uuid
              AND task_kind = 'writer'
              AND created_at > NOW() - INTERVAL '5 minutes'
            """,
            M_AND_A_SESSION_ID,
        )
    measured_cost = float(rows[0]["cost"]) if rows else 0.0

    # Word-count comparison (the assertion).
    original_wc = _count_words(result.original_section_json)
    deepened_wc = _count_words(result.deepened_section_json)
    growth_ratio = (deepened_wc / original_wc) if original_wc else 0.0

    return {
        "run_name": run["name"],
        "section_path": run["section_path"],
        "directive": run["directive"],
        "deepening_id": str(result.deepening_id),
        "status": result.status,
        "failure_reason": result.failure_reason,
        "wall_seconds": round(wall, 2),
        "measured_cost_usd": round(measured_cost, 4),
        "new_evidence_chunks_used": result.new_evidence_chunks_used,
        "new_claim_ids": result.new_claim_ids,
        "original_section_json": result.original_section_json,
        "deepened_section_json": result.deepened_section_json,
        "original_word_count": original_wc,
        "deepened_word_count": deepened_wc,
        "word_growth_ratio": round(growth_ratio, 2),
    }


def _excerpt(value: Any, words: int = 60) -> str:
    """Compact textual excerpt of a section value, capped to N words."""
    parts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str) and node.strip():
            parts.append(node.strip())
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(value)
    flat = " ".join(parts)
    flat = re.sub(r"\s+", " ", flat).strip()
    wlist = flat.split(" ")
    if len(wlist) > words:
        return " ".join(wlist[:words]) + " …"
    return flat


def _headline_assertions(records: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for r in records:
        name = r["run_name"]
        # 1: status complete
        out[f"{name}_status_complete"] = r["status"] == "complete"
        # 2: new claim_ids
        out[f"{name}_new_claim_ids_ge_{MIN_NEW_CLAIM_IDS}"] = (
            len(r.get("new_claim_ids") or []) >= MIN_NEW_CLAIM_IDS
        )
        # 3: new chunks
        out[f"{name}_new_chunks_ge_{MIN_NEW_CHUNKS}"] = (
            (r.get("new_evidence_chunks_used") or 0) >= MIN_NEW_CHUNKS
        )
        # 4: schema validation passed (status=complete implies it; the
        #    service rejects on validation failure with status=failed).
        out[f"{name}_schema_valid"] = r["status"] == "complete"
        # 5: word-count growth
        out[f"{name}_word_growth_ge_{MIN_WORD_GROWTH_RATIO}x"] = (
            (r.get("word_growth_ratio") or 0.0) >= MIN_WORD_GROWTH_RATIO
        )
    # 6: combined cost under cap
    total_cost = sum(r.get("measured_cost_usd") or 0.0 for r in records)
    out[f"combined_cost_under_{MAX_TOTAL_COST_USD}"] = total_cost < MAX_TOTAL_COST_USD
    out["combined_cost_usd"] = round(total_cost, 4)
    out["headline_pass"] = all(
        v for k, v in out.items() if isinstance(v, bool)
    )
    return out


def _build_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    headline = _headline_assertions(records)
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "session_id": str(M_AND_A_SESSION_ID),
        "headline_assertions": headline,
        "headline_pass": headline["headline_pass"],
        "n_runs": len(records),
        "runs": [
            {
                "run_name": r["run_name"],
                "section_path": r["section_path"],
                "deepening_id": r["deepening_id"],
                "status": r["status"],
                "failure_reason": r["failure_reason"],
                "wall_seconds": r["wall_seconds"],
                "measured_cost_usd": r["measured_cost_usd"],
                "new_evidence_chunks_used": r["new_evidence_chunks_used"],
                "new_claim_ids_count": len(r.get("new_claim_ids") or []),
                "original_word_count": r["original_word_count"],
                "deepened_word_count": r["deepened_word_count"],
                "word_growth_ratio": r["word_growth_ratio"],
                "original_excerpt": _excerpt(r["original_section_json"]),
                "deepened_excerpt": _excerpt(r["deepened_section_json"]),
            }
            for r in records
        ],
    }


async def main_async(args: argparse.Namespace) -> None:
    BENCH_ROOT.mkdir(parents=True, exist_ok=True)

    if args.summary_only:
        records: list[dict[str, Any]] = []
        for run in RUNS:
            f = BENCH_ROOT / f"{run['name']}.json"
            if f.exists():
                records.append(json.loads(f.read_text(encoding="utf-8")))
        (BENCH_ROOT / "summary.json").write_text(
            json.dumps(_build_summary(records), indent=2, default=str),
            encoding="utf-8",
        )
        print(f"\nsummary: {BENCH_ROOT / 'summary.json'}")
        return

    from db.connection import close_db, init_db

    await init_db()
    records: list[dict[str, Any]] = []
    try:
        for run in RUNS:
            rec = await _fire_one(run)
            (BENCH_ROOT / f"{run['name']}.json").write_text(
                json.dumps(rec, indent=2, default=str), encoding="utf-8"
            )
            records.append(rec)
    finally:
        await close_db()

    summary = _build_summary(records)
    (BENCH_ROOT / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )

    print("\n=== HEADLINE ASSERTIONS ===")
    for k, v in summary["headline_assertions"].items():
        if isinstance(v, bool):
            print(f"  [{'PASS' if v else 'FAIL'}] {k}")
        else:
            print(f"  {k}: {v}")
    print(f"\nheadline_pass: {summary['headline_pass']}")
    print(f"summary: {BENCH_ROOT / 'summary.json'}")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--summary-only", action="store_true")
    return p.parse_args()


def main() -> None:
    asyncio.run(main_async(_parse_args()))


if __name__ == "__main__":
    main()
