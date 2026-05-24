"""Phase 4 / Week 18 / Day 3 — email delivery + preferences smoke.

  1. Capture adapter records a mention email (with firm branding +
     a "View in Argus" link).
  2. Toggle the partner's mention-email preference off → the next
     mention captures no email (in-app notification still lands).

Usage::

    python tools/run_week18_d3_smoke.py
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
os.environ.setdefault("ARGUS_EMAIL_ADAPTER", "capture")
os.environ.setdefault("ARGUS_BASE_URL", "https://argus.example.com")

FIRM_SLUG = "meridian-advisory"
TITLE_PREFIX = "Kestrel"


async def _run() -> int:
    from db.connection import acquire
    from core.comments.mentions import slug_for_user
    from core.comments.service import create_comment
    from core.notifications.email import (
        CaptureEmailAdapter,
        reset_adapter_for_tests,
    )

    # Replace the singleton with a fresh capture instance.
    capture = CaptureEmailAdapter()
    reset_adapter_for_tests(capture)

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
        partner_email = next(em for em, uid in users.items() if str(uid) == partner)
        partner_slug = slug_for_user({"email": partner_email})

        # Clean slate.
        await conn.execute(
            "DELETE FROM notifications WHERE session_id = $1::uuid", sess["id"],
        )
        await conn.execute(
            "DELETE FROM comments WHERE session_id = $1::uuid", sess["id"],
        )
        await conn.execute(
            "DELETE FROM notification_preferences WHERE user_id = $1::uuid",
            UUID(partner),
        )

    sid = UUID(str(sess["id"]))
    print(f"engagement: {sess['title']}  partner={partner_email}")
    print()

    print(f"[1] Consultant mentions @{partner_slug} (default prefs: email ON) …")
    await create_comment(
        session_id=sid, author_id=UUID(consultant),
        anchor_type="engagement", anchor_ref={},
        body=f"@{partner_slug} - second look on synergy?",
        mentioned_user_ids=[partner],
    )
    captured1 = list(capture.captured)
    if not captured1:
        raise SystemExit("expected one captured email")
    cap = captured1[0]
    print(f"    -> 1 captured email to {cap.to_email}")
    print(f"       subject: {cap.subject}")
    assert "View in Argus" in cap.html_body
    assert "argus.example.com" in cap.html_body
    # Branding present (Meridian colours come from the seeded firm row).
    assert "Meridian Advisory" in cap.html_body or "MERIDIAN" in cap.html_body.upper()

    print()
    print(f"[2] Partner toggles mention-email OFF; consultant mentions again …")
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO notification_preferences (user_id, notification_type, in_app, email)
            VALUES ($1::uuid, 'mention', TRUE, FALSE)
            ON CONFLICT (user_id, notification_type) DO UPDATE
              SET in_app = TRUE, email = FALSE
            """,
            UUID(partner),
        )

    capture.clear()
    await create_comment(
        session_id=sid, author_id=UUID(consultant),
        anchor_type="engagement", anchor_ref={},
        body=f"@{partner_slug} - one more thought on Kestrel.",
        mentioned_user_ids=[partner],
    )
    captured2 = list(capture.captured)
    if captured2:
        raise SystemExit(
            f"expected zero captured emails after opt-out, got {len(captured2)}"
        )
    # The in-app row should still have landed (status='skipped').
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT email_status FROM notifications
             WHERE session_id = $1::uuid AND recipient_id = $2::uuid
             ORDER BY created_at DESC LIMIT 1
            """,
            sid, UUID(partner),
        )
    if row is None or row["email_status"] != "skipped":
        raise SystemExit(f"expected latest notification email_status='skipped', got {row}")
    print(f"    -> 0 emails captured; latest notification row email_status={row['email_status']}")

    print()
    print("Smoke passed: capture adapter records email with branding+link; "
          "email pref OFF skips email but keeps the in-app row")
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
