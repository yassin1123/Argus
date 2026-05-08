"""Phase 1 / Week 4 / Day 3 smoke: run the pipeline on a news-priority brief.

The brief is the one the spec named verbatim. The smoke verifies:

  (a) planner declares source_priorities=["news"] (or includes "news")
  (b) Tavily fires (chunks with source_type='news' land in the DB)
  (c) the analyst grounds claims to news chunks
  (d) ensemble verifier runs and produces real DeBERTa labels
      (Day 1 fix already exercised; Day 3 just inherits)

Outputs: prints a per-section verdict to stdout. The session row is
deleted at the end; news chunks are deleted too (so re-running the
smoke doesn't accumulate junk in the dev DB).

Usage::

    python tools/week4_d3_news_smoke.py
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

os.environ.setdefault("ARGUS_USE_ENSEMBLE_VERDICT", "true")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")


BRIEF = (
    "What were the most material news events affecting Apple's stock "
    "in the last 90 days?"
)
TICKER = "AAPL"


async def _setup_session() -> str:
    from db.connection import acquire  # noqa: WPS433

    sid = str(uuid.uuid4())
    metadata = {"week4_d3_news_smoke": True, "ticker": TICKER}
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sessions (
                id, title, query, status, report_mode, pipeline_state,
                metadata, gap_report, intake_questions, intake_answers, updated_at
            ) VALUES (
                $1::uuid, $2, $3, 'draft', 'general', 'idle',
                $4::jsonb, '{}'::jsonb, '[]'::jsonb, '[]'::jsonb, NOW()
            )
            """,
            sid,
            "Week 4 D3 news smoke",
            BRIEF,
            json.dumps(metadata),
        )
    return sid


async def _capture(sid: str) -> dict:
    from db.connection import acquire  # noqa: WPS433

    async with acquire() as conn:
        sess = await conn.fetchrow(
            "SELECT metadata FROM sessions WHERE id=$1::uuid", sid
        )
        report = await conn.fetchrow(
            """
            SELECT recommendation, summary, evidence_count
            FROM reports WHERE session_id=$1::uuid
            """,
            sid,
        )
        n_news_chunks = await conn.fetchval(
            """
            SELECT count(*)::int FROM chunks
            WHERE source_type='news' AND session_id=$1::uuid
            """,
            sid,
        )
        sample_news = await conn.fetch(
            """
            SELECT trust_level, source_url, metadata->>'title' AS title,
                   metadata->>'source_domain' AS domain,
                   left(content, 160) AS preview
            FROM chunks
            WHERE source_type='news' AND session_id=$1::uuid
            ORDER BY position ASC LIMIT 5
            """,
            sid,
        )
        claim_rows = await conn.fetch(
            """
            SELECT claim_text, ensemble_verdict, nli_label, nli_confidence,
                   evidence_object_ids
            FROM claim_support_rows WHERE session_id=$1::uuid
            ORDER BY claim_id ASC
            """,
            sid,
        )
        evidence_objs = await conn.fetch(
            """
            SELECT id, source_url, source_type
            FROM evidence_objects WHERE session_id=$1::uuid
            """,
            sid,
        )
    sess_meta = {}
    if sess and sess.get("metadata"):
        m = sess["metadata"]
        sess_meta = json.loads(m) if isinstance(m, str) else dict(m)
    rh = (sess_meta.get("retrieval_hits") or [])
    return {
        "report": dict(report) if report else None,
        "n_news_chunks": int(n_news_chunks or 0),
        "sample_news": [dict(r) for r in sample_news],
        "claim_rows": [dict(r) for r in claim_rows],
        "evidence_objs": [dict(r) for r in evidence_objs],
        "retrieval_hits": rh,
    }


