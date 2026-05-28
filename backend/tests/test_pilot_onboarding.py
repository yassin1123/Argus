"""Pilot onboarding tests — Phase 5 / Week 24 / Day 2.

Live-DB integration tests (same pattern as test_firm_library_service):
per-test unique slugs, embeddings stubbed to avoid OpenAI, cleanup at
the end. They pin the four onboarding contracts:

  1. test_onboarding_wizard_completes_e2e_firm_setup — the wizard's
     backend path (the onboarding API functions) takes a fresh firm
     from branding → team → library → engagement, and /status reports
     complete.
  2. test_pilot_setup_cli_idempotent — re-running every command is a
     no-op (no duplicate firm / user / engagement).
  3. test_pilot_setup_creates_firm_with_users_library_engagement —
     the full operator-CLI flow lands the firm, users, library, and
     engagement in the DB.
  4. test_first_engagement_template_briefs_load — the reference briefs
     parse + load for every supported mode.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = _BACKEND.parent
for p in (str(_BACKEND), str(_REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

from eval.pilot_briefs import SUPPORTED_BRIEF_MODES, load_pilot_briefs
from tools.pilot_setup import (
    add_user, create_engagement, create_firm, ingest_library, slugify,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def _db_pool():
    from db.connection import close_db, init_db

    await init_db()
    try:
        yield
    finally:
        await close_db()


@pytest.fixture
def stub_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hash-based 1536-dim embeddings — no OpenAI call in the ingest
    path. The ingestion module imports embed_texts at module level."""
    import hashlib

    async def _stub(texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            full = (h * (1536 // len(h) + 1))[:1536]
            out.append([(b - 128) / 128.0 for b in full])
        return out

    import core.firm_library.ingestion as ing
    monkeypatch.setattr(ing, "embed_texts", _stub)


async def _cleanup_firm(slug: str, emails: list[str]) -> None:
    """Tear down everything a test created for ``slug``."""
    from db.connection import acquire

    async with acquire() as conn:
        firm = await conn.fetchrow("SELECT id FROM firms WHERE slug = $1", slug)
        if firm:
            fid = firm["id"]
            await conn.execute(
                "DELETE FROM sessions WHERE firm_id = $1::uuid", fid,
            )
            await conn.execute(
                "DELETE FROM chunks WHERE firm_content_id IN "
                "(SELECT id FROM firm_content WHERE firm_id = $1::uuid)", fid,
            )
            await conn.execute(
                "DELETE FROM firm_content WHERE firm_id = $1::uuid", fid,
            )
            await conn.execute(
                "DELETE FROM firm_memberships WHERE firm_id = $1::uuid", fid,
            )
        if emails:
            await conn.execute(
                "DELETE FROM users WHERE email = ANY($1::citext[])", emails,
            )
        await conn.execute("DELETE FROM firms WHERE slug = $1", slug)


def _uniq() -> str:
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# 4. Template briefs load (no DB)
# ---------------------------------------------------------------------------


def test_first_engagement_template_briefs_load() -> None:
    briefs = load_pilot_briefs()
    # Every supported mode has at least one reference brief.
    for mode in SUPPORTED_BRIEF_MODES:
        assert mode in briefs, f"no template briefs for mode {mode!r}"
        assert len(briefs[mode]) >= 1
    # M&A is the pilot's likely first mode — at least 2 examples.
    assert len(briefs["m_and_a_diligence"]) >= 2
    # Each brief is fully formed.
    for items in briefs.values():
        for b in items:
            assert b.title.strip()
            assert b.why_good.strip()
            assert len(b.body) > 200, f"{b.id}: brief body too thin"
            assert b.research_targets, f"{b.id}: no research targets"
    # Mode filter returns only that mode.
    only_ma = load_pilot_briefs("m_and_a_diligence")
    assert set(only_ma.keys()) == {"m_and_a_diligence"}


# ---------------------------------------------------------------------------
# 3. Full operator-CLI flow creates firm + users + library + engagement
# ---------------------------------------------------------------------------


async def test_pilot_setup_creates_firm_with_users_library_engagement(
    stub_embed: None, tmp_path: Path,
) -> None:
    from db.connection import acquire

    name = f"Pilot Test Firm {_uniq()}"
    slug = slugify(name)
    partner = f"partner-{_uniq()}@pilot.invalid"
    analyst = f"analyst-{_uniq()}@pilot.invalid"
    try:
        firm = await create_firm(
            name=name, primary_color="#0B3D2E",
            footer_text="Pilot — Confidential",
        )
        assert firm["created"] is True
        assert firm["slug"] == slug
        assert firm["branding"]["primary_color"] == "#0B3D2E"

        u1 = await add_user(
            firm_slug=slug, email=partner, role="firm_admin",
            name="Test Partner",
        )
        assert u1["created"] is True
        assert u1["membership_role"] == "admin"
        u2 = await add_user(
            firm_slug=slug, email=analyst, role="firm_member",
            name="Test Analyst",
        )
        assert u2["membership_role"] == "member"

        # A real file to ingest through the W14 path.
        doc = tmp_path / "ma_carveout_playbook.md"
        doc.write_text(
            "# Carve-out playbook\n\n"
            "Standalone EBITDA must load stranded costs and TSA exit "
            "costs. Triangulate against comparable carve-out "
            "transactions before trusting the vendor adjusted-EBITDA "
            "bridge.\n",
            encoding="utf-8",
        )
        lib = await ingest_library(
            firm_slug=slug, directory=tmp_path, category="playbook",
            modes=["m_and_a_diligence"],
        )
        assert lib["summary"]["by_status"]["ready"] >= 1

        eng = await create_engagement(
            firm_slug=slug,
            brief="Assess Project Atlas: acquire the Home & Living "
                  "carve-out. Standalone margin and integration risk "
                  "decide the recommendation.",
            mode="m_and_a_diligence",
            lead_email=partner, reviewer_email=analyst,
        )
        assert eng["created"] is True
        assert eng["mode"] == "m_and_a_diligence"
        assert eng["reviewer_user_id"] == u2["user_id"]

        # Verify DB state.
        async with acquire() as conn:
            sess = await conn.fetchrow(
                "SELECT firm_id, report_mode, created_by_user_id, "
                "review_assigned_to FROM sessions WHERE id = $1::uuid",
                eng["session_id"],
            )
            assert str(sess["firm_id"]) == firm["firm_id"]
            assert sess["report_mode"] == "m_and_a_diligence"
            assert str(sess["created_by_user_id"]) == u1["user_id"]
            assert str(sess["review_assigned_to"]) == u2["user_id"]

            roles = {
                r["role"] for r in await conn.fetch(
                    "SELECT role FROM engagement_memberships "
                    "WHERE engagement_id = $1::uuid", eng["session_id"],
                )
            }
            assert "lead" in roles and "reviewer" in roles

            lib_count = await conn.fetchval(
                "SELECT COUNT(*)::int FROM firm_content WHERE firm_id = $1::uuid",
                firm["firm_id"],
            )
            assert lib_count >= 1
    finally:
        await _cleanup_firm(slug, [partner, analyst])


# ---------------------------------------------------------------------------
# 2. Idempotency
# ---------------------------------------------------------------------------


async def test_pilot_setup_cli_idempotent() -> None:
    from db.connection import acquire

    name = f"Idempotent Firm {_uniq()}"
    slug = slugify(name)
    lead = f"lead-{_uniq()}@pilot.invalid"
    try:
        f1 = await create_firm(name=name, primary_color="#111111")
        f2 = await create_firm(name=name, footer_text="added later")
        assert f1["firm_id"] == f2["firm_id"]
        assert f1["created"] is True and f2["created"] is False
        # The merge kept the original color AND added the footer.
        assert f2["branding"]["primary_color"] == "#111111"
        assert f2["branding"]["footer_text"] == "added later"

        a1 = await add_user(firm_slug=slug, email=lead, role="firm_member", name="L")
        a2 = await add_user(firm_slug=slug, email=lead, role="firm_admin", name="L")
        assert a1["user_id"] == a2["user_id"]
        assert a1["created"] is True and a2["created"] is False
        assert a2["membership_role"] == "admin"  # role updated, not duplicated

        e1 = await create_engagement(
            firm_slug=slug, brief="A repeatable engagement brief here.",
            mode="general", lead_email=lead, title="Repeat Engagement",
        )
        e2 = await create_engagement(
            firm_slug=slug, brief="A repeatable engagement brief here.",
            mode="general", lead_email=lead, title="Repeat Engagement",
        )
        assert e1["session_id"] == e2["session_id"]
        assert e1["created"] is True and e2["created"] is False

        # Exactly one of each.
        async with acquire() as conn:
            fid = f1["firm_id"]
            assert await conn.fetchval(
                "SELECT COUNT(*)::int FROM firms WHERE slug = $1", slug,
            ) == 1
            assert await conn.fetchval(
                "SELECT COUNT(*)::int FROM firm_memberships WHERE firm_id = $1::uuid",
                fid,
            ) == 1
            assert await conn.fetchval(
                "SELECT COUNT(*)::int FROM sessions WHERE firm_id = $1::uuid",
                fid,
            ) == 1
    finally:
        await _cleanup_firm(slug, [lead])


# ---------------------------------------------------------------------------
# 1. Wizard backend completes the e2e firm setup
# ---------------------------------------------------------------------------


async def test_onboarding_wizard_completes_e2e_firm_setup(
    stub_embed: None, tmp_path: Path,
) -> None:
    """Drives the wizard's actual backend (the onboarding API
    functions) end-to-end and asserts /status reports complete."""
    from api.onboarding import (
        BrandingBody, EngagementBody, TeamMemberBody,
        create_first_engagement, invite_team_member,
        onboarding_status, set_firm_branding,
    )

    name = f"Wizard Firm {_uniq()}"
    slug = slugify(name)
    admin_email = f"admin-{_uniq()}@pilot.invalid"
    member_email = f"member-{_uniq()}@pilot.invalid"
    try:
        # Bootstrap: the firm + the firm_admin must already exist (the
        # wizard runs as a firm_admin on a fresh firm). Use the shared
        # functions for the bootstrap, then drive the rest via the API.
        firm = await create_firm(name=name)
        admin = await add_user(
            firm_slug=slug, email=admin_email, role="firm_admin",
            name="Wizard Admin",
        )
        admin_user = {
            "user_id": admin["user_id"],
            "role": "member",
            "default_firm_id": firm["firm_id"],
            "default_firm_role": "admin",
        }

        # Step 1 — branding via the API.
        r1 = await set_firm_branding(
            BrandingBody(primary_color="#1A2B3C", footer_text="Confidential"),
            user=admin_user,
        )
        assert r1["ok"] is True

        # Step 2 — invite a teammate via the API.
        r2 = await invite_team_member(
            TeamMemberBody(email=member_email, name="Wizard Member", role="firm_member"),
            user=admin_user,
        )
        assert r2["ok"] is True

        # Step 3 — library (the wizard uses the existing upload route;
        # exercise the same ingestion the route runs).
        doc = tmp_path / "method.md"
        doc.write_text(
            "# Method\n\nAlways decompose like-for-like growth into "
            "traffic, basket, and price/mix before trusting a headline "
            "number.\n",
            encoding="utf-8",
        )
        from tools.pilot_setup import ingest_library as _ingest
        await _ingest(
            firm_slug=slug, directory=tmp_path, category="methodology",
            modes=["general"],
        )

        # Step 4 — first engagement via the API.
        r4 = await create_first_engagement(
            EngagementBody(
                brief="Decide build vs buy for the missing capability, "
                      "with TCO and reversibility.",
                mode="general", lead_email=admin_email,
            ),
            user=admin_user,
        )
        assert r4["ok"] is True

        # /status must now report all four steps complete.
        status = await onboarding_status(user=admin_user)
        assert status["steps"]["firm_setup"] is True
        assert status["steps"]["invite_team"] is True
        assert status["steps"]["upload_library"] is True
        assert status["steps"]["first_engagement"] is True
        assert status["complete"] is True
    finally:
        await _cleanup_firm(slug, [admin_email, member_email])
