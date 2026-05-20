"""Phase 3 / Week 14 / Day 2 — seed the demo firm with the W14/D2
library expansion fixtures via the hardened ingestion path.

Six fixtures (5 markdown + 1 CSV) covering UK SaaS sector primer,
consumer-goods market sizing, M&A carve-out playbook, regulatory
brief, diligence checklist template, and a 30-row comparable
transactions database. The mix exercises the new content-type router
(text + csv) and the new sentence-aware chunker.

Idempotent: re-running the script returns ``dedup_skipped`` on every
file with no rebuild. Failed extractors land as ``failed`` rows in
the per-file table and a non-zero exit code.

Usage::

    python tools/seed_week14_library_expansion.py
    python tools/seed_week14_library_expansion.py --firm <slug>
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))

os.environ.setdefault("ARGUS_USE_ENSEMBLE_VERDICT", "true")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")

# Per-fixture metadata. Filename → (title, category, intended_modes,
# sector_tags). Modes + tags wired so retrieval filters on growth /
# diligence engagements pick the right pieces.
FIXTURE_META: dict[str, tuple[str, str, list[str], list[str]]] = {
    "uk_saas_sector_primer.md": (
        "UK SaaS Sector Primer",
        "sector_primer",
        ["growth_strategy", "market_entry"],
        ["saas", "uk"],
    ),
    "consumer_goods_market_sizing.md": (
        "Consumer Goods Market Sizing — Methodology + UK Reference Pack",
        "methodology",
        ["growth_strategy", "market_entry", "m_and_a_diligence"],
        ["consumer_goods", "uk"],
    ),
    "ma_carveout_playbook.md": (
        "M&A Carve-out & Divestiture Playbook",
        "playbook",
        ["m_and_a_diligence", "carve_out"],
        [],
    ),
    "regulatory_environment_brief.md": (
        "UK Regulatory Environment Brief — GDPR, Competition Law, Sector Compliance",
        "framework",
        ["m_and_a_diligence", "growth_strategy", "market_entry"],
        ["uk", "regulatory"],
    ),
    "diligence_checklist_template.md": (
        "Diligence Checklist Template",
        "framework",
        ["m_and_a_diligence"],
        [],
    ),
    "comparable_transactions.csv": (
        "Comparable Transactions Database (UK, synthetic)",
        "prior_report",
        ["m_and_a_diligence"],
        ["uk", "comparables"],
    ),
}

DEMO_FIRM_SLUG_DEFAULT = "argus-demo-boutique"


def _format_table(results: list) -> str:
    if not results:
        return "(no results)"
    name_w = max(len("filename"), max(len(r.filename) for r in results))
    status_w = max(len("status"), max(len(r.status) for r in results))
    lines = [
        f"{'filename':<{name_w}}  {'status':<{status_w}}  {'chunks':<6}  reason",
        f"{'-' * name_w}  {'-' * status_w}  {'-' * 6}  {'-' * 18}",
    ]
    for r in results:
        reason = r.error_reason or ("(prev ingested)" if r.dedup_skipped else "")
        lines.append(
            f"{r.filename:<{name_w}}  {r.status:<{status_w}}  "
            f"{r.chunks_created:<6}  {reason}"
        )
    return "\n".join(lines)


async def _resolve_firm_id(firm_slug: str) -> str:
    from db.connection import acquire

    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM firms WHERE slug = $1::text", firm_slug,
        )
    if not row:
        raise SystemExit(
            f"firm slug not found: {firm_slug!r}. "
            f"Run tools/seed_week5_demo.py first to provision the demo firm."
        )
    return str(row["id"])


async def main_async(args: argparse.Namespace) -> int:
    from db.connection import close_db, init_db

    fixtures_dir = _REPO_ROOT / "backend" / "tests" / "fixtures" / "library_expansion"
    if not fixtures_dir.is_dir():
        raise SystemExit(f"fixture directory missing: {fixtures_dir}")

    await init_db()
    try:
        firm_id = await _resolve_firm_id(args.firm)
        print(f"Resolved firm slug {args.firm!r} -> firm_id={firm_id}")
        print(f"Ingesting from {fixtures_dir.resolve()} ...")
        print()

        from core.firm_library.ingestion import IngestionResult, _ingest_single_hardened

        all_results: list[IngestionResult] = []
        for path in sorted(fixtures_dir.iterdir()):
            if not path.is_file() or path.name.startswith("."):
                continue
            meta = FIXTURE_META.get(path.name)
            if meta is None:
                # No declared metadata — still ingest under sensible defaults
                # so a future fixture drop-in doesn't get silently skipped.
                meta = (
                    path.stem.replace("_", " ").title(),
                    "other",
                    [],
                    [],
                )
            title, category, modes, sectors = meta
            res = await _ingest_single_hardened(
                firm_id=firm_id,
                title=title,
                category=category,
                file_bytes=path.read_bytes(),
                source_filename=path.name,
                uploaded_by=None,
                description=f"W14/D2 library expansion — {category}.",
                intended_modes=modes,
                sector_tags=sectors,
                trust_level="firm_vetted",
            )
            all_results.append(res)
    finally:
        await close_db()

    print(_format_table(all_results))
    print()
    n_ready = sum(1 for r in all_results if r.status == "ready")
    n_dedup = sum(1 for r in all_results if r.status == "dedup_skipped")
    n_fail = sum(1 for r in all_results if r.status == "failed")
    chunks = sum(r.chunks_created for r in all_results if r.status == "ready")
    print(f"Ready          : {n_ready}")
    print(f"Dedup-skipped  : {n_dedup}")
    print(f"Failed         : {n_fail}")
    print(f"Chunks created : {chunks}")
    return 1 if n_fail else 0


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--firm", default=DEMO_FIRM_SLUG_DEFAULT,
                   help=f"Firm slug (default: {DEMO_FIRM_SLUG_DEFAULT})")
    args = p.parse_args()
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
