"""Smoke check: print the chunks for one ticker-quarter-year tuple.

Usage:
    python tools/transcript_inspect.py AAPL --quarter Q4 --year 2025
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")

from db.connection import acquire, close_db, init_db  # noqa: E402


async def _amain(args: argparse.Namespace) -> int:
    await init_db()
    try:
        async with acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT position,
                       metadata->>'speaker' AS speaker,
                       metadata->>'role' AS role,
                       metadata->>'firm' AS firm,
                       metadata->>'segment' AS segment,
                       metadata->>'turn_index' AS turn_index,
                       trust_level,
                       left(content, 240) AS preview,
                       char_length(content) AS clen
                FROM chunks
                WHERE source_type = 'transcript'
                  AND metadata->>'ticker' = $1
                  AND metadata->>'quarter' = $2
                  AND (metadata->>'year')::int = $3
                ORDER BY position ASC
                """,
                args.ticker.upper(),
                args.quarter,
                args.year,
            )
        if not rows:
            print(
                f"No transcript chunks for {args.ticker} {args.quarter} FY{args.year}.",
                file=sys.stderr,
            )
            return 1
        print(
            f"=== {args.ticker} {args.quarter} FY{args.year} — {len(rows)} chunks ==="
        )
        for r in rows:
            speaker = r["speaker"] or "?"
            role = r["role"] or ""
            firm = r["firm"] or ""
            seg = r["segment"] or ""
            preview = (r["preview"] or "").replace("\n", " ")
            label = speaker
            if role:
                label += f" ({role})"
            if firm:
                label += f" @ {firm}"
            print(
                f"  [{r['position']:>3}] {seg:>16} | {label:>50} | {r['clen']:>5}c | {preview[:120]}"
            )
    finally:
        await close_db()
    return 0


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("ticker")
    p.add_argument("--quarter", required=True)
    p.add_argument("--year", type=int, required=True)
    return p.parse_args()


def main() -> None:
    sys.exit(asyncio.run(_amain(_parse_args())))


if __name__ == "__main__":
    main()
