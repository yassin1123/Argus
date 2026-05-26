"""Extract claim–evidence pairs from past engagements for human labelling.

Phase 5 / Week 21 / Day 1.

Pulls (claim, evidence-quote) pairs from the ``evidence_objects``
table for the engagements the operator selects, stratified across
the verifier's current verdicts so the labelling worksheet has a
balanced sample (some the verifier called supported, some weak,
some unsupported, some contradicted). The worksheet is written
to a JSON file the companion :mod:`label_claims` CLI consumes.

Hard rule (W21/D1 spec): this script does NOT label anything. It
only extracts the pairs + the verifier's current verdict, so the
human labeller can record their independent ground-truth verdict.
Using an LLM to label whether the LLM verifier is right is
circular — that's why this step is unautomatable.

Usage::

    # Extract from a specific firm's recent engagements
    python tools/extract_claims_for_labeling.py \\
        --firm-slug meridian-advisory \\
        --per-verdict 10 \\
        --out backend/eval/golden_set/real_runs/_worksheet_2026-05-26.json

    # Or from one specific session
    python tools/extract_claims_for_labeling.py \\
        --session-id <uuid> \\
        --out worksheet.json

The output file is the worksheet shape :mod:`label_claims` reads.
It is NOT a valid golden-set fixture until a human labels each row.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import UUID

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "backend"))
sys.path.insert(0, str(_REPO))


# Worksheet shape — what :mod:`label_claims` consumes:
#
#   {
#     "version": 1,
#     "generated_at": "<iso>",
#     "rows": [
#       {
#         "id": "wks_<n>",
#         "session_id": "<uuid>",
#         "claim_id": "<id or null>",
#         "claim": "<claim text>",
#         "evidence": "<evidence quote>",
#         "verifier_verdict": "supported_high|...|null",
#         "evidence_source_type": "sec_filing|...",
#         "label": null,                # filled by the labeller
#         "label_rationale": null,      # filled by the labeller
#         "category": null              # filled by the labeller
#       },
#       ...
#     ]
#   }


def _stratify(rows: list[dict[str, Any]], per_verdict: int) -> list[dict[str, Any]]:
    """Pick up to ``per_verdict`` rows per verifier verdict so the
    labelling worksheet isn't dominated by the most common bucket."""
    by_verdict: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        v = (r.get("verifier_verdict") or "unknown").lower()
        by_verdict[v].append(r)
    picked: list[dict[str, Any]] = []
    for verdict, group in sorted(by_verdict.items()):
        picked.extend(group[:per_verdict])
    return picked


