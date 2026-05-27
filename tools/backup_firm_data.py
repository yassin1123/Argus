"""Backup a firm's full data to a portable JSON archive.

Phase 5 / Week 23 / Day 4. Pilot insurance — run before any
risky migration / deploy + at scheduled cadence.

Usage::

    python tools/backup_firm_data.py \\
        --firm-slug meridian-advisory \\
        --out backups/meridian-2026-05-27.json

Restore is the companion ``tools/restore_firm_data.py``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "backend"))
sys.path.insert(0, str(_REPO))


async def _run(args: argparse.Namespace) -> int:
    from dotenv import load_dotenv
    load_dotenv(_REPO / ".env")
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/argus",
    )
    from db.connection import close_db, init_db, acquire
    from core.backup import backup_firm

    await init_db()
    try:
        # Resolve firm_id from slug if given.
        firm_id = args.firm_id
        if not firm_id and args.firm_slug:
            async with acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id FROM firms WHERE slug = $1::text",
                    args.firm_slug,
                )
            if not row:
                print(f"firm with slug {args.firm_slug!r} not found")
                return 2
            firm_id = str(row["id"])
        if not firm_id:
            print("--firm-id or --firm-slug required")
            return 2

        archive = await backup_firm(firm_id)
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(archive.to_dict(), indent=2))
        print(f"backup: {archive.total_rows()} rows across "
              f"{len([k for k in archive.__dataclass_fields__])} surfaces "
              f"-> {out_path}")
    finally:
        await close_db()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--firm-id", help="Firm UUID.")
    ap.add_argument("--firm-slug", help="Firm slug (alternative to --firm-id).")
    ap.add_argument(
        "--out",
        default=f"backups/firm_{datetime.now(tz=timezone.utc):%Y%m%d_%H%M%S}.json",
    )
    return asyncio.run(_run(ap.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
