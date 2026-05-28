"""Operator-side pilot setup CLI — Phase 5 / Week 24 / Day 2.

The counterpart to the in-app onboarding wizard for when the
operator (Yassin) stands up a pilot firm with their content
offline. Every command is IDEMPOTENT — pilot setup is iterative,
so re-running a command updates rather than duplicates.

Four commands, mirroring the wizard's four steps::

    # 1. Firm setup
    python tools/pilot_setup.py create-firm \\
        --name "Blackmont Consulting" \\
        --primary-color "#0B3D2E" \\
        --footer-text "Blackmont Consulting — Private & Confidential"

    # 2. Invite team
    python tools/pilot_setup.py add-user \\
        --firm blackmont-consulting \\
        --email partner@blackmont.com --role firm_admin \\
        --name "Eleanor Vance"

    # 3. Upload library (wraps the W14 hardened ingestion path)
    python tools/pilot_setup.py ingest-library \\
        --firm blackmont-consulting --dir ./blackmont_playbooks \\
        --category playbook --modes m_and_a_diligence,growth_strategy

    # 4. First engagement
    python tools/pilot_setup.py create-engagement \\
        --firm blackmont-consulting \\
        --brief "Assess Project Atlas: acquire TargetCo ..." \\
        --mode m_and_a_diligence \\
        --lead partner@blackmont.com \\
        --reviewer analyst@blackmont.com

Hard rules (W24/D2 spec):
  - Idempotent. create-firm upserts by slug; add-user upserts the
    membership; create-engagement is keyed by (firm, title) so a
    re-run returns the existing engagement; library ingestion
    dedups by file hash.
  - We never seed synthetic content into a pilot firm. The pilot
    brings their own files; this CLI only ingests what the operator
    points it at.
  - No pricing / billing. Commercial terms are handled offline.

The public ``async`` functions are importable so the onboarding
wizard's backend path + the test-suite exercise the SAME code the
CLI runs.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "backend"))
sys.path.insert(0, str(_REPO))


# Built-in consulting modes (source of truth: backend/config/
# consulting_modes.yaml). Loaded lazily so the import doesn't need
# the yaml at module import time.
_FALLBACK_MODES = {
    "general", "market_entry", "due_diligence",
    "growth_strategy", "m_and_a_diligence",
}

# Membership role mapping. The firm_memberships.role CHECK only
# permits 'member' | 'admin'; the user-facing onboarding vocabulary
# is firm_admin / firm_member.
_ROLE_MAP = {
    "firm_admin": "admin",
    "firm_member": "member",
    "admin": "admin",
    "member": "member",
}

_LIBRARY_CATEGORIES = {
    "playbook", "sector_primer", "prior_report",
    "framework", "methodology", "other",
}


def slugify(name: str) -> str:
    """Deterministic url-safe slug from a firm name."""
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower())
    return s.strip("-") or "firm"


def valid_modes() -> set[str]:
    """Load the built-in mode ids from consulting_modes.yaml; fall
    back to the known set if the yaml or pyyaml isn't available."""
    cfg = _REPO / "backend" / "config" / "consulting_modes.yaml"
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data:
            return set(data.keys())
    except Exception:
        pass
    return set(_FALLBACK_MODES)


# ---------------------------------------------------------------------------
# 1. create-firm
# ---------------------------------------------------------------------------


