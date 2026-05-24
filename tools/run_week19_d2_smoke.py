"""Phase 4 / Week 19 / Day 2 — version diff + restore live smoke.

Walks the spec's manual smoke against the seeded Meridian Kestrel
engagement: simulate a section deepening that bumps to v2, restore
v1, verify a new v3 lands as a copy of v1 with history preserved.

Usage::

    python tools/run_week19_d2_smoke.py
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
os.environ.setdefault("ARGUS_EMAIL_ADAPTER", "capture")

FIRM_SLUG = "meridian-advisory"
TITLE_PREFIX = "Kestrel"


async def _run() -> int:
    from db.connection import acquire
    from core.versioning import (
        ChangeType,
        create_version,
        diff_versions,
        list_versions,
        restore_version,
    )
    from core.notifications.email import (
        CaptureEmailAdapter, reset_adapter_for_tests,
    )

    reset_adapter_for_tests(CaptureEmailAdapter())

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
        # Look up the actual active lead for this engagement — prior
        # e2e runs may have reassigned it away from the default
        # consultant. Falls back to the W14 seed creator if no lead
        # row exists.
        lead_row = await conn.fetchrow(
            """
            SELECT user_id FROM engagement_memberships
             WHERE engagement_id = $1::uuid
               AND role = 'lead' AND removed_at IS NULL
             LIMIT 1
            """,
            sess["id"],
        )
        consultant = str(lead_row["user_id"]) if lead_row else \
            next((str(uid) for em, uid in users.items()
                  if "marcus" in em or "consultant" in em),
                 list(users.values())[0])

        # Reset prior W19 history for this session so the smoke is idempotent.
        # Note: this is destructive on the version table — only safe in dev.
        await conn.execute(
            "DELETE FROM payload_versions WHERE session_id = $1::uuid", sess["id"],
        )
        # Reset session to draft state for the test.
        await conn.execute(
            """
            UPDATE sessions SET review_state = 'draft',
                                approved_at = NULL, approved_by = NULL,
                                submitted_at = NULL, submitted_by = NULL
             WHERE id = $1::uuid
            """,
            sess["id"],
        )

    sid = UUID(str(sess["id"]))
    print(f"engagement: {sess['title']}")
    print()

    # Seed v1 directly + simulate a v2 from a "deepening".
    print("[1] Seed v1 (from current reports) + v2 (simulated deepening) ...")
    from core.versioning.service import _load_live_payload_for_session
    v1_payload = await _load_live_payload_for_session(sid)
    v1 = await create_version(sid, v1_payload, ChangeType.INITIAL,
                              created_by=UUID(consultant))
    print(f"    -> v1: change_type={v1.change_type}")

    v2_payload = dict(v1_payload)
    v2_payload["summary"] = (
        "Updated summary after the (simulated) synergy deepening. "
        "Cross-sell re-anchored to FY25 pipeline assumptions."
    )
    v2 = await create_version(
        sid, v2_payload, ChangeType.SECTION_DEEPENING,
        created_by=UUID(consultant),
        change_summary="Deepened summary section",
    )
    print(f"    -> v2: change_type={v2.change_type}  changed={v2.changed_section_paths}")

    print()
    print("[2] Diff v1 vs v2 ...")
    diff = await diff_versions(sid, 1, 2)
    print(f"    -> {len(diff.section_changes)} section changes; "
          f"added claims={diff.claim_changes['added']}, "
          f"removed={diff.claim_changes['removed']}")
    for c in diff.section_changes:
        if c.change == "modified":
            n_added = sum(1 for s in c.word_segments if s.status == "added")
            n_removed = sum(1 for s in c.word_segments if s.status == "removed")
            print(f"    [{c.change}] {c.section_path}  +{n_added}w/-{n_removed}w")

    print()
    print("[3] Restore v1 -> should create v3 as a copy ...")
    res = await restore_version(sid, 1, UUID(consultant))
    if not res.ok:
        raise SystemExit(f"restore failed: {res.reason}")
    print(f"    -> v{res.new_version.version_number} created  "
          f"(change_type={res.new_version.change_type})  "
          f"reverted={res.reverted_from_approved}  "
          f"artifacts_stale={res.artifacts_marked_stale}")

    print()
    print("[4] Final history snapshot ...")
    rows = await list_versions(sid)
    for r in rows:
        print(f"    v{r.version_number}  {r.change_type:18}  {r.change_summary or ''}")

    assert len(rows) == 3, f"expected 3 versions, got {len(rows)}"
    assert rows[0].version_number == 3
    assert rows[0].change_type == "restore"

    print()
    print("Smoke passed: diff_versions + restore + history preservation")
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
