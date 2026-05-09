"""Phase 2 / Week 6 / Day 5 — seed the boutique_pricing_review override
in the demo firm so the e2e runner has a real layered config to exercise.

Note: the spec referenced ``growth_strategy_pricing`` as the base_mode
and Run B's mode. That built-in doesn't exist in
``backend/config/consulting_modes.yaml`` (only general / market_entry /
due_diligence / growth_strategy ship today). We substitute
``growth_strategy`` as the closest match — base_mode for the override
and the no-override comparison mode. The substitution is noted in the
Week 6 wrap-up doc.

Idempotent: re-running this script after the override is already
seeded refreshes the config to the canonical values (so the demo is
locked from step 1 — see Day 5 hard rule "Don't tune the demo
override mid-run").

Demo firm: ``Argus Demo Boutique`` (slug ``argus-demo-boutique`` —
created by W5/D5's ``seed_week5_demo.py``).

Usage::

    python tools/seed_week6_demo.py
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
OVERRIDE_NAME = "boutique_pricing_review"
BASE_MODE = "growth_strategy"  # spec called for growth_strategy_pricing — see header

OVERRIDE_CONFIG: dict[str, object] = {
    "display_name": "Boutique pricing review",
    "description": (
        "Boutique-firm pricing review: anchors pricing actions to "
        "willingness-to-pay evidence, segment elasticity, and an "
        "implementation roadmap with named owners."
    ),
    "required_branches": [
        "competitor_price_anchor_analysis",
        "willingness_to_pay_evidence",
        "price_architecture_review",
        "implementation_friction_audit",
    ],
    "reasoning_slots": [
        "price_segmentation_logic",
        "elasticity_evidence",
        "rollout_plan_with_owners",
    ],
    "source_priorities_default": ["uploaded", "sec_filing", "news", "transcript"],
    "trust_tier_rules": {
        "news": "web_general",
        "sec_filing": "firm_vetted",
        "uploaded": "firm_vetted",
    },
    "writer_overlay": (
        "Always conclude with a 2x2 matrix of (price action × customer segment "
        "willingness) and a 90-day implementation roadmap with named owners. "
        "Quantify expected revenue impact in £ at 3 sensitivity levels "
        "(conservative, base, aggressive)."
    ),
    "planner_overlay": (
        "Prioritise firm-library content for pricing methodology and "
        "segmentation frameworks. Default to uploaded sources before public "
        "data when both are available."
    ),
}


CIM_FIXTURE = "albright_marsh_pricing_pack.md"
CIM_TITLE = "Albright & Marsh Pricing Diagnostic Pack"
CIM_CATEGORY = "prior_report"


async def _ensure_cim_ingested(firm_id: str) -> None:
    """Ingest the Albright & Marsh pricing pack into the firm library
    if it isn't already there. The CIM gives the verifier concrete
    segment-level revenue / margin / elasticity data to ratify, which
    a pure-methodology library can't provide for a hypothetical brief.

    Idempotent on (firm_id, sha256(file_bytes)) — the firm library
    service short-circuits with the existing row.
    """
    from core.firm_library.service import ingest_firm_content
    from pathlib import Path as _Path

    fixture = _Path(__file__).resolve().parent.parent / "backend" / "tests" / "fixtures" / "firm_library" / CIM_FIXTURE
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
        description=(
            "Synthetic UK retailer pricing-diagnostic pack — segment-"
            "level financials, competitor pricing audit, willingness-"
            "to-pay study, cost structure walk, implementation "
            "constraints. Used by the Week 6 e2e to give the verifier "
            "concrete numbers for the boutique_pricing_review demo."
        ),
        intended_modes=["boutique_pricing_review", "growth_strategy", "due_diligence"],
        sector_tags=["consumer_retail"],
    )
    marker = "CACHE" if result.cached else "INGEST"
    print(f"  CIM [{marker}]: {result.firm_content_id}  chunks={result.chunks_written}")


async def _ensure_override() -> dict:
    from core.consulting_modes.service import (
        create_firm_mode,
        get_firm_mode,
        update_firm_mode,
    )
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

    existing = await get_firm_mode(firm_id, OVERRIDE_NAME)
    if existing:
        # Refresh the config in case the spec was tightened — locked from now on.
        fm = await update_firm_mode(
            firm_id=firm_id,
            name=OVERRIDE_NAME,
            config=OVERRIDE_CONFIG,
            updated_by=None,
            actor_email="seed_week6_demo@argus.invalid",
        )
        action = "REFRESHED"
    else:
        fm = await create_firm_mode(
            firm_id=firm_id,
            name=OVERRIDE_NAME,
            base_mode=BASE_MODE,
            config=OVERRIDE_CONFIG,
            created_by=None,
            actor_email="seed_week6_demo@argus.invalid",
        )
        action = "CREATED"

    print(f"[{action}] firm={firm_id} mode={OVERRIDE_NAME}")
    print(f"  base_mode:           {fm.base_mode}")
    print(f"  required_branches:   {fm.config.get('required_branches')}")
    print(f"  reasoning_slots:     {fm.config.get('reasoning_slots')}")
    print(f"  source_priorities:   {fm.config.get('source_priorities_default')}")
    print(f"  trust_tier_rules:    {fm.config.get('trust_tier_rules')}")
    print(f"  writer_overlay len:  {len(str(fm.config.get('writer_overlay') or ''))}")
    print(f"  planner_overlay len: {len(str(fm.config.get('planner_overlay') or ''))}")
    return {"firm_id": firm_id, "name": OVERRIDE_NAME}


async def main_async() -> None:
    from db.connection import close_db, init_db

    await init_db()
    try:
        result = await _ensure_override()
        await _ensure_cim_ingested(result["firm_id"])
    finally:
        await close_db()


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