async def _cleanup(sid: str) -> None:
    from db.connection import acquire  # noqa: WPS433

    async with acquire() as conn:
        await conn.execute("DELETE FROM chunks WHERE session_id=$1::uuid", sid)
        await conn.execute("DELETE FROM claim_support_rows WHERE session_id=$1::uuid", sid)
        await conn.execute("DELETE FROM evidence_objects WHERE session_id=$1::uuid", sid)
        await conn.execute("DELETE FROM reports WHERE session_id=$1::uuid", sid)
        await conn.execute("DELETE FROM agent_outputs WHERE session_id=$1::uuid", sid)
        await conn.execute("DELETE FROM llm_calls WHERE session_id=$1::uuid", sid)
        await conn.execute("DELETE FROM sessions WHERE id=$1::uuid", sid)


def _summarise(captured: dict) -> dict:
    rep = captured.get("report") or {}
    rec = (rep.get("recommendation") or "").strip()
    summ = (rep.get("summary") or "").strip()
    rh = captured.get("retrieval_hits") or []
    planner_priorities: list[list[str]] = []
    for snap in rh:
        if isinstance(snap, dict) and snap.get("source_priorities"):
            planner_priorities.append(snap["source_priorities"])
    ev_by_id = {str(e["id"]): e for e in captured.get("evidence_objs") or []}
    grounded_with_news = 0
    grounded = 0
    for r in captured.get("claim_rows") or []:
        eo_ids = r.get("evidence_object_ids") or []
        if isinstance(eo_ids, str):
            try:
                eo_ids = json.loads(eo_ids)
            except Exception:
                eo_ids = []
        eo_ids = [str(x) for x in eo_ids if x]
        if not eo_ids:
            continue
        grounded += 1
        urls = [ev_by_id[i].get("source_url", "") for i in eo_ids if i in ev_by_id]
        # News chunks have source_url set to the article URL (not sec.gov/Archives).
        if any(u and "sec.gov/Archives/" not in u for u in urls):
            grounded_with_news += 1
    by_verdict: dict[str, int] = {}
    for r in captured.get("claim_rows") or []:
        v = r.get("ensemble_verdict") or "(null)"
        by_verdict[v] = by_verdict.get(v, 0) + 1
    by_nli: dict[str, int] = {}
    for r in captured.get("claim_rows") or []:
        v = r.get("nli_label") or "(null)"
        by_nli[v] = by_nli.get(v, 0) + 1
    return {
        "n_news_chunks": captured.get("n_news_chunks", 0),
        "planner_emitted_news": any("news" in p for p in planner_priorities),
        "planner_source_priorities_per_task": planner_priorities,
        "n_claims": len(captured.get("claim_rows") or []),
        "n_grounded_claims": grounded,
        "n_grounded_with_news": grounded_with_news,
        "ensemble_verdict_dist": by_verdict,
        "nli_label_dist": by_nli,
        "recommendation_preview": rec[:300] or summ[:300],
    }


async def main() -> None:
    from agents.orchestrator import run_pipeline
    from db.connection import close_db, init_db

    await init_db()
    t0 = time.perf_counter()
    sid = await _setup_session()
    print(f"smoke session: {sid}")
    print(f"brief: {BRIEF}\n")
    error: str | None = None
    try:
        await run_pipeline(sid, BRIEF)
    except Exception as e:  # noqa: BLE001
        import traceback as tb
        error = f"{type(e).__name__}: {e}"
        tb.print_exc()
    wall = time.perf_counter() - t0

    captured = await _capture(sid)
    summary = _summarise(captured)
    print(f"\n=== Week 4 D3 news smoke ({wall:.0f}s) ===")
    if error:
        print(f"  pipeline error: {error}")
    print(json.dumps(summary, indent=2, default=str))
    if captured.get("sample_news"):
        print("\nSample news chunks:")
        for c in captured["sample_news"][:3]:
            print(
                f"  [{c.get('trust_level'):>11}] {c.get('domain') or '?':>20}"
                f"  {(c.get('title') or '')[:80]}"
            )
            print(f"     {(c.get('preview') or '').replace(chr(10), ' ')[:200]}")

    await _cleanup(sid)
    await close_db()
    print("\ncleanup OK")


if __name__ == "__main__":
    asyncio.run(main())
