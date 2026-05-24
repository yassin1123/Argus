"""Phase 4 / Week 18 / Day 2 — notifications wiring live smoke.

Walks the spec's manual smoke against the seeded Meridian Kestrel
engagement: consultant mentions partner in a comment → partner has
an unread notification; consultant submits for review → reviewer
has a notification; partner requests changes → consultant has a
notification. Idempotent.

Usage::

    python tools/run_week18_d2_smoke.py
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
TITLE_PREFIX = "Kestrel"


async def _run() -> int:
    from db.connection import acquire
    from core.comments.mentions import slug_for_user
    from core.comments.service import create_comment
    from core.review.feedback import ReviewFeedback, SectionPointer
    from core.review.service import transition_review
    from core.review.state_machine import ReviewAction

    async with acquire() as conn:
        sess = await conn.fetchrow(
            """
            SELECT s.id, s.title, s.firm_id
              FROM sessions s JOIN firms f ON f.id = s.firm_id
             WHERE f.slug = $1::text AND s.title LIKE $2 || '%'
             ORDER BY s.title ASC LIMIT 1
            """,
            FIRM_SLUG, TITLE_PREFIX,
        )
        if not sess:
            raise SystemExit("Seed Meridian first.")

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

        consultant = _pick("marcus", "consultant")
        partner = _pick("helena", "partner")

        # Reset for an idempotent run.
        await conn.execute(
            "DELETE FROM notifications WHERE session_id = $1::uuid", sess["id"],
        )
        await conn.execute(
            "DELETE FROM review_records WHERE session_id = $1::uuid", sess["id"],
        )
        await conn.execute(
            "DELETE FROM comments WHERE session_id = $1::uuid", sess["id"],
        )
        await conn.execute(
            """
            UPDATE sessions SET review_state = 'draft',
                                review_assigned_to = $2::uuid,
                                submitted_at = NULL, submitted_by = NULL,
                                approved_at = NULL, approved_by = NULL
             WHERE id = $1::uuid
            """,
            sess["id"], UUID(partner),
        )

    sid = UUID(str(sess["id"]))
    print(f"engagement: {sess['title']}")
    print(f"  consultant = {consultant}")
    print(f"  partner    = {partner}")
    print()

    partner_email = next(em for em, uid in users.items() if str(uid) == partner)
    partner_slug = slug_for_user({"email": partner_email})

    print(f"[1] Consultant mentions @{partner_slug} in a comment …")
    res = await create_comment(
        session_id=sid, author_id=UUID(consultant),
        anchor_type="engagement", anchor_ref={},
        body=f"@{partner_slug} — second pair of eyes on synergy?",
        mentioned_user_ids=[partner],
    )
    if not res.ok:
        raise SystemExit(f"comment failed: {res.reason}")
    print(f"    -> comment {res.comment_id}")

    print("[2] Consultant submits engagement for review …")
    submit = await transition_review(
        sid, ReviewAction.SUBMIT_FOR_REVIEW, UUID(consultant),
        reviewer_id=UUID(partner),
    )
    if not submit.ok:
        raise SystemExit(f"submit failed: {submit.reason}")

    print("[3] Partner requests changes …")
    rc = await transition_review(
        sid, ReviewAction.REQUEST_CHANGES, UUID(partner),
        structured_feedback=ReviewFeedback(
            overall_note="Tighten the synergy basis.",
            severity="blocking",
            section_pointers=[SectionPointer(
                section_path="synergy_estimate", note="Source the cross-sell.",
                severity="blocking", resolved=False,
            )],
        ),
    )
    if not rc.ok:
        raise SystemExit(f"request_changes failed: {rc.reason}")

    print()
    print("=== Notification inbox snapshot ===")
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT recipient_id, notification_type, summary, email_status, read, created_at
              FROM notifications
             WHERE session_id = $1::uuid
             ORDER BY created_at ASC, id ASC
            """,
            sid,
        )
    for r in rows:
        rid = str(r["recipient_id"])
        label = "PARTNER" if rid == partner else ("CONSULTANT" if rid == consultant else rid[:8])
        print(f"  [{label:10}] {r['notification_type']:18} email={r['email_status']:8} read={r['read']} "
              f"{r['summary'][:70]}")

    partner_notifs = [r for r in rows if str(r["recipient_id"]) == partner]
    consultant_notifs = [r for r in rows if str(r["recipient_id"]) == consultant]

    print()
    assert any(r["notification_type"] == "mention" for r in partner_notifs), \
        "expected MENTION for partner"
    assert any(r["notification_type"] == "review_requested" for r in partner_notifs), \
        "expected REVIEW_REQUESTED for partner"
    assert any(r["notification_type"] == "changes_requested" for r in consultant_notifs), \
        "expected CHANGES_REQUESTED for consultant"

    print("Smoke passed: mention -> review_requested -> changes_requested wired end-to-end")
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
