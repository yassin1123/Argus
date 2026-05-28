"""Pilot onboarding setup — Phase 5 / Week 24 / Day 2 (relocated D4).

The idempotent firm/user/library/engagement setup functions shared by
BOTH the in-app onboarding wizard (``api/onboarding.py``) and the
operator CLI (``tools/pilot_setup.py``). This lives under
``backend/core`` — NOT ``tools/`` — because the deployed backend image
only contains ``backend/``; application code must never import from
``tools/`` (that broke the container boot in W24/D4).

Every function is idempotent: create_firm upserts by slug, add_user
upserts the membership, create_engagement is keyed by (firm, title),
and library ingestion dedups by file hash.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from uuid import uuid4

# Built-in consulting modes (source of truth: backend/config/
# consulting_modes.yaml). Fallback set if the yaml / pyyaml is absent.
_FALLBACK_MODES = {
    "general", "market_entry", "due_diligence",
    "growth_strategy", "m_and_a_diligence",
}

# Membership role mapping. The firm_memberships.role CHECK only permits
# 'member' | 'admin'; the user-facing vocabulary is firm_admin /
# firm_member.
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

# backend/ — this file is backend/core/pilot_onboarding/__init__.py
_BACKEND = Path(__file__).resolve().parents[2]


def slugify(name: str) -> str:
    """Deterministic url-safe slug from a firm name."""
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower())
    return s.strip("-") or "firm"


def valid_modes() -> set[str]:
    """Load the built-in mode ids from consulting_modes.yaml; fall back
    to the known set if the yaml or pyyaml isn't available."""
    cfg = _BACKEND / "config" / "consulting_modes.yaml"
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
    ``{user_id, firm_id, created, membership_role}``. Idempotent."""
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
            await conn.execute(
                "UPDATE users SET default_firm_id = COALESCE(default_firm_id, $1::uuid), "
                "full_name = CASE WHEN full_name = '' THEN $2 ELSE full_name END "
                "WHERE id = $3::uuid",
                firm_id, name, user_id,
            )
        else:
            user_id = str(uuid4())
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
    """Ingest a directory of the pilot firm's OWN files through the W14
    hardened ingestion path. Dedup-by-hash makes re-runs safe."""
    from db.connection import acquire

    from core.firm_library.ingestion import ingest_directory, summarise

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
    ``(firm_id, title)``. Assigns the lead + optional reviewer."""
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


__all__ = [
    "add_user",
    "create_engagement",
    "create_firm",
    "ingest_library",
    "slugify",
    "valid_modes",
]
