"""Day 3 sanity run — pipeline with ARGUS_USE_ENSEMBLE_VERDICT=true.

Drives one full Germany-vs-France pipeline run (same fixture as the
Week 1 benchmark) with the ensemble flag turned on, then queries the
DB to confirm every claim_support_row has the eight new columns
populated. Doesn't write a regression report — that's Day 5.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))

# Force the flag ON before importing anything that reads it.
os.environ["ARGUS_USE_ENSEMBLE_VERDICT"] = "true"

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")


async def main() -> int:
    from agents.orchestrator import run_pipeline  # noqa: WPS433
    from db.connection import acquire, close_db, init_db  # noqa: WPS433

    fixture = json.loads(
        (_REPO_ROOT / "backend" / "tests" / "fixtures" / "germany_vs_france" / "session.json").read_text(
            encoding="utf-8"
        )
    )
    fixture_evidence = json.loads(
        (_REPO_ROOT / "backend" / "tests" / "fixtures" / "germany_vs_france" / "evidence.json").read_text(
            encoding="utf-8"
        )
    )

    session_id = str(uuid.uuid4())
    print(f"sanity session_id = {session_id}")

    await init_db()
    try:
        # Insert a fresh session + seed evidence (mirrors the Week 1 runner).
        async with acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO sessions (
                        id, title, query, status, report_mode, pipeline_state,
                        metadata, gap_report, intake_questions, intake_answers, updated_at
                    ) VALUES (
                        $1::uuid, 'Day 3 ensemble sanity', $2, 'draft', 'general', 'idle',
                        '{"day3_sanity": true}'::jsonb, '{}'::jsonb, $3::jsonb, $4::jsonb, NOW()
                    )
                    """,
                    session_id,
                    fixture["query"],
                    json.dumps(fixture.get("intake_questions") or []),
                    json.dumps(fixture.get("intake_answers") or []),
                )
                for e in fixture_evidence:
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

        # Run the pipeline.
        t0 = time.perf_counter()
        await run_pipeline(session_id, fixture["query"])
        wall = time.perf_counter() - t0
        print(f"pipeline finished in {wall:.1f}s")

        # Verify every claim_support_row got the 8 new columns populated.
        async with acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT claim_id, claim_text, verifier_verdict,
                       nli_label, nli_confidence,
                       numeric_overlap_score, numeric_overlap_missing,
                       entity_overlap_score, entity_overlap_missing,
                       ensemble_verdict, ensemble_reason
                FROM claim_support_rows
                WHERE session_id = $1::uuid
                ORDER BY created_at
                """,
                session_id,
            )

        print(f"claim_support_rows: {len(rows)}")
        if not rows:
            print("FAIL: zero rows persisted")
            return 1

        # Population stats per column.
        cols = [
            "nli_label",
            "nli_confidence",
            "numeric_overlap_score",
            "entity_overlap_score",
            "ensemble_verdict",
            "ensemble_reason",
        ]
        stats = {c: 0 for c in cols}
        for row in rows:
            for c in cols:
                if row[c] is not None:
                    stats[c] += 1

        print("populated counts (should equal len(rows) for each):")
        for c, n in stats.items():
            status = "OK" if n == len(rows) else "GAP"
            print(f"  {status}  {c:30s} {n}/{len(rows)}")

        # Show the first 3 rows so the operator can eyeball verdict shape.
        print("\nfirst 3 rows:")
        for row in rows[:3]:
            print(f"- claim_id={row['claim_id']!r}")
            print(f"  llm={row['verifier_verdict']!r}  ensemble={row['ensemble_verdict']!r}  "
                  f"nli={row['nli_label']!r} (conf={row['nli_confidence']})")
            print(f"  num={row['numeric_overlap_score']}  ent={row['entity_overlap_score']}")
            print(f"  reason: {(row['ensemble_reason'] or '')[:140]}")

        # Verdict distribution.
        ev_dist: dict[str, int] = {}
        for row in rows:
            k = row["ensemble_verdict"] or "(null)"
            ev_dist[k] = ev_dist.get(k, 0) + 1
        print(f"\nensemble_verdict distribution: {ev_dist}")

        all_populated = all(n == len(rows) for n in stats.values())
        if not all_populated:
            print("FAIL: some columns are NULL on at least one row")
            return 1

        print("\nOK: every claim_support_row has all 8 ensemble columns populated.")
        return 0

    finally:
        await close_db()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
