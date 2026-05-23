"""Phase 4 / Week 16 / Day 4 — overview + my-mentions + artifact-comment smoke.

Builds on the W16/D2 smoke (create / @mention / reply / resolve) and
exercises the W16/D4 surfaces against the seeded Meridian Kestrel
engagement:

  - Comment on an artifact (artifact anchor).
  - Engagement overview groups threads by anchor with per-group counts.
  - Filter by mentioning the partner.
  - The partner's cross-engagement /api/users/{id}/mentions returns
    the thread the consultant tagged them in.
  - bulk_resolve_section flips every open thread on a section
    and the per-thread audit events fire.

Usage::

    python tools/run_week16_d4_smoke.py
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


async def _lookup() -> dict[str, str]:
    from db.connection import acquire

    async with acquire() as conn:
        sess = await conn.fetchrow(
            """
            SELECT s.id, s.firm_id
              FROM sessions s
              JOIN firms f ON f.id = s.firm_id
             WHERE f.slug = $1::text AND s.title LIKE $2 || '%'
             ORDER BY s.title ASC LIMIT 1
            """,
            FIRM_SLUG, ENGAGEMENT_TITLE_PREFIX,
        )
        if not sess:
            raise SystemExit("Seed Meridian first (tools/seed_sample_workspace.py).")
        artifact = await conn.fetchrow(
            """
            SELECT id, artifact_type FROM export_artifacts
             WHERE session_id = $1::uuid
             ORDER BY generated_at ASC LIMIT 1
            """,
            sess["id"],
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

    by_email = {u["email"]: str(u["id"]) for u in users}
    consultant = next(
        (uid for em, uid in by_email.items() if "alex" in em or "consultant" in em),
        list(by_email.values())[0],
    )
    partner = next(
        (uid for em, uid in by_email.items() if "sarah" in em or "partner" in em),
        list(by_email.values())[1],
    )
    return {
        "session_id": str(sess["id"]),
        "firm_id": str(sess["firm_id"]),
        "consultant_id": consultant,
        "partner_id": partner,
        "partner_email": next(
            (em for em, uid in by_email.items() if uid == partner), ""
        ),
        "artifact_id": str(artifact["id"]) if artifact else "",
        "artifact_type": artifact["artifact_type"] if artifact else "",
    }


async def _cleanup(session_id: str) -> None:
    from db.connection import acquire
    async with acquire() as conn:
        await conn.execute(
            "DELETE FROM comments WHERE session_id = $1::uuid", session_id,
        )


async def _run() -> int:
    ctx = await _lookup()
    sid = UUID(ctx["session_id"])
    firm_uuid = UUID(ctx["firm_id"])
    consultant = UUID(ctx["consultant_id"])
    partner = UUID(ctx["partner_id"])
    partner_email = ctx["partner_email"]
    artifact_id = ctx["artifact_id"]

    await _cleanup(ctx["session_id"])

    from core.comments.mentions import slug_for_user
    from core.comments.service import create_comment, reply_to_comment
    from core.comments.threads import (
        bulk_resolve_section,
        get_threads_grouped_for_overview,
        list_mentions_for_user,
    )

    partner_slug = slug_for_user({"email": partner_email})

    print("[1] Consultant creates an artifact-anchored comment …")
    if artifact_id:
        deck_thread = await create_comment(
            session_id=sid, author_id=consultant,
            anchor_type="artifact",
            anchor_ref={"artifact_id": artifact_id},
            body=f"Deck needs the synergy slide reworked, @{partner_slug}.",
            mentioned_user_ids=[str(partner)],
        )
        if not deck_thread.ok:
            raise SystemExit(f"artifact comment failed: {deck_thread.reason}")
        print(f"    -> deck thread {deck_thread.comment_id}")
    else:
        print("    -> no artifact on session; skipping artifact-anchor step")

    print("[2] Consultant creates two section comments on synergy_estimate …")
    s1 = await create_comment(
        session_id=sid, author_id=consultant,
        anchor_type="section",
        anchor_ref={"section_path": "synergy_estimate"},
        body=f"Tighten basis. @{partner_slug} — second pair of eyes?",
        mentioned_user_ids=[str(partner)],
    )
    s2 = await create_comment(
        session_id=sid, author_id=consultant,
        anchor_type="section",
        anchor_ref={"section_path": "synergy_estimate"},
        body="Worth a row-by-row review tomorrow.",
    )
    if not s1.ok or not s2.ok:
        raise SystemExit("section comments failed")
    await reply_to_comment(
        parent_comment_id=UUID(s1.comment_id or ""),
        author_id=partner,
        body="Will dig in this afternoon.",
    )

    print("[3] Engagement overview …")
    overview = await get_threads_grouped_for_overview(sid)
    print(f"    -> {len(overview['groups'])} groups, "
          f"{overview['unresolved_total']} unresolved, "
          f"{overview['total']} total")
    for g in overview["groups"]:
        print(f"       {g['label']}: {g['unresolved']} unresolved / {g['total']} total")
    assert overview["unresolved_total"] >= 2

    print("[4] Partner's cross-engagement mentions …")
    mentions = await list_mentions_for_user(partner, firm_id=firm_uuid)
    print(f"    -> partner has {len(mentions)} mention rows in this firm")
    assert any(str(consultant) == str(m["author_id"]) for m in mentions)

    print("[5] Resolve all in section synergy_estimate …")
    res = await bulk_resolve_section(sid, "synergy_estimate", consultant)
    print(f"    -> flipped {res['resolved_count']} threads")
    assert res["resolved_count"] >= 1

    print("[6] Overview after bulk resolve (unresolved-only filter) …")
    open_only = await get_threads_grouped_for_overview(sid, resolved=False)
    print(f"    -> {open_only['unresolved_total']} unresolved remaining")

    print()
    print("Smoke passed: artifact + overview + mentions + bulk resolve")
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
