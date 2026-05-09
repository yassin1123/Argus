"""Phase 2 / Week 5 / Day 5 — seed the demo firm with the four fixture
playbooks so the e2e demo runner can exercise the firm-library retrieval
path against real-shaped firm content.

Idempotent: re-running this script after the fixtures are already in the
DB returns cache HITs from ``ingest_firm_content`` and rebuilds nothing.
That is the desired behaviour — partners on a real firm tenancy will
also re-run a sync job repeatedly and should get the same outcome.

Demo firm: ``Argus Demo Boutique`` (slug ``argus-demo-boutique``).
Baseline firm: ``Argus Baseline Firm`` (slug ``argus-baseline``) —
created here too so the e2e runner has a no-library tenancy to compare
against without provisioning code in the runner itself.

Usage::

    python tools/seed_week5_demo.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))

os.environ.setdefault("ARGUS_USE_ENSEMBLE_VERDICT", "true")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")

# Each fixture: (filename, title, category, intended_modes, sector_tags).
# Modes/tags are a synthetic but realistic shape so retrieval has
# something to compare a brief's metadata against.
FIXTURES: list[tuple[str, str, str, list[str], list[str]]] = [
    (
        "ma_target_screen_playbook.md",
        "M&A Target Screen Playbook (Boutique Edition)",
        "playbook",
        ["ma_target_screen"],
        ["consumer_retail", "payments", "industrial_automation"],
    ),
    (
        "retail_sector_primer.md",
        "Retail Sector Primer (UK + US)",
        "sector_primer",
        ["ma_target_screen", "growth_strategy", "market_entry"],
        ["consumer_retail"],
    ),
    (
        "growth_strategy_framework.md",
        "Growth Strategy Framework (Boutique Methodology)",
        "framework",
        ["growth_strategy", "market_entry"],
        ["consumer_retail", "industrial", "saas"],
    ),
    (
        "valuation_methodology.md",
        "Valuation Methodology (Firm House View)",
        "methodology",
        ["ma_target_screen", "valuation"],
        [],
    ),
]

DEMO_FIRM_NAME = "Argus Demo Boutique"
DEMO_FIRM_SLUG = "argus-demo-boutique"

BASELINE_FIRM_NAME = "Argus Baseline Firm"
BASELINE_FIRM_SLUG = "argus-baseline"


async def _ensure_firm(name: str, slug: str) -> str:
    """Create the firm if it doesn't already exist; return its UUID."""
    from db.connection import acquire

    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM firms WHERE slug = $1", slug
        )
        if row:
            return str(row["id"])
        row = await conn.fetchrow(
            "INSERT INTO firms (name, slug) VALUES ($1, $2) RETURNING id",
            name,
            slug,
        )
        return str(row["id"])


async def _seed() -> dict:
    from core.firm_library.service import ingest_firm_content

    fixtures_dir = _REPO_ROOT / "backend" / "tests" / "fixtures" / "firm_library"

    demo_firm_id = await _ensure_firm(DEMO_FIRM_NAME, DEMO_FIRM_SLUG)
    baseline_firm_id = await _ensure_firm(BASELINE_FIRM_NAME, BASELINE_FIRM_SLUG)

    print(f"demo firm:     {demo_firm_id}  ({DEMO_FIRM_NAME})")
    print(f"baseline firm: {baseline_firm_id}  ({BASELINE_FIRM_NAME})  [no library]")
    print()

    results = []
    for filename, title, category, modes, sectors in FIXTURES:
        path = fixtures_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"fixture missing: {path}")
        body = path.read_bytes()
        result = await ingest_firm_content(
            firm_id=demo_firm_id,
            title=title,
            category=category,
            file_bytes=body,
            source_filename=filename,
            uploaded_by=None,
            description=f"Synthetic Week-5 demo fixture — {category}.",
            intended_modes=modes,
            sector_tags=sectors,
        )
        results.append(
            {
                "filename": filename,
                "title": title,
                "firm_content_id": result.firm_content_id,
                "cached": result.cached,
                "chunks_written": result.chunks_written,
            }
        )
        marker = "CACHE" if result.cached else "INGEST"
        print(
            f"  [{marker}]  {filename:<38}"
            f"  -> {result.firm_content_id}  chunks={result.chunks_written}"
        )

    # Verify the chunks landed.
    from db.connection import acquire

    async with acquire() as conn:
        n_content = await conn.fetchval(
            "SELECT COUNT(*) FROM firm_content WHERE firm_id = $1::uuid",
            demo_firm_id,
        )
        n_chunks = await conn.fetchval(
            """
            SELECT COUNT(*) FROM chunks
            WHERE firm_id = $1::uuid AND source_type = 'firm_library'
              AND COALESCE(metadata->>'retired_at', '') = ''
            """,
            demo_firm_id,
        )

    print()
    print(f"verification:  firm_content rows = {n_content}")
    print(f"               firm_library chunks = {n_chunks}")
    if n_content < len(FIXTURES) or n_chunks == 0:
        raise SystemExit(
            f"FAIL: expected >= {len(FIXTURES)} firm_content rows and chunks > 0, "
            f"got rows={n_content} chunks={n_chunks}"
        )

    return {
        "demo_firm_id": demo_firm_id,
        "baseline_firm_id": baseline_firm_id,
        "results": results,
        "n_firm_content": int(n_content),
        "n_firm_library_chunks": int(n_chunks),
    }


async def main_async() -> None:
    from db.connection import close_db, init_db

    await init_db()
    try:
        await _seed()
    finally:
        await close_db()


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
