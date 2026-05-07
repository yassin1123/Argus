"""Pull a real filing through fetch -> parse -> chunk and print the
section histogram + sample chunks. Operator sanity check for the
EDGAR chunker (Phase 1 / Week 3 / Day 2).

Examples
--------

    python tools/edgar_chunk_inspect.py AAPL --form 10-K
    python tools/edgar_chunk_inspect.py MSFT --form 10-Q --samples 1
    python tools/edgar_chunk_inspect.py TSLA --form 10-K --samples 0

Surfaces a loud warning (non-zero exit) if more than 30% of the
filing's body text lands in UNKNOWN — that's a parser bug, not an
edge case.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import textwrap
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from core.retrievers.edgar import (  # noqa: E402
    EdgarClient,
    TickerNotFoundError,
    chunk_filing,
    parse_filing_sections,
)


def _ascii(text: str) -> str:
    """ASCII-fold for terminals that can't render € / ’ etc."""
    return text.encode("ascii", "replace").decode("ascii")


async def _amain(args: argparse.Namespace) -> int:
    async with EdgarClient() as client:
        try:
            info = await client.resolve_ticker(args.ticker)
        except TickerNotFoundError as e:
            print(f"FAIL: {e}", file=sys.stderr)
            return 1
        filings = await client.list_filings(info.cik, forms=[args.form], limit=1)
        if not filings:
            print(f"FAIL: no {args.form} filings for {info.ticker}", file=sys.stderr)
            return 1
        filing = filings[0]
        print(
            f"{info.ticker}  CIK={info.cik}  {info.name}\n"
            f"  filing: {filing.form}  {filing.filing_date}  {filing.accession_number}\n"
            f"  url: {filing.primary_doc_url}"
        )
        doc = await client.fetch_document(filing)
        print(f"  fetched: {doc.length_bytes / 1024:.0f} KB  content_type={doc.content_type}")

    sections = parse_filing_sections(doc.raw_html, args.form)
    chunks = chunk_filing(sections, target_chunk_chars=args.target, overlap_chars=args.overlap)

    total_chars = sum(len(s.raw_text) for s in sections) or 1
    unknown_chars = sum(len(s.raw_text) for s in sections if s.item_id == "UNKNOWN")
    unknown_pct = 100.0 * unknown_chars / total_chars

    print(f"\n  parsed: {len(sections)} sections, {len(chunks)} chunks")
    print(f"  UNKNOWN: {unknown_pct:.1f}% of body text\n")

    print("section histogram:")
    section_sizes = {(s.item_id, s.canonical_name): len(s.raw_text) for s in sections}
    section_chunk_counts = Counter((c.section_item_id, c.section_canonical_name) for c in chunks)
    for (iid, name), n in sorted(section_chunk_counts.items()):
        size = section_sizes.get((iid, name), 0)
        print(f"  {iid:<8} {_ascii(name):<55} {n:>4} chunks  ({size/1024:.1f} KB)")

    if args.samples > 0 and chunks:
        print(f"\nsample chunks ({args.samples}):")
        # Pick samples from different sections so the eyeball check
        # isn't all from Risk Factors.
        seen_sections: set[str] = set()
        printed = 0
        for c in chunks:
            if c.section_item_id in seen_sections:
                continue
            seen_sections.add(c.section_item_id)
            print(
                f"\n  --- {c.section_item_id} | {_ascii(c.section_canonical_name)} | "
                f"chunk {c.chunk_index_within_section} | offset {c.char_offset_in_filing} | "
                f"{len(c.content)} chars ---"
            )
            preview = c.content[:600]
            print(textwrap.fill(_ascii(preview), width=92, initial_indent="  ", subsequent_indent="  "))
            if len(c.content) > 600:
                print("  [...]")
            printed += 1
            if printed >= args.samples:
                break

    if unknown_pct > 30.0:
        print(
            f"\nWARN: UNKNOWN holds {unknown_pct:.1f}% of body text — likely a parser bug "
            "for this filing's markup. Investigate before promoting to ingest.",
            file=sys.stderr,
        )
        return 2
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Fetch + parse + chunk a SEC filing.")
    p.add_argument("ticker")
    p.add_argument("--form", default="10-K", help="Form type (default: 10-K)")
    p.add_argument("--target", type=int, default=2000, help="Target chunk chars (default: 2000)")
    p.add_argument("--overlap", type=int, default=200, help="Overlap chars (default: 200)")
    p.add_argument(
        "--samples",
        type=int,
        default=3,
        help="How many sample chunks to print (one per section) (default: 3)",
    )
    args = p.parse_args()
    sys.exit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
