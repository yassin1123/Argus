"""Retention sweep — Phase 5 / Week 23 / Day 2.

Walks every firm's engagements, evaluates each against the
firm's ``retention_days``, and takes the appropriate action:

  - ``noop``  — not yet past the retention window
  - ``flag``  — past the window, not yet flagged. Flag the
                session, schedule the grace period, send the
                firm_admin notification.
  - ``purge`` — flagged + grace expired. Call
                :func:`core.retention.deletion.purge_engagement`.

Usage::

    # dry-run — print decisions, don't act
    python tools/run_retention_sweep.py --dry-run

    # production — flag + notify + purge as the policy dictates
    python tools/run_retention_sweep.py

The sweep runs idempotently. A flagged engagement that's still
in its grace window is a no-op every subsequent call until the
grace expires.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
    from core.retention.deletion import purge_engagement
    from core.retention.policy import (
        DEFAULT_RETENTION_GRACE_DAYS,
        list_expired_sessions,
        mark_flagged,
        notify_firm_admins_of_purge_schedule,
    )

    await init_db()
    try:
        now = datetime.now(tz=timezone.utc)
        decisions = await list_expired_sessions(
            grace_days=args.grace_days, now=now,
        )

        flagged = 0
        purged = 0
        report: dict[str, Any] = {
            "ran_at": now.isoformat(),
            "dry_run": args.dry_run,
            "grace_days": args.grace_days,
            "decisions": [d.to_dict() for d in decisions],
        }

        for d in decisions:
            if d.action == "flag":
                if args.dry_run:
                    continue
                grace_expires = datetime.fromisoformat(d.grace_expires_at)
                await mark_flagged(d.session_id, grace_expires)
                delivered = await notify_firm_admins_of_purge_schedule(
                    firm_id=d.firm_id,
                    session_id=d.session_id,
                    grace_expires_at=grace_expires,
                )
                flagged += 1
                d.reason += f" (notifications={delivered})"
            elif d.action == "purge":
                if args.dry_run:
                    continue
                try:
                    rpt = await purge_engagement(
                        session_id=d.session_id,
                        actor_user_id=None,  # system-initiated
                        purge_reason="retention_sweep",
                    )
                    purged += 1
                    d.reason += (
                        f" (rows={rpt.total_rows_deleted()} "
                        f"files={rpt.files_deleted})"
                    )
                except Exception as e:  # noqa: BLE001
                    d.reason += f" (purge FAILED: {e})"

        report["flagged_count"] = flagged
        report["purged_count"] = purged
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(report, indent=2))
        print(f"--- retention sweep {'(dry-run)' if args.dry_run else ''} ---")
        print(f"  decisions: {len(decisions)}   "
              f"flagged: {flagged}   purged: {purged}")
        for d in decisions:
            print(f"  {d.action:6s}  {d.session_id[:8]}...  {d.reason}")
        if args.out:
            print(f"  report -> {args.out}")
    finally:
        await close_db()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Print decisions; don't flag or purge.",
    )
    ap.add_argument(
        "--grace-days", type=int, default=14,
        help="Grace days between flag + actual purge (default 14).",
    )
    ap.add_argument(
        "--out", default=None,
        help="Optional path to dump the sweep report JSON.",
    )
    args = ap.parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
