"""Restore a firm backup into the current DB.

Phase 5 / Week 23 / Day 4. Idempotent via ON CONFLICT (id) DO
NOTHING — restoring twice doesn't duplicate.

Usage::

    python tools/restore_firm_data.py --in backups/meridian-2026-05-27.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
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
    from db.connection import close_db, init_db
    from core.backup import BackupArchive, restore_firm

    payload = json.loads(Path(args.in_path).read_text(encoding="utf-8"))
    archive = BackupArchive.from_dict(payload)

    await init_db()
    try:
        counts = await restore_firm(archive)
    finally:
        await close_db()

    print(f"restore: archive_version={archive.version} "
          f"exported_at={archive.exported_at}")
    for table, n in counts.items():
        print(f"  {table:32s} {n:5d} rows inserted")
    print(f"  total: {sum(counts.values())} rows")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="in_path", required=True,
                    help="Backup JSON archive path.")
    return asyncio.run(_run(ap.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
