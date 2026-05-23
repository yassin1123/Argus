"""Phase 4 / Week 17 / Day 3 — live my-work smoke.

Plants a deterministic mix of derived signals (owned section,
change-request pointer, mention) + an explicit task on the seeded
Meridian Kestrel engagement, then exercises ``derive_tasks_for_user``
and ``get_my_work`` against the live DB. Idempotent — clears
prior W17/D3 fixtures first.

Usage::

    python tools/run_week17_d3_smoke.py
"""

from __future__ import annotations

import asyncio
import json
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
TITLE_PREFIX = "Kestrel"


async def _run() -> int:
    from db.connection import acquire
    from core.collaboration.explicit_tasks import (
        complete_task,
        create_task,
    )
    from core.collaboration.my_work import get_my_work
    from core.collaboration.section_assignments import assign_section, set_section_status
    from core.collaboration.section_status import SectionStatus
    from core.collaboration.tasks import derive_tasks_for_user

    async with acquire() as conn:
        sess = await conn.fetchrow(
            """
            SELECT s.id, s.title FROM sessions s
              JOIN firms f ON f.id = s.firm_id
             WHERE f.slug = $1::text AND s.title LIKE $2 || '%'
             ORDER BY s.title ASC LIMIT 1
            """,
            FIRM_SLUG, TITLE_PREFIX,
        )
        if not sess:
            raise SystemExit(f"Seed Meridian first ({FIRM_SLUG}).")

        users = {r["email"]: r["id"] for r in await conn.fetch(
            """
            SELECT u.id, u.email FROM users u
              JOIN firm_memberships fm ON fm.user_id = u.id
              JOIN firms f ON f.id = fm.firm_id
             WHERE f.slug = $1::text
            """,
            FIRM_SLUG,
        )}

        def _pick(*needles: str) -> str:
            for em, uid in users.items():
                if any(n in em for n in needles):
                    return str(uid)
            raise KeyError(needles)

        lead_id = UUID(_pick("helena", "partner"))
        contrib_id = UUID(_pick("marcus", "consultant"))
        # Reset W17/D3 fixtures.
        await conn.execute(
            "DELETE FROM engagement_tasks WHERE session_id = $1::uuid",
            sess["id"],
        )
        await conn.execute(
            "DELETE FROM review_records WHERE session_id = $1::uuid "
            "AND action = 'request_changes'",
            sess["id"],
        )
        await conn.execute(
            "DELETE FROM comments WHERE session_id = $1::uuid",
            sess["id"],
        )
        await conn.execute(
            "DELETE FROM section_assignments WHERE session_id = $1::uuid",
            sess["id"],
        )

    sid = UUID(str(sess["id"]))

    print(f"engagement: {sess['title']}  session={sid}")
    print(f"  lead       = {lead_id}")
    print(f"  contributor = {contrib_id}")
    print()

    print("[1] Lead assigns synergy_estimate to contributor + marks in_progress …")
    a = await assign_section(
        session_id=sid, section_path="synergy_estimate",
        assigned_to=contrib_id, assigned_by=lead_id,
    )
    if not a.ok:
        raise SystemExit(f"assign failed: {a.reason}")
    await set_section_status(
        session_id=sid, section_path="synergy_estimate",
        status=SectionStatus.IN_PROGRESS, actor_id=contrib_id,
    )

    print("[2] Lead opens a blocking change request on synergy_estimate …")
    firm_uuid = await _firm_id_for(sid)
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO review_records
                (session_id, firm_id, from_state, to_state, action,
                 actor_id, reviewer_id, feedback)
            VALUES ($1::uuid, $2::uuid, 'in_review', 'changes_requested', 'request_changes',
                    $3::uuid, $3::uuid, $4::jsonb)
            """,
            sid, UUID(firm_uuid), lead_id,
            json.dumps({
                "overall_note": "Tighten synergy basis.",
                "severity": "blocking",
                "section_pointers": [
                    {"section_path": "synergy_estimate",
                     "note": "Source on the cross-sell uplift?",
                     "severity": "blocking", "resolved": False},
                ],
            }),
        )

    print("[3] Lead drops a comment mentioning the contributor on synergy_estimate …")
    firm_uuid = await _firm_id_for(sid)
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO comments
                (session_id, firm_id, parent_comment_id,
                 anchor_type, anchor_ref, body, mentioned_user_ids, author_id)
            VALUES ($1::uuid, $2::uuid, NULL,
                    'engagement', '{}'::jsonb,
                    $3, $4::jsonb, $5::uuid)
            """,
            sid, UUID(firm_uuid),
            "Heads up @marcus.thorne — check the FY24 baseline first.",
            json.dumps([str(contrib_id)]),
            lead_id,
        )

    print("[4] Lead files an explicit task: 'Ping client lawyer about SPA timeline' …")
    explicit = await create_task(
        session_id=sid, title="Ping client lawyer about SPA timeline",
        created_by=lead_id, assigned_to=contrib_id,
    )
    if not explicit.ok:
        raise SystemExit(f"create_task failed: {explicit.reason}")

    print()
    print("[5] derive_tasks_for_user (contributor, cross-engagement) …")
    derived = await derive_tasks_for_user(contrib_id, session_id=None)
    for t in derived:
        print(f"    [{t.priority:6}] {t.task_type:24} "
              f"section={t.section_path or '-':<24} "
              f"summary={t.summary[:60]}")

    print()
    print("[6] get_my_work (scope=all) …")
    work = await get_my_work(contrib_id, scope="all")
    print(f"    -> {len(work.tasks)} unified tasks; "
          f"totals high={work.totals['high']} medium={work.totals['medium']} low={work.totals['low']}")
    for sid_key, bucket in work.by_engagement.items():
        print(f"    {bucket['engagement_title']}: "
              f"{bucket['counts']['total']} tasks "
              f"(high={bucket['counts']['high']} medium={bucket['counts']['medium']} low={bucket['counts']['low']})")

    print()
    print("[7] Complete the explicit task …")
    await complete_task(UUID(explicit.task.id), actor_id=contrib_id)
    work2 = await get_my_work(contrib_id, scope="all")
    print(f"    -> after complete: {len(work2.tasks)} unified tasks remaining")

    # Sanity: at least one high-priority change_request, one mention, one section_incomplete.
    types = {t.task_type for t in derived}
    assert "change_request" in types, "missing change_request"
    assert "mention" in types, "missing mention"
    assert "section_incomplete" in types, "missing section_incomplete"

    print()
    print("Smoke passed: derived (change_request + mention + section_incomplete) "
          "+ explicit task + complete flow")
    return 0


async def _firm_id_for(session_id: UUID) -> str:
    from db.connection import acquire
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT firm_id FROM sessions WHERE id = $1::uuid", session_id,
        )
    return str(row["firm_id"])


async def main() -> int:
    from db.connection import close_db, init_db
    await init_db()
    try:
        return await _run()
    finally:
        await close_db()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
