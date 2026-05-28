"""Apply DB migrations to a managed Postgres — Phase 5 / Week 25 / Day 1.

The dev stack applies migrations via Postgres' ``docker-entrypoint-initdb.d``,
which only runs on a FRESH data volume. A managed production Postgres
(RDS / Cloud SQL / etc.) never sees that hook, so migrations must be
applied explicitly. This runner is idempotent + tracked:

  - records each applied file in a ``schema_migrations`` table,
  - applies only the up-migrations not yet recorded, in numeric order,
  - skips every ``*.down.sql``,
  - wraps each migration in a transaction (all-or-nothing per file).

Usage (DATABASE_URL must point at the target managed DB, sslmode=require)::

    DATABASE_URL=postgresql://user:pass@host:5432/argus?sslmode=require \\
        python deploy/apply_migrations.py
    python deploy/apply_migrations.py --dry-run   # list pending, apply none
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_MIGRATIONS = _REPO / "backend" / "db" / "migrations"

_NUM_RE = re.compile(r"^(\d+)_")


def _up_migrations() -> list[Path]:
    """All up-migrations (NNN_*.sql, excluding *.down.sql) in numeric order."""
    files = [
        p for p in _MIGRATIONS.glob("*.sql")
        if not p.name.endswith(".down.sql") and _NUM_RE.match(p.name)
    ]
    return sorted(files, key=lambda p: (int(_NUM_RE.match(p.name).group(1)), p.name))


async def _run(dry_run: bool) -> int:
    import asyncpg

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("FATAL: DATABASE_URL is not set.", file=sys.stderr)
        return 2

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename    TEXT PRIMARY KEY,
                applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        applied = {
            r["filename"]
            for r in await conn.fetch("SELECT filename FROM schema_migrations")
        }
        pending = [p for p in _up_migrations() if p.name not in applied]

        if not pending:
            print(f"up to date — {len(applied)} migrations already applied.")
            return 0

        print(f"{len(pending)} pending migration(s):")
        for p in pending:
            print(f"  - {p.name}")
        if dry_run:
            print("(dry-run — applied none)")
            return 0

        for p in pending:
            sql = p.read_text(encoding="utf-8")
            try:
                async with conn.transaction():
                    await conn.execute(sql)
                    await conn.execute(
                        "INSERT INTO schema_migrations (filename) VALUES ($1)",
                        p.name,
                    )
                print(f"  applied {p.name}")
            except Exception as e:  # noqa: BLE001
                print(f"FATAL: {p.name} failed: {e}", file=sys.stderr)
                return 1
        print(f"done — applied {len(pending)} migration(s).")
        return 0
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="List pending migrations without applying.")
    args = ap.parse_args(argv)
    return asyncio.run(_run(args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
