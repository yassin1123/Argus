"""Manual earnings-transcript upload CLI (Phase 1 / Week 4 / Day 2).

The primary path for AAPL / MSFT / TSLA Phase 1 transcripts because public
companies generally don't file actual transcripts as SEC exhibits — see
``backend/core/retrievers/edgar/transcripts.py`` for the surface signal.

Accepts plain TXT, WebVTT, and SRT. The detection + normalisation +
ingestion logic lives in
``backend/core/retrievers/transcripts/manual_upload.py`` (so tests can
import without sys.path gymnastics); this CLI is a thin wrapper.

Usage::

    python tools/transcript_upload.py path/to/aapl_q4_fy25.txt \\
        --ticker AAPL --quarter Q4 --year 2025 --source manual

    python tools/transcript_upload.py path/to/msft_q3.vtt \\
        --ticker MSFT --quarter Q3 --year 2026
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

from core.retrievers.transcripts.manual_upload import (  # noqa: E402
    ingest_manual_transcript,
    load_and_normalise,
)
from db.connection import close_db, init_db  # noqa: E402


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingest a manually-supplied earnings-call transcript.")
    p.add_argument("path", help="Path to a .txt / .vtt / .srt transcript file.")
    p.add_argument("--ticker", required=True, help="Stock ticker, e.g. AAPL.")
    p.add_argument(
        "--company-name",
        default=None,
        help="Optional pretty name (e.g. 'Apple Inc.'). Defaults to ticker.",
    )
    p.add_argument("--quarter", required=True, help="Fiscal quarter, e.g. Q4.")
    p.add_argument("--year", required=True, type=int, help="Fiscal year, e.g. 2025.")
    p.add_argument(
        "--source",
        default="manual",
        help=(
            "Provenance label written into metadata.source. Useful values: "
            "'manual' (default), 'apple_ir', 'seeking_alpha', 'motley_fool'."
        ),
    )
    p.add_argument(
        "--session-id",
        default=None,
        help="Optional session UUID to scope chunks to. When omitted the chunks "
             "are written firm-global (session_id NULL) — same as SEC ingestion.",
    )
    p.add_argument(
        "--trust-level",
        default="general",
        help="trust_level column value (default: general — manual uploads are "
             "unverified until an admin flips them).",
    )
    return p.parse_args()


async def _amain(args: argparse.Namespace) -> int:
    src_path = Path(args.path).expanduser().resolve()
    if not src_path.is_file():
        print(f"FAIL: {src_path} does not exist", file=sys.stderr)
        return 1
    shape, text = load_and_normalise(src_path)
    if not text:
        print(f"FAIL: {src_path} appears empty after normalisation", file=sys.stderr)
        return 1

    company_name = args.company_name or args.ticker.upper()
    print(f"loaded shape={shape} chars={len(text)} from {src_path.name}")

    await init_db()
    t0 = time.perf_counter()
    try:
        outcome = await ingest_manual_transcript(
            text=text,
            ticker=args.ticker.upper(),
            company_name=company_name,
            quarter=args.quarter,
            year=args.year,
            source_label=args.source,
            source_path=src_path,
            session_id=args.session_id,
            trust_level=args.trust_level,
        )
    finally:
        await close_db()
    wall = time.perf_counter() - t0

    if outcome.get("error"):
        print(f"FAIL: {outcome['error']}", file=sys.stderr)
        return 1

    print(f"\n=== ingest summary for {args.ticker} {args.quarter} FY{args.year} ===")
    print(f"  shape                 : {shape}")
    print(f"  chunks_written        : {outcome['chunks_written']}")
    print(f"  pseudo_accession      : {outcome['pseudo_accession']}")
    print(f"  speakers              : {outcome.get('speakers', [])}")
    print(f"  trust_level           : {args.trust_level}")
    print(f"  wall_seconds          : {wall:.1f}")
    return 0


def main() -> None:
    sys.exit(asyncio.run(_amain(_parse_args())))


if __name__ == "__main__":
    main()
