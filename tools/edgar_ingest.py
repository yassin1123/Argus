"""End-to-end SEC EDGAR ingestion CLI.

Phase 1 / Week 3 / Day 3. Drives ``core.retrievers.edgar.ingest_filings``
from the operator's terminal:

    python tools/edgar_ingest.py AAPL --forms 10-K,10-Q,8-K --limit-per-form 3

Prints a summary at the end (filings ingested / skipped / chunks
written / errors). Useful as the smoke target for Day 5's end-to-end
test and for hand-curating SEC content into a fresh dev DB.
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

from core.retrievers.edgar import ingest_filings  # noqa: E402


async def _amain(args: argparse.Namespace) -> int:
    forms = [f.strip().upper() for f in args.forms.split(",") if f.strip()]
    if not forms:
        print("FAIL: --forms must list at least one form (e.g. 10-K,10-Q)", file=sys.stderr)
        return 1

    from db.connection import close_db, init_db  # noqa: WPS433

    await init_db()
    t0 = time.perf_counter()
    try:
        result = await ingest_filings(
            ticker=args.ticker,
            forms=forms,
            limit_per_form=args.limit_per_form,
            session_id=args.session_id,
            trust_level=args.trust_level,
            target_chunk_chars=args.target_chunk_chars,
            overlap_chars=args.overlap_chars,
        )
    finally:
        await close_db()
    wall = time.perf_counter() - t0

    print(f"\n=== ingest summary for {args.ticker} ===")
    print(f"  forms                      : {forms}")
    print(f"  filings_attempted          : {result.filings_attempted}")
    print(f"  filings_ingested           : {result.filings_ingested}")
    print(f"  filings_skipped_idempotent : {result.filings_skipped_idempotent}")
    print(f"  chunks_written             : {result.chunks_written}")
    print(f"  chunks_skipped             : {result.chunks_skipped}")
    print(f"  errors                     : {len(result.errors)}")
    for e in result.errors[:10]:
        print(f"    - {e}")
    print(f"  wall_seconds               : {wall:.1f}")

    return 1 if result.errors else 0


def main() -> None:
    p = argparse.ArgumentParser(description="Ingest SEC filings for a ticker into the chunks table.")
    p.add_argument("ticker", help="Stock ticker (e.g. AAPL)")
    p.add_argument(
        "--forms",
        default="10-K,10-Q,8-K",
        help="Comma-separated list of forms to ingest (default: 10-K,10-Q,8-K)",
    )
    p.add_argument(
        "--limit-per-form",
        type=int,
        default=3,
        help="Max filings per form (default: 3 — politeness rule for sec.gov)",
    )
    p.add_argument(
        "--session-id",
        default=None,
        help="Optional session UUID. When omitted, chunks are written firm-global "
             "(session_id=NULL).",
    )
    p.add_argument(
        "--trust-level",
        default="firm_vetted",
        help="trust_level column value (default: firm_vetted — SEC primary source).",
    )
    p.add_argument("--target-chunk-chars", type=int, default=2000)
    p.add_argument("--overlap-chars", type=int, default=200)
    args = p.parse_args()
    sys.exit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