async def create_firm(
    *,
    name: str,
    slug: str | None = None,
    primary_color: str | None = None,
    secondary_color: str | None = None,
    footer_text: str | None = None,
    logo_url: str | None = None,
) -> dict[str, Any]:
    """Upsert a firm by slug. Branding fields land in the
    ``firms.branding`` JSONB. Returns
    ``{firm_id, slug, created, branding}``."""
    import json as _json

    from db.connection import acquire

    slug = slug or slugify(name)
    branding = {
        k: v for k, v in {
            "primary_color": primary_color,
            "secondary_color": secondary_color,
            "footer_text": footer_text,
            "logo_url": logo_url,
        }.items() if v
    }

    async with acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id, branding FROM firms WHERE slug = $1", slug,
        )
        if existing:
            # Merge new branding keys over the existing blob — a
            # re-run that only sets a logo shouldn't wipe the color.
            cur = existing["branding"]
            if isinstance(cur, str):
                try: cur = _json.loads(cur)
                except Exception: cur = {}
            merged = {**(cur or {}), **branding}
            await conn.execute(
                "UPDATE firms SET name = $2, branding = $3::jsonb WHERE slug = $1",
                slug, name, _json.dumps(merged),
            )
            return {
                "firm_id": str(existing["id"]), "slug": slug,
                "created": False, "branding": merged,
            }
        row = await conn.fetchrow(
            """
            INSERT INTO firms (name, slug, branding, metadata)
            VALUES ($1, $2, $3::jsonb, '{}'::jsonb)
            RETURNING id
            """,
            name, slug, _json.dumps(branding),
        )
        return {
            "firm_id": str(row["id"]), "slug": slug,
            "created": True, "branding": branding,
        }


# ---------------------------------------------------------------------------
# 2. add-user
# ---------------------------------------------------------------------------


def _hash_password(plaintext: str) -> str:
    import bcrypt
    return bcrypt.hashpw(
        plaintext.encode("utf-8"), bcrypt.gensalt(rounds=12),
    ).decode("ascii")


async def add_user(
    *,
    firm_slug: str,
    email: str,
    role: str,
    name: str,
    password: str | None = None,
) -> dict[str, Any]:
    """Create the user (if absent) + upsert their firm membership.
    ``role`` is firm_admin | firm_member. Returns
    ``{user_id, firm_id, created, membership_role}``.

    Idempotent: a re-run with a changed role updates the membership;
    an existing user keeps their password (we never reset it on a
    re-run)."""
    from db.connection import acquire

    membership_role = _ROLE_MAP.get(role.strip().lower())
    if membership_role is None:
        raise ValueError(
            f"role must be one of {sorted(_ROLE_MAP)}; got {role!r}"
        )

    async with acquire() as conn:
        firm = await conn.fetchrow(
            "SELECT id FROM firms WHERE slug = $1", firm_slug,
        )
        if not firm:
            raise ValueError(
                f"firm {firm_slug!r} not found — run create-firm first"
            )
        firm_id = str(firm["id"])

        existing = await conn.fetchrow(
            "SELECT id FROM users WHERE email = $1::citext", email,
        )
        if existing:
            user_id = str(existing["id"])
            created = False
            # Keep the user's default firm pointing at this firm if
            # it's currently unset (don't override a real choice).
            await conn.execute(
                "UPDATE users SET default_firm_id = COALESCE(default_firm_id, $1::uuid), "
                "full_name = CASE WHEN full_name = '' THEN $2 ELSE full_name END "
                "WHERE id = $3::uuid",
                firm_id, name, user_id,
            )
        else:
            user_id = str(uuid4())
            # A pilot user gets a random throwaway password unless the
            # operator supplies one; they reset on first login via the
            # W18 email flow. We never log the value.
            pw = password or uuid4().hex
            await conn.execute(
                """
                INSERT INTO users (id, email, password_hash, full_name,
                                   role, default_firm_id)
                VALUES ($1::uuid, $2, $3, $4, 'member', $5::uuid)
                """,
                user_id, email, _hash_password(pw), name, firm_id,
            )
            created = True

        await conn.execute(
            """
            INSERT INTO firm_memberships (firm_id, user_id, role)
            VALUES ($1::uuid, $2::uuid, $3)
            ON CONFLICT (firm_id, user_id) DO UPDATE SET role = EXCLUDED.role
            """,
            firm_id, user_id, membership_role,
        )

    return {
        "user_id": user_id, "firm_id": firm_id,
        "created": created, "membership_role": membership_role,
    }


# ---------------------------------------------------------------------------
# 3. ingest-library  (wraps the W14 hardened path)
# ---------------------------------------------------------------------------