async def _fetch_pairs(
    firm_slug: str | None,
    session_id: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Query ``evidence_objects`` for (claim, quote) rows, optionally
    scoped by firm or session. Joins against ``sessions`` to surface
    the firm + verifier metadata where available."""
    from db.connection import acquire

    where_clauses: list[str] = []
    params: list[Any] = []
    if session_id:
        params.append(session_id)
        where_clauses.append(f"e.session_id = ${len(params)}::uuid")
    if firm_slug:
        params.append(firm_slug)
        where_clauses.append(
            f"s.firm_id = (SELECT id FROM firms WHERE slug = ${len(params)}::text)"
        )
    # Always require a non-empty claim AND a non-empty quote (the
    # labellable surface).
    where_clauses.append("e.claim IS NOT NULL AND length(e.claim) > 0")
    where_clauses.append("e.quote  IS NOT NULL AND length(e.quote)  > 0")
    where = " AND ".join(where_clauses)

    sql = (
        "SELECT e.id, e.session_id, e.claim, e.quote, e.source_type, "
        "       e.metadata, s.metadata AS session_metadata "
        f"  FROM evidence_objects e "
        "  JOIN sessions s ON s.id = e.session_id "
        f" WHERE {where} "
        f" ORDER BY e.created_at DESC LIMIT {int(limit)}"
    )
    async with acquire() as conn:
        rows = await conn.fetch(sql, *params)

    out: list[dict[str, Any]] = []
    for i, r in enumerate(rows):
        meta = r["metadata"]
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        # The verifier's latest verdict is denormalised in a few
        # places depending on pipeline version. We look in two
        # spots and accept the first hit; missing → "unknown".
        verifier_verdict = None
        if isinstance(meta, dict):
            verifier_verdict = (
                meta.get("ensemble_verdict")
                or meta.get("verifier_verdict")
                or None
            )
        out.append({
            "id": f"wks_{i+1:04d}",
            "session_id": str(r["session_id"]),
            "claim_id": str(r["id"]),
            "claim": r["claim"],
            "evidence": r["quote"],
            "verifier_verdict": verifier_verdict,
            "evidence_source_type": r["source_type"],
            "label": None,
            "label_rationale": None,
            "category": None,
        })
    return out


def _extract_from_eval_runs(
    eval_runs_dir: Path, limit: int,
) -> list[dict[str, Any]]:
    """Offline extractor — reads committed ``backend/eval_runs/**/*.json``
    files and pulls (claim, evidence) pairs from their ``captured``
    blocks. The Phase 1/2 eval runs (week3, week4, phase1_exit, etc.)
    each saved the full ``claim_rows`` + ``evidence`` lookup, so we
    have real engagement claims + the verifier's actual verdict
    without needing Postgres.

    Used when ``--source eval_runs`` is passed instead of ``--firm-slug``.
    The Day 1 spec asks for ~50 real pairs; this hits that target
    by walking the cached runs from before W22.
    """
    out: list[dict[str, Any]] = []
    files = []
    for sub in sorted(eval_runs_dir.iterdir()):
        if not sub.is_dir():
            continue
        # Skip W22's own output dirs.
        if sub.name.startswith("week22"):
            continue
        for f in sorted(sub.glob("*.json")):
            files.append(f)
    next_id = 1
    for f in files:
        if len(out) >= limit:
            break
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        captured = doc.get("captured") if isinstance(doc, dict) else None
        if not isinstance(captured, dict):
            continue
        claim_rows = captured.get("claim_rows") or []
        evidence_list = captured.get("evidence") or []
        if not claim_rows or not evidence_list:
            continue
        # Build a quick index of evidence objects by id; their
        # ``quote`` is the chunk text we'll pair with the claim.
        ev_idx: dict[str, dict[str, Any]] = {}
        for ev in evidence_list:
            if isinstance(ev, dict) and ev.get("id"):
                ev_idx[str(ev["id"])] = ev
        session_id = doc.get("session_id") or captured.get("session_id")
        for claim in claim_rows:
            if len(out) >= limit:
                break
            if not isinstance(claim, dict):
                continue
            claim_text = claim.get("claim_text") or ""
            ev_ids = claim.get("evidence_object_ids") or []
            if not claim_text or not ev_ids:
                continue
            ev_id = ev_ids[0]
            ev = ev_idx.get(str(ev_id))
            if not ev:
                continue
            evidence_text = ev.get("quote") or ev.get("text") or ""
            # The committed eval_runs slim evidence to metadata only
            # (url + title + source_type). We still emit the row so
            # the operator sees the claim + can do a DB lookup of
            # the chunk text via the recorded evidence_object_id. The
            # row is flagged so label_claims.py knows to skip / defer.
            chunk_text_present = bool(evidence_text)
            verdict = (
                claim.get("ensemble_verdict")
                or claim.get("verifier_verdict")
            )
            out.append({
                "id": f"wks_{next_id:04d}",
                "session_id": str(session_id) if session_id else None,
                "claim_id": str(claim.get("claim_id") or ""),
                "claim": claim_text,
                "evidence": evidence_text,
                "verifier_verdict": verdict,
                "evidence_source_type": ev.get("source_type"),
                "evidence_source_url": ev.get("source_url"),
                "evidence_source_title": ev.get("source_title"),
                "evidence_object_id": str(ev.get("id") or ""),
                "source_eval_run": str(f.relative_to(eval_runs_dir.parent)),
                "chunk_text_present": chunk_text_present,
                "label": None,
                "label_rationale": None,
                "category": None,
            })
            next_id += 1
    return out


async def _main_async(args: argparse.Namespace) -> int:
    from datetime import datetime, timezone

    # Offline path — no DB required. Walks committed eval_runs files.
    if args.source == "eval_runs":
        rows = _extract_from_eval_runs(
            Path(args.eval_runs_dir), args.limit,
        )
    else:
        os.environ.setdefault(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/argus",
        )
        from db.connection import close_db, init_db

        await init_db()
        try:
            rows = await _fetch_pairs(
                firm_slug=args.firm_slug,
                session_id=args.session_id,
                limit=args.limit,
            )
        finally:
            await close_db()

    if args.per_verdict and args.per_verdict > 0:
        rows = _stratify(rows, args.per_verdict)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    worksheet = {
        "version": 1,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "source": {
            "firm_slug": args.firm_slug,
            "session_id": args.session_id,
            "per_verdict": args.per_verdict,
            "limit": args.limit,
        },
        "rows": rows,
    }
    out_path.write_text(json.dumps(worksheet, indent=2))
    print(f"wrote {len(rows)} rows -> {out_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--source", choices=["db", "eval_runs"], default="db",
        help=(
            "Where to pull claim-evidence pairs from. 'db' queries "
            "evidence_objects (requires Postgres). 'eval_runs' walks "
            "the committed backend/eval_runs/**/*.json files and "
            "extracts captured.claim_rows + captured.evidence — no DB "
            "required. The W22/D1 workflow uses 'eval_runs' to seed "
            "Yassin's first labelling batch."
        ),
    )
    ap.add_argument(
        "--firm-slug",
        help="(db source) Restrict to one firm's engagements.",
    )
    ap.add_argument(
        "--session-id",
        help="(db source) Restrict to one session (UUID).",
    )
    ap.add_argument(
        "--eval-runs-dir",
        default="backend/eval_runs",
        help="(eval_runs source) Directory of committed eval runs.",
    )
    ap.add_argument(
        "--limit", type=int, default=400,
        help="Max raw rows to pull before stratification (default 400).",
    )
    ap.add_argument(
        "--per-verdict", type=int, default=10,
        help="Max rows kept per verifier verdict bucket (default 10).",
    )
    ap.add_argument(
        "--out", default="backend/eval/golden_set/real_runs/_worksheet.json",
        help="Output JSON worksheet path.",
    )
    args = ap.parse_args(argv)
    if args.source == "db" and not args.firm_slug and not args.session_id:
        ap.error("--source=db needs --firm-slug or --session-id.")
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
