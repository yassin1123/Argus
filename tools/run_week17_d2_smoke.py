"""Phase 4 / Week 17 / Day 2 — section ownership live smoke.

Drives the W17/D2 surface against the seeded Meridian Kestrel
engagement: lead assigns synergy_estimate to a contributor;
contributor walks the status through in_progress → done; coverage
map surfaces unassigned sections. Idempotent — clears prior
section_assignments first.

Usage::

    python tools/run_week17_d2_smoke.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))
sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/argus",
)

FIRM_SLUG = "meridian-advisory"
ENGAGEMENT_TITLE_PREFIX = "Kestrel"


async def _run() -> int:
    from db.connection import acquire
    from core.collaboration.coverage import section_coverage
    from core.collaboration.section_assignments import (
        assign_section,
        list_section_assignments,
        set_section_status,
    )
    from core.collaboration.section_status import SectionStatus

    async with acquire() as conn:
        sess = await conn.fetchrow(
            """
            SELECT s.id, s.title FROM sessions s
              JOIN firms f ON f.id = s.firm_id
             WHERE f.slug = $1::text AND s.title LIKE $2 || '%'
             ORDER BY s.title ASC LIMIT 1
            """,
            FIRM_SLUG, ENGAGEMENT_TITLE_PREFIX,
        )
        if not sess:
            raise SystemExit(
                f"No '{ENGAGEMENT_TITLE_PREFIX}' engagement. "
                "Seed first: tools/seed_sample_workspace.py"
            )
        lead = await conn.fetchrow(
            """
            SELECT user_id FROM engagement_memberships
             WHERE engagement_id = $1::uuid
               AND role = 'lead' AND removed_at IS NULL
             LIMIT 1
            """,
            sess["id"],
        )
        contrib = await conn.fetchrow(
            """
            SELECT user_id FROM engagement_memberships
             WHERE engagement_id = $1::uuid
               AND role = 'contributor' AND removed_at IS NULL
             ORDER BY added_at ASC LIMIT 1
            """,
            sess["id"],
        )
        if not lead or not contrib:
            raise SystemExit("Engagement is missing a lead or contributor.")
        # Reset section_assignments for an idempotent smoke.
        await conn.execute(
            "DELETE FROM section_assignments WHERE session_id = $1::uuid",
            sess["id"],
        )

    sid = UUID(str(sess["id"]))
    lead_id = UUID(str(lead["user_id"]))
    contrib_id = UUID(str(contrib["user_id"]))

    print(f"engagement: {sess['title']}  session={sid}")
    print(f"  lead       = {lead_id}")
    print(f"  contributor = {contrib_id}")
    print()

    print("[1] Lead assigns synergy_estimate to contributor …")
    r1 = await assign_section(
        session_id=sid, section_path="synergy_estimate",
        assigned_to=contrib_id, assigned_by=lead_id,
    )
    if not r1.ok:
        raise SystemExit(f"assign failed: {r1.reason}")
    print(f"    -> assignment {r1.assignment.id}  status={r1.assignment.status}")

    print("[2] Contributor marks it in_progress …")
    r2 = await set_section_status(
        session_id=sid, section_path="synergy_estimate",
        status=SectionStatus.IN_PROGRESS, actor_id=contrib_id,
    )
    if not r2.ok:
        raise SystemExit(f"in_progress failed: {r2.reason}")

    print("[3] Contributor marks it done …")
    r3 = await set_section_status(
        session_id=sid, section_path="synergy_estimate",
        status=SectionStatus.DONE, actor_id=contrib_id,
    )
    if not r3.ok:
        raise SystemExit(f"done failed: {r3.reason}")
    print(f"    -> status={r3.assignment.status}")

    print("[4] Coverage map …")
    cov = await section_coverage(sid)
    print(f"    -> {len(cov.entries)} trackable sections; "
          f"{cov.unassigned_count} unassigned; "
          f"ready_to_submit={cov.ready_to_submit}")
    print("    by_status:")
    for k, v in cov.by_status.items():
        if v:
            print(f"      {k}: {v}")
    print("    unassigned paths:")
    for e in cov.entries:
        if not e.assigned:
            print(f"      - {e.section_path}")
    if cov.ready_to_submit:
        raise SystemExit("ready_to_submit should be False with unassigned sections")

    print()
    print("Smoke passed: assign -> in_progress -> done -> coverage with unassigned surfaced")
    return 0


async def main() -> int:
    from db.connection import close_db, init_db
    await init_db()
    try:
        return await _run()
    finally:
        await close_db()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
