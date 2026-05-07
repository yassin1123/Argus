"""Quick CLI to peek at SEC EDGAR filings for a ticker.

Phase 1 / Week 3 / Day 1. Useful while developing Day 2's chunker —
lets the operator see what filings sec.gov has on file for a company
and what the primary-document URLs look like.

Examples
--------

    # Three most recent 10-Ks for Apple
    python tools/edgar_inspect.py AAPL --form 10-K --limit 3

    # All filings of any form, capped at 5
    python tools/edgar_inspect.py MSFT --limit 5

    # Multiple forms
    python tools/edgar_inspect.py AMZN --form 10-K --form 10-Q --limit 6

The User-Agent comes from ``ARGUS_SEC_USER_AGENT`` if set; the default
is "Argus Research argus-ops@example.com" — fine for development but
SEC's policy prefers a real contact email.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Make `backend/` importable so this CLI runs from any cwd.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from core.retrievers.edgar import EdgarClient, TickerNotFoundError  # noqa: E402


def _format_row(filing) -> str:
    return (
        f"  {filing.form:<10}  {filing.filing_date}  {filing.accession_number}\n"
        f"             report_date={filing.report_date or '(n/a)':<12}\n"
        f"             {filing.primary_doc_url}"
    )


async def _amain(args: argparse.Namespace) -> int:
    forms = list(args.form) if args.form else None
    async with EdgarClient() as client:
        try:
            info = await client.resolve_ticker(args.ticker)
        except TickerNotFoundError as e:
            print(f"FAIL: {e}", file=sys.stderr)
            return 1
        print(f"{info.ticker}  CIK={info.cik}  {info.name}")
        filings = await client.list_filings(info.cik, forms=forms, limit=args.limit)
    if not filings:
        forms_label = ", ".join(forms) if forms else "any form"
        print(f"  no filings ({forms_label}) found within the most recent {args.limit} returned by sec.gov.")
        return 0
    print(f"  {len(filings)} filing(s):")
    print()
    for f in filings:
        print(_format_row(f))
        print()
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Inspect SEC EDGAR filings for a ticker.")
    p.add_argument("ticker", help="Stock ticker symbol, e.g. AAPL")
    p.add_argument(
        "--form",
        action="append",
        help="Filter to a specific form type (repeatable). e.g. --form 10-K --form 10-Q",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum filings to return (default 10).",
    )
    args = p.parse_args()
    sys.exit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
