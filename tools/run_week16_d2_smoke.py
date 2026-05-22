"""Phase 4 / Week 16 / Day 2 — comments-API live smoke.

Drives a single thread end-to-end against the seeded Meridian
Advisory engagement (W14/D3): consultant creates a section-anchored
comment with an @-mention to the partner, partner replies, consultant
resolves the thread. Asserts that the live review-state read returns
``comments: {unresolved, total}`` and that the unresolved count goes
to zero after resolution.

The script talks to the service layer + the new W16/D2 thread +
mention helpers directly so we exercise the real DB path without
spinning up the FastAPI stack (the docker-compose backend container
on this host can't reach ``argusv3-db-1`` from the ``argus`` network).

Usage::

    python tools/run_week16_d2_smoke.py
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
# Force local-loopback DB DSN since the smoke runs outside Docker.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/argus",
)

FIRM_SLUG = "meridian-advisory"
ENGAGEMENT_TITLE_PREFIX = "Kestrel"


async def _lookup_session_and_users() -> dict[str, str]:
    from db.connection import acquire

    async with acquire() as conn:
        sess = await conn.fetchrow(
            """
            SELECT s.id, s.title, s.firm_id
              FROM sessions s
              JOIN firms f ON f.id = s.firm_id
             WHERE f.slug = $1::text
               AND s.title LIKE $2 || '%'
             ORDER BY s.title ASC LIMIT 1
            """,
            FIRM_SLUG, ENGAGEMENT_TITLE_PREFIX,
        )
        if not sess:
            raise SystemExit(
                f"No '{ENGAGEMENT_TITLE_PREFIX}' engagement under firm "
                f"'{FIRM_SLUG}'. Seed first: tools/seed_sample_workspace.py"
            )
        users = await conn.fetch(
            """
            SELECT u.id, u.email
              FROM users u
              JOIN firm_memberships fm ON fm.user_id = u.id
              JOIN firms f ON f.id = fm.firm_id
             WHERE f.slug = $1::text
             ORDER BY fm.created_at ASC
            """,
            FIRM_SLUG,
        )

    # Meridian seed plants exactly three users: consultant (member),
    # partner (admin), junior analyst (member). Pull by email keyword.
    by_email = {u["email"]: str(u["id"]) for u in users}
    consultant = next(
        (uid for em, uid in by_email.items() if "alex" in em or "consultant" in em),
        None,
    )
    partner = next(
        (uid for em, uid in by_email.items() if "sarah" in em or "partner" in em),
        None,
    )
    if not consultant or not partner:
        # Fall back to the first two firm members.
        ordered = list(by_email.values())
        consultant = consultant or ordered[0]
        partner = partner or ordered[1]

    return {
        "session_id": str(sess["id"]),
        "consultant_id": consultant,
        "partner_id": partner,
        "partner_email": next(
            (em for em, uid in by_email.items() if uid == partner), ""
        ),
    }


async def _cleanup_prior_comments(session_id: str) -> None:
    """Hard-delete any comments left behind by a prior smoke run so
    the script is idempotent. Audit-log integrity hard-rule applies
    in product code; this script is a dev convenience."""
    from db.connection import acquire

    async with acquire() as conn:
        await conn.execute(
            "DELETE FROM comments WHERE session_id = $1::uuid", session_id,
        )


async def main() -> int:
    from db.connection import close_db, init_db

    await init_db()
    try:
        return await _run()
    finally:
        await close_db()


async def _run() -> int:
    ctx = await _lookup_session_and_users()
    sid = UUID(ctx["session_id"])
    consultant = UUID(ctx["consultant_id"])
    partner = UUID(ctx["partner_id"])
    partner_email = ctx["partner_email"]

    await _cleanup_prior_comments(ctx["session_id"])

    from core.comments.mentions import slug_for_user
    from core.comments.service import (
        create_comment,
        reply_to_comment,
        resolve_thread,
    )
    from core.comments.threads import (
        count_unresolved_for_session,
        get_threads_for_session,
    )

    partner_slug = slug_for_user({"email": partner_email})
    body = (
        f"Hey @{partner_slug}, the synergy basis still feels load-bearing — "
        "can you double-check the cross-sell line?"
    )

    print(f"[1] Consultant creates section comment with @{partner_slug} …")
    created = await create_comment(
        session_id=sid, author_id=consultant,
        anchor_type="section",
        anchor_ref={"section_path": "synergy_estimate"},
        body=body,
        mentioned_user_ids=[str(partner)],
    )
    if not created.ok:
        raise SystemExit(f"create failed: {created.reason}")
    root_id = UUID(created.comment_id or "")
    print(f"    -> root comment {root_id}  (mentions: {created.row.get('mentioned_user_ids')})")

    print("[2] Partner replies on the thread …")
    replied = await reply_to_comment(
        parent_comment_id=root_id, author_id=partner,
        body="On it — pulling the latest pipeline numbers now.",
    )
    if not replied.ok:
        raise SystemExit(f"reply failed: {replied.reason}")
    print(f"    -> reply {replied.comment_id}")

    print("[3] List threads for the session …")
    threads = await get_threads_for_session(sid)
    if len(threads) != 1:
        raise SystemExit(f"expected 1 thread, got {len(threads)}")
    thread = threads[0]
    print(
        f"    -> 1 thread, root={thread.root['id'][:8]}…, "
        f"replies={len(thread.replies)}, resolved={thread.resolved}, "
        f"orphaned={thread.orphaned}"
    )
    if len(thread.replies) != 1:
        raise SystemExit(f"expected 1 reply, got {len(thread.replies)}")

    print("[4] Review counts BEFORE resolve …")
    before = await count_unresolved_for_session(sid)
    print(f"    -> {before}")
    if before["unresolved"] != 1 or before["total"] != 1:
        raise SystemExit(f"unexpected before-counts: {before}")

    print("[5] Consultant resolves the thread …")
    resolved = await resolve_thread(root_id, consultant)
    if not resolved.ok:
        raise SystemExit(f"resolve failed: {resolved.reason}")

    print("[6] Review counts AFTER resolve …")
    after = await count_unresolved_for_session(sid)
    print(f"    -> {after}")
    if after["unresolved"] != 0 or after["total"] != 1:
        raise SystemExit(f"unexpected after-counts: {after}")

    print("[7] Final thread state …")
    threads2 = await get_threads_for_session(sid)
    assert threads2[0].resolved is True
    print(
        f"    -> root resolved={threads2[0].resolved}, "
        f"replies still attached={len(threads2[0].replies)}"
    )

    print()
    print("Smoke passed: create -> mention -> reply -> resolve -> count decrement")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