async def ingest_library(
    *,
    firm_slug: str,
    directory: str | Path,
    category: str,
    modes: list[str] | None = None,
    sectors: list[str] | None = None,
    trust_level: str = "firm_vetted",
    uploaded_by: str | None = None,
    recursive: bool = False,
) -> dict[str, Any]:
    """Ingest a directory of the pilot firm's OWN files through the
    W14 hardened ingestion path. Dedup-by-hash makes re-runs safe.
    Returns the per-file results + a roll-up summary."""
    from db.connection import acquire

    from core.firm_library.ingestion import (
        ingest_directory, summarise,
    )

    if category not in _LIBRARY_CATEGORIES:
        raise ValueError(
            f"category must be one of {sorted(_LIBRARY_CATEGORIES)}; "
            f"got {category!r}"
        )
    modes = modes or []
    bad_modes = [m for m in modes if m not in valid_modes()]
    if bad_modes:
        raise ValueError(
            f"unknown modes {bad_modes}; valid: {sorted(valid_modes())}"
        )

    async with acquire() as conn:
        firm = await conn.fetchrow(
            "SELECT id FROM firms WHERE slug = $1", firm_slug,
        )
        if not firm:
            raise ValueError(
                f"firm {firm_slug!r} not found — run create-firm first"
            )
        firm_id = str(firm["id"])

    results = await ingest_directory(
        firm_id=firm_id,
        directory=Path(directory),
        category=category,
        intended_modes=modes,
        sector_tags=sectors or [],
        trust_level=trust_level,
        uploaded_by=uploaded_by,
        recursive=recursive,
    )
    summary = summarise(results)
    return {
        "firm_id": firm_id,
        "summary": summary,
        "files": [
            {
                "filename": r.filename, "status": r.status,
                "chunks_created": r.chunks_created,
                "error_reason": r.error_reason,
            }
            for r in results
        ],
    }


# ---------------------------------------------------------------------------
# 4. create-engagement
# ---------------------------------------------------------------------------


def _derive_title(brief: str) -> str:
    head = brief.strip().splitlines()[0] if brief.strip() else "Engagement"
    return head[:80].strip() or "Engagement"


