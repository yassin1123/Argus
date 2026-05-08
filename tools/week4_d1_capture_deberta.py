"""Phase 1 / Week 4 / Day 1 — capture real-evidence DeBERTa label distribution.

Queries claim_support_rows from the two clean post-fix sessions (AAPL +
MSFT, both 100% nli_label populated after the sub-batch chunking fix
landed) and writes the empirical distribution Day 5 will need for
threshold tuning.

Output: ``docs/eval/week4_d1_deberta_distribution.json``

Includes:
  - count + mean + median nli_confidence per nli_label, grouped by ticker
  - aggregate across both tickers
  - 10-bucket confidence histogram per label (0.0–0.1 ... 0.9–1.0)
  - tuning_hypothesis (Day 1's read of whether the current 0.7 high-conf
    threshold looks fine or whether Day 5 will need to think harder)
  - run_window: timestamps of the captured sessions for reproducibility

Run from repo root:
    python tools/week4_d1_capture_deberta.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")

from db.connection import acquire, close_db, init_db  # noqa: E402

# The two sessions whose claim_support_rows have nli_label populated
# (verified via SELECT count(*)…WHERE nli_label IS NOT NULL AND
# nli_label != 'unknown'). TSLA failed twice on a separate Anthropic
# 400 / analyst structured-output issue and never wrote
# claim_support_rows; surfaced separately, see Day 1 commit message.
RUN_START_UTC = datetime(2026, 5, 8, 2, 50, 0, tzinfo=timezone.utc)  # cuts off the pre-fix sessions

OUT_PATH = _REPO_ROOT / "docs" / "eval" / "week4_d1_deberta_distribution.json"


async def main() -> None:
    await init_db()
    try:
        async with acquire() as conn:
            sessions = await conn.fetch(
                """
                SELECT id, metadata->>'ticker' AS ticker, created_at,
                       (SELECT count(*) FROM claim_support_rows
                          WHERE session_id=s.id) AS n_total,
                       (SELECT count(*) FROM claim_support_rows
                          WHERE session_id=s.id
                            AND nli_label IS NOT NULL
                            AND nli_label != 'unknown') AS n_real
                FROM sessions s
                WHERE metadata->>'week3_e2e' = 'true'
                  AND created_at > $1::timestamptz
                ORDER BY created_at ASC
                """,
                RUN_START_UTC,
            )
            captured_sessions = [
                {
                    "session_id": str(r["id"]),
                    "ticker": r["ticker"],
                    "created_at": r["created_at"].isoformat(),
                    "claims_total": int(r["n_total"]),
                    "claims_real_label": int(r["n_real"]),
                }
                for r in sessions
                if int(r["n_real"]) > 0
            ]

            ticker_summary = await conn.fetch(
                """
                SELECT s.metadata->>'ticker' AS ticker,
                       c.nli_label,
                       COUNT(*) AS n,
                       ROUND(AVG(c.nli_confidence)::numeric, 4) AS mean_conf,
                       ROUND((percentile_cont(0.5) WITHIN GROUP
                              (ORDER BY c.nli_confidence))::numeric, 4) AS median_conf
                FROM claim_support_rows c
                JOIN sessions s ON s.id = c.session_id
                WHERE s.metadata->>'week3_e2e' = 'true'
                  AND s.created_at > $1::timestamptz
                  AND c.nli_label IS NOT NULL
                  AND c.nli_label != 'unknown'
                GROUP BY ticker, c.nli_label
                ORDER BY ticker, c.nli_label
                """,
                RUN_START_UTC,
            )
            per_ticker: dict[str, dict] = {}
            for r in ticker_summary:
                per_ticker.setdefault(r["ticker"], {})[r["nli_label"]] = {
                    "count": int(r["n"]),
                    "mean_confidence": float(r["mean_conf"]),
                    "median_confidence": float(r["median_conf"]),
                }

            agg_summary = await conn.fetch(
                """
                SELECT c.nli_label,
                       COUNT(*) AS n,
                       ROUND(AVG(c.nli_confidence)::numeric, 4) AS mean_conf,
                       ROUND((percentile_cont(0.5) WITHIN GROUP
                              (ORDER BY c.nli_confidence))::numeric, 4) AS median_conf
                FROM claim_support_rows c
                JOIN sessions s ON s.id = c.session_id
                WHERE s.metadata->>'week3_e2e' = 'true'
                  AND s.created_at > $1::timestamptz
                  AND c.nli_label IS NOT NULL
                  AND c.nli_label != 'unknown'
                GROUP BY c.nli_label
                ORDER BY c.nli_label
                """,
                RUN_START_UTC,
            )
            aggregate: dict[str, dict] = {}
            for r in agg_summary:
                aggregate[r["nli_label"]] = {
                    "count": int(r["n"]),
                    "mean_confidence": float(r["mean_conf"]),
                    "median_confidence": float(r["median_conf"]),
                }

            # 10-bucket confidence histogram per label.
            hist_rows = await conn.fetch(
                """
                SELECT c.nli_label,
                       LEAST(9, FLOOR(c.nli_confidence * 10)::int) AS bucket,
                       COUNT(*) AS n
                FROM claim_support_rows c
                JOIN sessions s ON s.id = c.session_id
                WHERE s.metadata->>'week3_e2e' = 'true'
                  AND s.created_at > $1::timestamptz
                  AND c.nli_label IS NOT NULL
                  AND c.nli_label != 'unknown'
                GROUP BY c.nli_label, bucket
                ORDER BY c.nli_label, bucket
                """,
                RUN_START_UTC,
            )
            histograms: dict[str, list[int]] = {}
            for r in hist_rows:
                histograms.setdefault(r["nli_label"], [0] * 10)
                histograms[r["nli_label"]][int(r["bucket"])] = int(r["n"])
    finally:
        await close_db()

    # Day 1 sanity hypothesis. Spec rule: "If entailment median ≥ 0.85 AND
    # neutral median ≤ 0.5 → current 0.7 threshold likely fine; Day 5 may
    # not need to touch it. If they overlap (entailment ≤ 0.7 OR neutral
    # ≥ 0.6) → Day 5 will need to think harder."
    hyp_lines: list[str] = []
    ent_med = aggregate.get("entailment", {}).get("median_confidence")
    neu_med = aggregate.get("neutral", {}).get("median_confidence")
    con_med = aggregate.get("contradiction", {}).get("median_confidence")
    if ent_med is None and neu_med is None:
        hyp_lines.append("No entailment or neutral rows — cannot assess threshold.")
    else:
        if ent_med is not None:
            hyp_lines.append(f"entailment median confidence = {ent_med}")
        if neu_med is not None:
            hyp_lines.append(f"neutral median confidence = {neu_med}")
        if con_med is not None:
            hyp_lines.append(f"contradiction median confidence = {con_med}")
        if (ent_med is not None and ent_med < 0.7) or (
            neu_med is not None and neu_med > 0.6
        ):
            hyp_lines.append(
                "OVERLAP: entailment and neutral confidence ranges overlap — "
                "Day 5 threshold tuning is warranted."
            )
        elif (ent_med is not None and ent_med >= 0.85) and (
            neu_med is None or neu_med <= 0.5
        ):
            hyp_lines.append(
                "CLEAN SEPARATION: entailment median ≥ 0.85 and neutral ≤ 0.5 — "
                "current 0.7 threshold is probably fine; Day 5 may not need to touch it."
            )
        else:
            hyp_lines.append(
                "INTERMEDIATE: not clearly clean nor overlapping — "
                "Day 5 should plot full histograms before deciding."
            )

    out = {
        "schema_version": 1,
        "captured_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
        "captured_sessions": captured_sessions,
        "summary_by_ticker": per_ticker,
        "summary_aggregate": aggregate,
        "confidence_histograms_by_label": {
            label: {
                "buckets_0_to_1_step_0.1": [
                    {"range": f"[{i / 10:.1f},{(i + 1) / 10:.1f})", "count": h[i]}
                    for i in range(10)
                ],
                "total": sum(h),
            }
            for label, h in histograms.items()
        },
        "tuning_hypothesis": hyp_lines,
        "notes": [
            "Pre-fix sessions (AAPL/MSFT before 02:50 UTC) had 100% nli_label='unknown' "
            "because nli_worker SIGKILLed on 17–22 pair batches.",
            "Post-fix (sub-batches of 5 dispatched sequentially): 100% real labels. "
            "Direct evidence in nli_worker docker logs — sub-batches succeed in 0.3–4.2s.",
            "TSLA never produced claim_support_rows in either Day 1 attempt — failed at "
            "the writer/analyst stage with Anthropic 400 Bad Request, unrelated to "
            "DeBERTa or the OOM fix. Surfaced separately for Day 2 triage.",
        ],
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_PATH}")
    print(json.dumps(out["summary_aggregate"], indent=2))
    print("\n".join(out["tuning_hypothesis"]))


if __name__ == "__main__":
    asyncio.run(main())
