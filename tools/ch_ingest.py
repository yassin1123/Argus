"""End-to-end Companies House ingestion CLI (Phase 1 / Week 4 / Day 4).

Mirror of ``tools/edgar_ingest.py``. Drives
:func:`core.retrievers.companies_house.ingest_company` from the
operator's terminal:

    python tools/ch_ingest.py 00445790 --limit 1                 # Tesco
    python tools/ch_ingest.py "Tesco PLC" --limit 1              # by name
    python tools/ch_ingest.py 02666364 --limit 2                 # AstraZeneca

Prints a summary at the end (filings ingested / skipped / chunks
written / errors).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")

from core.retrievers.companies_house import ingest_company  # noqa: E402


async def _amain(args: argparse.Namespace) -> int:
    from db.connection import close_db, init_db  # noqa: WPS433

    await init_db()
    t0 = time.perf_counter()
    try:
        result = await ingest_company(
            company_number=args.company,
            limit=args.limit,
            categories=[c.strip() for c in args.categories.split(",") if c.strip()],
            session_id=args.session_id,
            trust_level=args.trust_level,
            target_chunk_chars=args.target_chunk_chars,
            overlap_chars=args.overlap_chars,
        )
    finally:
        await close_db()
    wall = time.perf_counter() - t0

    print(f"\n=== ingest summary for {args.company} ===")
    print(f"  categories                 : {args.categories}")
    print(f"  filings_attempted          : {result.filings_attempted}")
    print(f"  filings_ingested           : {result.filings_ingested}")
    print(f"  filings_skipped_idempotent : {result.filings_skipped_idempotent}")
    print(f"  filings_skipped_no_text    : {result.filings_skipped_no_text}")
    print(f"  chunks_written             : {result.chunks_written}")
    print(f"  errors                     : {len(result.errors)}")
    for e in result.errors[:10]:
        print(f"    - {e}")
    print(f"  wall_seconds               : {wall:.1f}")
    return 1 if result.errors else 0


def main() -> None:
    p = argparse.ArgumentParser(
        description="Ingest UK Companies House filings into the chunks table."
    )
    p.add_argument(
        "company",
        help=(
            "Company number (8 chars, e.g. 00445790) or name "
            "(falls back to /search/companies)."
        ),
    )
    p.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Max filings to ingest (default 1 — politeness toward CH).",
    )
    p.add_argument(
        "--categories",
        default="accounts",
        help="Comma-separated CH filing categories (default: accounts).",
    )
    p.add_argument(
        "--session-id",
        default=None,
        help=(
            "Optional session UUID. When omitted, chunks are written "
            "firm-global (session_id NULL) — same convention as SEC ingest."
        ),
    )
    p.add_argument(
        "--trust-level",
        default="firm_vetted",
        help="trust_level column (default: firm_vetted — CH is statutory).",
    )
    p.add_argument("--target-chunk-chars", type=int, default=2000)
    p.add_argument("--overlap-chars", type=int, default=200)
    args = p.parse_args()
    sys.exit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