async def create_engagement(
    *,
    firm_slug: str,
    brief: str,
    mode: str,
    lead_email: str,
    reviewer_email: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """Create the firm's first engagement. Idempotent by
    ``(firm_id, title)`` — a re-run returns the existing engagement
    rather than duplicating. Assigns the lead (engagement
    membership 'lead' + sessions.created_by_user_id) and, if given,
    the reviewer ('reviewer' membership + sessions.review_assigned_to).
    Returns ``{session_id, created, title, mode, lead_user_id,
    reviewer_user_id}``."""
    from db.connection import acquire

    if mode not in valid_modes():
        raise ValueError(
            f"unknown mode {mode!r}; valid: {sorted(valid_modes())}"
        )
    title = title or _derive_title(brief)

    async with acquire() as conn:
        firm = await conn.fetchrow(
            "SELECT id FROM firms WHERE slug = $1", firm_slug,
        )
        if not firm:
            raise ValueError(
                f"firm {firm_slug!r} not found — run create-firm first"
            )
        firm_id = str(firm["id"])

        lead = await conn.fetchrow(
            "SELECT id FROM users WHERE email = $1::citext", lead_email,
        )
        if not lead:
            raise ValueError(
                f"lead {lead_email!r} not found — run add-user first"
            )
        lead_id = str(lead["id"])

        reviewer_id: str | None = None
        if reviewer_email:
            rev = await conn.fetchrow(
                "SELECT id FROM users WHERE email = $1::citext",
                reviewer_email,
            )
            if not rev:
                raise ValueError(
                    f"reviewer {reviewer_email!r} not found — run "
                    "add-user first"
                )
            reviewer_id = str(rev["id"])

        # Idempotency key: (firm_id, title).
        existing = await conn.fetchrow(
            "SELECT id FROM sessions WHERE firm_id = $1::uuid AND title = $2",
            firm_id, title,
        )
        if existing:
            session_id = str(existing["id"])
            created = False
        else:
            session_id = str(uuid4())
            created = True
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO sessions
                        (id, firm_id, title, query, status, report_mode,
                         pipeline_state, created_by_user_id, review_state,
                         review_assigned_to, updated_at)
                    VALUES ($1::uuid, $2::uuid, $3, $4, 'draft', $5,
                            'idle', $6::uuid, 'draft', $7, NOW())
                    """,
                    session_id, firm_id, title, brief, mode,
                    lead_id, reviewer_id,
                )
                await conn.execute(
                    """
                    INSERT INTO engagement_memberships
                        (engagement_id, user_id, role, added_by)
                    VALUES ($1::uuid, $2::uuid, 'lead', $2::uuid)
                    ON CONFLICT (engagement_id, user_id) DO NOTHING
                    """,
                    session_id, lead_id,
                )
                if reviewer_id and reviewer_id != lead_id:
                    await conn.execute(
                        """
                        INSERT INTO engagement_memberships
                            (engagement_id, user_id, role, added_by)
                        VALUES ($1::uuid, $2::uuid, 'reviewer', $3::uuid)
                        ON CONFLICT (engagement_id, user_id) DO NOTHING
                        """,
                        session_id, reviewer_id, lead_id,
                    )

    return {
        "session_id": session_id, "created": created,
        "title": title, "mode": mode,
        "lead_user_id": lead_id, "reviewer_user_id": reviewer_id,
    }


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


async def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    from dotenv import load_dotenv
    load_dotenv(_REPO / ".env")
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/argus",
    )
    from db.connection import close_db, init_db

    await init_db()
    try:
        if args.command == "create-firm":
            return await create_firm(
                name=args.name, slug=args.slug,
                primary_color=args.primary_color,
                secondary_color=args.secondary_color,
                footer_text=args.footer_text,
                logo_url=args.logo_url,
            )
        if args.command == "add-user":
            return await add_user(
                firm_slug=args.firm, email=args.email,
                role=args.role, name=args.name, password=args.password,
            )
        if args.command == "ingest-library":
            return await ingest_library(
                firm_slug=args.firm, directory=args.dir,
                category=args.category,
                modes=_split_csv(args.modes),
                sectors=_split_csv(args.sectors),
                trust_level=args.trust, recursive=args.recursive,
            )
        if args.command == "create-engagement":
            return await create_engagement(
                firm_slug=args.firm, brief=args.brief, mode=args.mode,
                lead_email=args.lead, reviewer_email=args.reviewer,
                title=args.title,
            )
        raise SystemExit(f"unknown command {args.command!r}")
    finally:
        await close_db()


def _split_csv(s: str | None) -> list[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-firm", help="Upsert a pilot firm.")
    p.add_argument("--name", required=True)
    p.add_argument("--slug", default=None)
    p.add_argument("--primary-color", default=None)
    p.add_argument("--secondary-color", default=None)
    p.add_argument("--footer-text", default=None)
    p.add_argument("--logo-url", default=None)

    p = sub.add_parser("add-user", help="Create + add a firm user.")
    p.add_argument("--firm", required=True, help="Firm slug.")
    p.add_argument("--email", required=True)
    p.add_argument("--role", required=True,
                   choices=["firm_admin", "firm_member"])
    p.add_argument("--name", required=True)
    p.add_argument("--password", default=None,
                   help="Optional; random throwaway if omitted.")

    p = sub.add_parser("ingest-library",
                       help="Ingest the firm's own files (W14 path).")
    p.add_argument("--firm", required=True, help="Firm slug.")
    p.add_argument("--dir", required=True)
    p.add_argument("--category", required=True,
                   choices=sorted(_LIBRARY_CATEGORIES))
    p.add_argument("--modes", default="",
                   help="Comma-separated intended modes.")
    p.add_argument("--sectors", default="",
                   help="Comma-separated sector tags.")
    p.add_argument("--trust", default="firm_vetted",
                   choices=["firm_vetted", "firm_uploaded", "firm_draft"])
    p.add_argument("--recursive", action="store_true")

    p = sub.add_parser("create-engagement",
                       help="Create the first engagement.")
    p.add_argument("--firm", required=True, help="Firm slug.")
    p.add_argument("--brief", required=True)
    p.add_argument("--mode", required=True)
    p.add_argument("--lead", required=True, help="Lead user email.")
    p.add_argument("--reviewer", default=None, help="Reviewer email.")
    p.add_argument("--title", default=None)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = asyncio.run(_dispatch(args))

    import json as _json
    print(_json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
