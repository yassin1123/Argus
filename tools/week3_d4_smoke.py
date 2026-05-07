"""Phase 1 / Week 3 / Day 4 smoke: task-aware retrieval against the real
chunks DB.

Exercises ``_retrieve_by_priorities`` (the new routing helper) against
whatever SEC chunks the dev DB already has from the Day 5 end-to-end
ingest. Saves a JSON snapshot to ``docs/eval/week3_d4_smoke.json`` so
the spec's "manual smoke" requirement has a reproducible artefact.

Usage (from repo root):
    python tools/week3_d4_smoke.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")

from agents.research.orchestrator import _retrieve_by_priorities  # noqa: E402
from db.connection import close_db, init_db  # noqa: E402


# An arbitrary engagement UUID. SEC chunks are session-less (session_id
# IS NULL) and surface for any engagement, so this just needs to parse
# as a UUID.
_FAKE_ENGAGEMENT = "00000000-0000-0000-0000-000000000abc"


async def _run_case(label: str, question: str, priorities: list[str]) -> dict:
    t0 = time.perf_counter()
    hits, consulted = await _retrieve_by_priorities(
        _FAKE_ENGAGEMENT, question, priorities
    )
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    return {
        "label": label,
        "question": question,
        "source_priorities": priorities,
        "sources_consulted": consulted,
        "elapsed_ms": elapsed_ms,
        "hit_count": len(hits),
        "hits_by_source_type": _count_by(hits, "source_type"),
        "top_hits": [
            {
                "source_type": h.get("source_type"),
                "source_filename": h.get("source_filename"),
                "section_heading": h.get("section_heading"),
                "score": round(float(h.get("score") or 0), 4),
                "snippet": (h.get("content") or "")[:160].replace("\n", " "),
            }
            for h in hits[:3]
        ],
    }


def _count_by(rows: list[dict], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        v = str(r.get(key) or "")
        out[v] = out.get(v, 0) + 1
    return out


async def main() -> None:
    await init_db()
    try:
        cases = [
            await _run_case(
                "sec_only",
                "What does Apple disclose about iPhone segment revenue?",
                ["sec_filing"],
            ),
            await _run_case(
                "uploaded_first_then_sec",
                "What does Apple disclose about iPhone segment revenue?",
                ["uploaded", "sec_filing"],
            ),
            await _run_case(
                "uploaded_only",
                "What does Apple disclose about iPhone segment revenue?",
                ["uploaded"],
            ),
            await _run_case(
                "news_then_web_no_chunks_path",
                "Recent analyst chatter on Apple",
                ["news", "web"],
            ),
        ]
    finally:
        await close_db()

    out_path = _REPO_ROOT / "docs" / "eval" / "week3_d4_smoke.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"cases": cases}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Wrote smoke snapshot to {out_path}")
    for c in cases:
        print(
            f"  [{c['label']}] consulted={c['sources_consulted']} "
            f"hits={c['hit_count']} by_type={c['hits_by_source_type']}"
        )


if __name__ == "__main__":
    asyncio.run(main())
