"""Bulk firm-library ingestion CLI — W14/D2.

Usage::

    python tools/ingest_library.py \\
        --firm <slug> \\
        --dir <path> \\
        --category <category> \\
        --modes <mode1,mode2> \\
        [--sectors <tag1,tag2>] \\
        [--trust firm_vetted|firm_uploaded] \\
        [--recursive]

The CLI is idempotent — a second run on the same directory deduplicates
on the file's sha256 and reports those rows as ``dedup_skipped`` rather
than re-ingesting. Per-file outcomes print as a table at the end:

    filename                      status            chunks  reason
    --------------------------    --------------    ------  --------
    saas_sector_primer.md         ready                 6
    ma_carveout_playbook.md       dedup_skipped         5  (was ingested previously)
    broken_pdf.pdf                failed                0  pdf extractor failed: ...

Exit code:
  0 — every file landed as ``ready`` or ``dedup_skipped``.
  1 — at least one file failed (printed to stderr in the table).
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


# Categories accepted by the firm_content table (see migration 025 +
# service.py Category Literal). Keep this in sync.
_VALID_CATEGORIES = {
    "playbook", "sector_primer", "prior_report",
    "framework", "methodology", "other",
}

_VALID_TRUST_LEVELS = {"firm_vetted", "firm_uploaded", "firm_draft"}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Bulk-ingest a directory into a firm's library.")
    p.add_argument("--firm", required=True, help="Firm slug (resolves to firm_id via DB).")
    p.add_argument("--dir", required=True, type=Path, help="Directory containing the files to ingest.")
    p.add_argument(
        "--category", required=True,
        help=f"Library category. One of: {sorted(_VALID_CATEGORIES)}.",
    )
    p.add_argument(
        "--modes", default="",
        help="Comma-separated intended_modes (e.g. growth_strategy,m_and_a_diligence).",
    )
    p.add_argument(
        "--sectors", default="",
        help="Comma-separated sector_tags (e.g. saas,uk).",
    )
    p.add_argument(
        "--trust", default="firm_vetted",
        help=f"Trust level on persisted chunks. One of: {sorted(_VALID_TRUST_LEVELS)}.",
    )
    p.add_argument(
        "--recursive", action="store_true",
        help="Recurse into subdirectories (off by default).",
    )
    p.add_argument(
        "--uploaded-by", default=None,
        help="Optional uploader user-id (uuid). None = anonymous CLI run.",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print the file list + resolved firm_id and exit (no DB writes).",
    )
    return p.parse_args(argv)


def _format_results_table(results: list) -> str:
    """Pretty-print the per-file table. Plain text, fixed-width."""
    lines: list[str] = []
    if not results:
        return "(no files matched)"
    headers = ("filename", "status", "chunks", "reason")
    name_w = max(len(headers[0]), max((len(r.filename) for r in results), default=0))
    status_w = max(len(headers[1]), max((len(r.status) for r in results), default=0))
    lines.append(
        f"{headers[0]:<{name_w}}  {headers[1]:<{status_w}}  {headers[2]:<8}  {headers[3]}"
    )
    lines.append(
        f"{'-' * name_w}  {'-' * status_w}  {'-' * 8}  {'-' * 20}"
    )
    for r in results:
        reason = r.error_reason or ("(was ingested previously)" if r.dedup_skipped else "")
        lines.append(
            f"{r.filename:<{name_w}}  {r.status:<{status_w}}  "
            f"{r.chunks_created:<8}  {reason}"
        )
    return "\n".join(lines)


async def _resolve_firm_id(firm_slug: str) -> str:
    from db.connection import acquire

    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM firms WHERE slug = $1::text", firm_slug,
        )
    if not row:
        raise SystemExit(f"firm slug not found: {firm_slug!r}. Check `SELECT slug FROM firms`.")
    return str(row["id"])


async def main_async(args: argparse.Namespace) -> int:
    if args.category not in _VALID_CATEGORIES:
        raise SystemExit(
            f"--category {args.category!r} invalid. Pick one of {sorted(_VALID_CATEGORIES)}."
        )
    if args.trust not in _VALID_TRUST_LEVELS:
        raise SystemExit(
            f"--trust {args.trust!r} invalid. Pick one of {sorted(_VALID_TRUST_LEVELS)}."
        )

    directory: Path = args.dir
    if not directory.is_dir():
        raise SystemExit(f"--dir {directory} is not a directory.")

    modes = [m.strip() for m in (args.modes or "").split(",") if m.strip()]
    sectors = [s.strip() for s in (args.sectors or "").split(",") if s.strip()]

    if args.dry_run:
        from core.firm_library.ingestion import detect_content_type
        print(f"Firm slug: {args.firm}")
        print(f"Directory: {directory.resolve()}")
        print(f"Category : {args.category}")
        print(f"Modes    : {modes}")
        print(f"Sectors  : {sectors}")
        print(f"Trust    : {args.trust}")
        files = sorted(directory.rglob("*") if args.recursive else directory.iterdir())
        for p in files:
            if not p.is_file() or p.name.startswith("."):
                continue
            kind, unsup = detect_content_type(p.name)
            print(f"  - {p.name}  ->  {kind or 'UNSUPPORTED: ' + (unsup or '')}")
        return 0

    from db.connection import close_db, init_db

    await init_db()
    try:
        firm_id = await _resolve_firm_id(args.firm)
        print(f"Resolved firm slug {args.firm!r} -> firm_id={firm_id}")
        print(f"Scanning {directory.resolve()} ...")

        from core.firm_library.ingestion import ingest_directory, summarise

        results = await ingest_directory(
            firm_id=firm_id,
            directory=directory,
            category=args.category,
            intended_modes=modes,
            sector_tags=sectors,
            trust_level=args.trust,
            uploaded_by=args.uploaded_by,
            recursive=args.recursive,
        )
    finally:
        await close_db()

    print()
    print(_format_results_table(results))
    print()
    summary = summarise(results)
    print(f"Total files       : {summary['total_files']}")
    print(f"Ready             : {summary['by_status']['ready']}")
    print(f"Dedup-skipped     : {summary['by_status']['dedup_skipped']}")
    print(f"Failed            : {summary['by_status']['failed']}")
    print(f"Chunks created    : {summary['chunks_created']}")

    return 1 if summary["by_status"]["failed"] else 0


def main() -> None:
    args = _parse_args()
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
