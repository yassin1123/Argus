"""Phase 2 / Week 7 / Day 4 — seed the synthetic TargetCo CIM into
the demo firm so the M&A integration test (and the Day 5 e2e demo)
have realistic acquisition-target data to ground against.

Idempotent: re-running this script returns a CACHE hit from the W5
firm-library hash dedupe path — same `(firm_id, sha256(file))` tuple,
no re-embedding, no duplicate row.

Demo firm: ``Argus Demo Boutique`` (slug ``argus-demo-boutique`` —
created by W5/D5's ``seed_week5_demo.py``). The W6 boutique pricing
override is independent and stays in place; this script only adds
the CIM as firm-library content.

Usage::

    python tools/seed_week7_demo.py
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

DEMO_FIRM_SLUG = "argus-demo-boutique"

CIM_FIXTURE = "targetco_cim.md"
CIM_TITLE = "TargetCo Holdings — Project Lighthouse CIM"
CIM_CATEGORY = "prior_report"
CIM_INTENDED_MODES = ["m_and_a_diligence"]
CIM_SECTOR_TAGS = ["industrial_services", "uk"]
CIM_DESCRIPTION = (
    "Synthetic UK industrial-services acquisition target. Four-segment "
    "portfolio (Facilities Maintenance, Industrial Cleaning, Mechanical "
    "Services, Compliance Auditing), £180m FY24 revenue, £24m EBITDA, "
    "950 FTE, sponsor-owned (Marylebone Partners III). Used by the W7 "
    "M&A integration test and Day 5 demo runner."
)


async def _ensure_cim() -> dict:
    from core.firm_library.service import ingest_firm_content
    from db.connection import acquire

    async with acquire() as conn:
        firm_row = await conn.fetchrow(
            "SELECT id FROM firms WHERE slug = $1", DEMO_FIRM_SLUG
        )
    if not firm_row:
        raise SystemExit(
            f"firm slug not found: {DEMO_FIRM_SLUG!r} — "
            "run tools/seed_week5_demo.py first."
        )
    firm_id = str(firm_row["id"])

    fixture = (
        _REPO_ROOT
        / "backend"
        / "tests"
        / "fixtures"
        / "m_and_a"
        / CIM_FIXTURE
    )
    if not fixture.exists():
        raise FileNotFoundError(f"missing fixture: {fixture}")
    body = fixture.read_bytes()

    result = await ingest_firm_content(
        firm_id=firm_id,
        title=CIM_TITLE,
        category=CIM_CATEGORY,
        file_bytes=body,
        source_filename=CIM_FIXTURE,
        uploaded_by=None,
        description=CIM_DESCRIPTION,
        intended_modes=CIM_INTENDED_MODES,
        sector_tags=CIM_SECTOR_TAGS,
    )
    marker = "CACHE" if result.cached else "INGEST"
    print(f"[{marker}] firm={firm_id} cim={result.firm_content_id}")
    print(f"  title:          {CIM_TITLE}")
    print(f"  category:       {CIM_CATEGORY}")
    print(f"  intended_modes: {CIM_INTENDED_MODES}")
    print(f"  sector_tags:    {CIM_SECTOR_TAGS}")
    print(f"  chunks_written: {result.chunks_written}")
    return {
        "firm_id": firm_id,
        "firm_content_id": result.firm_content_id,
        "cached": result.cached,
        "chunks_written": result.chunks_written,
    }


async def main_async() -> None:
    from db.connection import close_db, init_db

    await init_db()
    try:
        await _ensure_cim()
    finally:
        await close_db()


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
