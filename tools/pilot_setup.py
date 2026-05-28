"""Operator-side pilot setup CLI — Phase 5 / Week 24 / Day 2.

The operator's counterpart to the in-app onboarding wizard for when
Yassin stands up a pilot firm with their content offline. Every command
is IDEMPOTENT — pilot setup is iterative, so re-running updates rather
than duplicates.

The actual setup logic lives in ``backend/core/pilot_onboarding`` so it
is shared with the in-app wizard's backend (``api/onboarding.py``) AND
ships inside the deployed backend image. This module is a THIN CLI
wrapper over those functions — it must stay importable from the repo
root for the operator, but the app never imports it.

Four commands, mirroring the wizard's four steps::

    python tools/pilot_setup.py create-firm \\
        --name "Blackmont Consulting" --primary-color "#0B3D2E" \\
        --footer-text "Blackmont Consulting — Private & Confidential"

    python tools/pilot_setup.py add-user --firm blackmont-consulting \\
        --email partner@blackmont.com --role firm_admin --name "Eleanor Vance"

    python tools/pilot_setup.py ingest-library --firm blackmont-consulting \\
        --dir ./blackmont_playbooks --category playbook \\
        --modes m_and_a_diligence,growth_strategy

    python tools/pilot_setup.py create-engagement --firm blackmont-consulting \\
        --brief "Assess Project Atlas ..." --mode m_and_a_diligence \\
        --lead partner@blackmont.com --reviewer analyst@blackmont.com

Hard rules (W24/D2 spec): idempotent; never seed synthetic content into
a pilot firm (they bring their own); no pricing/billing.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "backend"))
sys.path.insert(0, str(_REPO))

# Re-export the shared setup functions so existing callers / tests that
# do ``from tools.pilot_setup import create_firm`` keep working.
from core.pilot_onboarding import (  # noqa: E402
    add_user,
    create_engagement,
    create_firm,
    ingest_library,
    slugify,
    valid_modes,
)

_LIBRARY_CATEGORIES = (
    "playbook", "sector_primer", "prior_report",
    "framework", "methodology", "other",
)


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


__all__ = [
    "add_user",
    "create_engagement",
    "create_firm",
    "ingest_library",
    "slugify",
    "valid_modes",
]


if __name__ == "__main__":
    raise SystemExit(main())
