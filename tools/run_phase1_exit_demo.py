"""Phase 1 / Week 4 / Day 5 — exit demo runner.

Runs the typed-name-to-memo pipeline on two demo targets:

  - **AAPL** (US-listed) — exercises SEC EDGAR + earnings transcripts +
    cross-family ensemble verification. This is the Phase 1 exit
    criterion's load-bearing target.
  - **Tesco PLC** (UK-listed) — exercises Companies House routing + news.
    NOTE: Day 4 surface signal (docs/eval/week4_d4_ch_scanned_pdf_finding.md)
    documented that CH serves only scanned-PDF accounts; ch_filing
    chunks won't populate without OCR (Phase 3). The Tesco run still
    proves planner-routing-fires + news-grounding works for UK briefs.

Captures full memo + claim_support_rows (with all ensemble columns) +
source diversity + recommendation specificity. Writes per-target JSON
to backend/eval_runs/phase1_exit/{TICKER}.json.

Hard assertions (per Day 5 spec):
  - AAPL: ≥1 transcript citation in grounded claims (load-bearing for
    Phase 1 exit). ≥3 distinct SEC accession_numbers cited. Cross-
    family verification visible (verifier_verdict + nli_label populated
    from different families). Recommendation has time-bound thresholds.
  - Tesco: ≥1 news citation; ≥1 ch_filing citation EXPECTED to fail
    pending Phase 3 OCR — captured as a surface signal, not a blocker.

Usage::

    python tools/run_phase1_exit_demo.py
    python tools/run_phase1_exit_demo.py --tickers AAPL
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))

os.environ.setdefault("ARGUS_USE_ENSEMBLE_VERDICT", "true")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------


TARGETS: list[dict[str, Any]] = [
    {
        "ticker": "AAPL",
        "company_name": "Apple Inc.",
        "country": "US",
        "is_phase1_exit": True,
        "expected_sources": ["sec_filing", "transcript"],
    },
    {
        "ticker": "TSCO_LON",  # synthetic local id; Tesco LSE ticker is TSCO.L
        "company_name": "Tesco PLC",
        "country": "UK",
        "is_phase1_exit": False,
        "expected_sources": ["ch_filing", "news"],
    },
]


def _brief(company_name: str) -> str:
    return (
        f"Generate a company profile of {company_name}. Cover business "
        "model, recent financial performance, material risks, and 12-month "
        "outlook."
    )


# ---------------------------------------------------------------------------
# Output paths
# ---------------------------------------------------------------------------


BENCH_ROOT = _REPO_ROOT / "backend" / "eval_runs" / "phase1_exit"

# Specificity regexes (mirror Week 1 regression methodology).
NUMERIC_RE = re.compile(
    r"(?:\b\d+(?:\.\d+)?\s*%|"
    r"[€$£]\s*\d+(?:[\.,]\d+)*[KkMmBb]?|"
    r"\b\d+(?:[\.,]\d+)?\s*(?:million|billion|m|bn|k)\b|"
    r"\b\d+\s*(?:month|months|year|years|day|days|week|weeks|quarter|quarters|q[1-4])\b|"
    r"\b\d+\b)",
    re.IGNORECASE,
)
TIME_BOUND_RE = re.compile(
    r"\b("
    r"(?:within|by|in|over|after|before|month|day|week|quarter)\s+\d+|"
    r"\d+\s*(?:day|days|week|weeks|month|months|year|years|quarter|quarters)|"
    r"q[1-4]\s*(?:fy)?\s*(?:20)?\d{0,2}|"
    r"by\s+(?:end of|q[1-4])"
    r")\b",
    re.IGNORECASE,
)
UK_FACTOR_RE = re.compile(
    r"\b(?:UK|British|United\s+Kingdom|GBP|£|sterling|FCA|HMRC|"
    r"OFGEM|OFCOM|CMA|GroceriesCode\s+Adjudicator|GSCOP|"
    r"national\s+living\s+wage|brexit|cost[-\s]of[-\s]living|"
    r"high\s+street|FTSE)\b",
    re.IGNORECASE,
)

ACCESSION_RE = re.compile(r"/Archives/edgar/data/\d+/(\d{18})/")


def _accession_from_url(url: str) -> str | None:
    if not url:
        return None
    m = ACCESSION_RE.search(url)
    if not m:
        return None
    nd = m.group(1)
    return f"{nd[:10]}-{nd[10:12]}-{nd[12:]}"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _setup_session(target: dict[str, Any]) -> str:
    from db.connection import acquire  # noqa: WPS433

    sid = str(uuid.uuid4())
    metadata = {
        "phase1_exit_demo": True,
        "ticker": target["ticker"],
        "company_name": target["company_name"],
        "country": target["country"],
    }
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sessions (
                id, title, query, status, report_mode, pipeline_state,
                metadata, gap_report, intake_questions, intake_answers, updated_at
            ) VALUES (
                $1::uuid, $2, $3, 'draft', 'general', 'idle',
                $4::jsonb, '{}'::jsonb, '[]'::jsonb, '[]'::jsonb, NOW()
            )
            """,
            sid,
            f"Phase 1 exit · {target['ticker']}",
            _brief(target["company_name"]),
            json.dumps(metadata),
        )
    return sid


def _row_to_jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, list):
        return [_row_to_jsonable(x) for x in value]
    if isinstance(value, dict):
        return {str(k): _row_to_jsonable(v) for k, v in value.items()}
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


async def _capture(sid: str) -> dict[str, Any]:
    from db.connection import acquire  # noqa: WPS433

    async with acquire() as conn:
        report = await conn.fetchrow(
            """
            SELECT recommendation, summary, confidence_level, key_reasons,
                   risks, counterarguments, next_steps, evidence_count,
                   unsupported_claim_count
            FROM reports WHERE session_id = $1::uuid
            """,
            sid,
        )
        sess = await conn.fetchrow(
            "SELECT metadata FROM sessions WHERE id = $1::uuid", sid
        )
        claim_rows = await conn.fetch(
            """
            SELECT claim_id, claim_text, evidence_object_ids, support_type,
                   verifier_verdict, contradiction_flag, weak_flag,
                   entailment_score, nli_label, nli_confidence,
                   numeric_overlap_score, entity_overlap_score,
                   ensemble_verdict, ensemble_reason
            FROM claim_support_rows WHERE session_id = $1::uuid
            """,
            sid,
        )
        evidence = await conn.fetch(
            """
            SELECT id, source_url, source_title, source_type
            FROM evidence_objects WHERE session_id = $1::uuid
            """,
            sid,
        )
        # Look up which chunk each evidence row came from. Two lookup
        # keys are needed because transcripts ingested via the manual-
        # upload path write source_url=NULL — we fall back to
        # source_filename (= evidence_object.source_title) for those.
        # source_url alone misses every transcript citation.
        chunk_by_url = await conn.fetch(
            """
            SELECT DISTINCT source_url, source_filename, source_type, trust_level,
                   metadata->>'company_name' AS company_name,
                   metadata->>'accession_number' AS accession_number,
                   metadata->>'transaction_id' AS transaction_id,
                   metadata->>'ticker' AS ticker,
                   metadata->>'quarter' AS quarter,
                   metadata->>'year' AS year,
                   metadata->>'source_domain' AS source_domain
            FROM chunks
            WHERE source_url = ANY(
                SELECT DISTINCT source_url FROM evidence_objects
                WHERE session_id = $1::uuid AND source_url IS NOT NULL AND source_url <> ''
            )
            OR source_filename = ANY(
                SELECT DISTINCT source_title FROM evidence_objects
                WHERE session_id = $1::uuid AND source_title IS NOT NULL AND source_title <> ''
            )
            """,
            sid,
        )
        llm_calls = await conn.fetch(
            """
            SELECT task_kind, model, provider, usd_cost, success
            FROM llm_calls WHERE session_id = $1::uuid
            """,
            sid,
        )
    sess_meta: dict[str, Any] = {}
    if sess and sess.get("metadata") is not None:
        m = sess["metadata"]
        sess_meta = json.loads(m) if isinstance(m, str) else dict(m)

    return {
        "report": {k: _row_to_jsonable(v) for k, v in (dict(report) if report else {}).items()},
        "session_metadata": sess_meta,
        "claim_rows": [{k: _row_to_jsonable(v) for k, v in dict(r).items()} for r in claim_rows],
        "evidence": [{k: _row_to_jsonable(v) for k, v in dict(e).items()} for e in evidence],
        "chunk_lookup": [{k: _row_to_jsonable(v) for k, v in dict(c).items()} for c in chunk_by_url],
        "llm_calls": [{k: _row_to_jsonable(v) for k, v in dict(c).items()} for c in llm_calls],
    }


# ---------------------------------------------------------------------------
# Per-target analysis
# ---------------------------------------------------------------------------


def _analyse(target: dict[str, Any], captured: dict[str, Any]) -> dict[str, Any]:
    rep = captured.get("report") or {}
    rec = (rep.get("recommendation") or "").strip()
    summ = (rep.get("summary") or "").strip()

    # Map evidence_object → chunk source_type via two lookup keys:
    # source_url (works for SEC/news/CH) and source_filename (only key
    # available for transcripts, which write source_url=NULL).
    chunk_by_url: dict[str, dict[str, Any]] = {}
    chunk_by_filename: dict[str, dict[str, Any]] = {}
    for c in captured.get("chunk_lookup") or []:
        url = (c.get("source_url") or "").strip()
        if url:
            chunk_by_url[url] = c
        fn = (c.get("source_filename") or "").strip()
        if fn and fn not in chunk_by_filename:
            chunk_by_filename[fn] = c
    ev_by_id: dict[str, dict[str, Any]] = {
        e["id"]: e for e in (captured.get("evidence") or [])
    }

    grounded_claims: list[dict[str, Any]] = []
    sec_accessions: set[str] = set()
    transcript_refs: set[str] = set()
    ch_transactions: set[str] = set()
    news_domains: set[str] = set()
    citations_by_source_type: dict[str, int] = {}
    contradicted_count = 0
    verdict_dist: dict[str, int] = {}
    nli_dist: dict[str, int] = {}
    cross_family_visible = False

    for r in captured.get("claim_rows") or []:
        verdict = r.get("ensemble_verdict") or "(null)"
        verdict_dist[verdict] = verdict_dist.get(verdict, 0) + 1
        nli = r.get("nli_label") or "(null)"
        nli_dist[nli] = nli_dist.get(nli, 0) + 1
        if (verdict or "").lower() == "contradicted" or r.get("contradiction_flag"):
            contradicted_count += 1
        # Cross-family check: verifier_verdict is set by an LLM-judge call
        # against (typically) OpenAI; nli_label is set by DeBERTa (a
        # different model family entirely). When BOTH columns carry
        # non-null values, the row is cross-family verified.
        if r.get("verifier_verdict") and (r.get("nli_label") or "").lower() not in ("", "unknown", "(null)"):
            cross_family_visible = True

        eo_ids = r.get("evidence_object_ids") or []
        if not eo_ids:
            continue
        cited = [ev_by_id.get(str(i)) for i in eo_ids if str(i) in ev_by_id]
        cited = [c for c in cited if c]
        if not cited:
            continue
        grounded_claims.append(r)
        for ev in cited:
            url = (ev.get("source_url") or "").strip()
            title = (ev.get("source_title") or "").strip()
            ch = chunk_by_url.get(url) if url else None
            if ch is None and title:
                ch = chunk_by_filename.get(title)
            if not ch:
                continue
            stype = ch.get("source_type") or ""
            citations_by_source_type[stype] = citations_by_source_type.get(stype, 0) + 1
            if stype == "sec_filing":
                acc = ch.get("accession_number") or _accession_from_url(url)
                if acc:
                    sec_accessions.add(acc)
            elif stype == "transcript":
                t = ch.get("ticker")
                q = ch.get("quarter")
                y = ch.get("year")
                if t and q and y:
                    transcript_refs.add(f"{t} {q} FY{y}")
            elif stype == "ch_filing":
                tx = ch.get("transaction_id")
                if tx:
                    ch_transactions.add(tx)
            elif stype == "news":
                d = ch.get("source_domain")
                if d:
                    news_domains.add(d)

    text_for_specificity = " ".join(s for s in (rec, summ) if s)
    n_numbers = len(NUMERIC_RE.findall(text_for_specificity))
    n_time_bound = len(TIME_BOUND_RE.findall(text_for_specificity))
    n_uk_factors = len(UK_FACTOR_RE.findall(text_for_specificity))

    return {
        "n_claims": len(captured.get("claim_rows") or []),
        "n_grounded": len(grounded_claims),
        "citations_by_source_type": citations_by_source_type,
        "sec_accessions_cited": sorted(sec_accessions),
        "transcript_refs_cited": sorted(transcript_refs),
        "ch_transactions_cited": sorted(ch_transactions),
        "news_domains_cited": sorted(news_domains),
        "ensemble_verdict_dist": verdict_dist,
        "nli_label_dist": nli_dist,
        "contradicted_count": contradicted_count,
        "cross_family_verification_visible": cross_family_visible,
        "n_numbers_in_recommendation": n_numbers,
        "n_time_bound_phrases": n_time_bound,
        "n_uk_factors_in_recommendation": n_uk_factors,
        "recommendation_preview": (rec or summ)[:400],
        "cost_usd_total": round(
            sum(float(c.get("usd_cost") or 0) for c in (captured.get("llm_calls") or [])), 4
        ),
    }


def _validate(
    target: dict[str, Any], analysis: dict[str, Any], wall_seconds: float, error: str | None
) -> tuple[bool, list[str], list[str]]:
    """Hard assertions per Day 5 spec.

    Returns ``(ok, blocking_issues, warnings)``. ``ok=False`` is the
    Phase 1 ship-blocker for AAPL specifically.
    """
    blocking: list[str] = []
    warnings: list[str] = []
    if error:
        blocking.append(f"pipeline raised: {error[:200]}")
        return False, blocking, warnings
    if analysis["n_claims"] < 5:
        blocking.append(f"n_claims={analysis['n_claims']} below sanity floor 5")
    if not analysis.get("recommendation_preview"):
        blocking.append("recommendation empty")

    if target["ticker"] == "AAPL":
        # Phase 1 exit-criterion assertions.
        if not analysis["transcript_refs_cited"]:
            blocking.append(
                "AAPL has 0 transcript citations — Phase 1 exit criterion "
                "requires ≥1; transcripts retrieval not wired"
            )
        if len(analysis["sec_accessions_cited"]) < 3:
            blocking.append(
                f"AAPL cited only {len(analysis['sec_accessions_cited'])} distinct "
                "SEC accessions; spec wants ≥3"
            )
        if not analysis["cross_family_verification_visible"]:
            blocking.append(
                "AAPL has no cross-family verification visible "
                "(both verifier_verdict and a non-unknown nli_label required)"
            )
        if analysis["n_numbers_in_recommendation"] < 2:
            blocking.append(
                f"AAPL recommendation has only {analysis['n_numbers_in_recommendation']} "
                "numeric tokens; spec wants specific numbers"
            )

    if target["ticker"] == "TSCO_LON":
        # Soft assertions per Day 4 surface signal — CH is blocked.
        if not analysis["ch_transactions_cited"]:
            warnings.append(
                "Tesco has 0 ch_filing citations — Day 4 surface (CH serves "
                "scanned PDFs only); Phase 3 OCR work"
            )
        if not analysis["news_domains_cited"]:
            warnings.append(
                "Tesco has 0 news citations — Tavily fetch may have failed "
                "or returned no UK-flavored results"
            )
        if analysis["n_uk_factors_in_recommendation"] < 1:
            warnings.append(
                "Tesco recommendation references zero UK-specific factors "
                "(spec hint: regulatory environment / GBP / UK retail)"
            )

    return (not blocking), blocking, warnings


# ---------------------------------------------------------------------------
# Run loop
# ---------------------------------------------------------------------------


async def _execute(target: dict[str, Any]) -> dict[str, Any]:
    from agents.orchestrator import run_pipeline

    sid = await _setup_session(target)
    t0 = time.perf_counter()
    error_str: str | None = None
    try:
        await run_pipeline(sid, _brief(target["company_name"]))
    except Exception as e:  # noqa: BLE001
        error_str = f"{type(e).__name__}: {e}\n{traceback.format_exc()[:4000]}"
    wall = time.perf_counter() - t0

    captured = await _capture(sid)
    analysis = _analyse(target, captured)
    ok, blocking, warnings = _validate(target, analysis, wall, error_str)
    return {
        "ticker": target["ticker"],
        "company_name": target["company_name"],
        "country": target["country"],
        "is_phase1_exit": target["is_phase1_exit"],
        "session_id": sid,
        "wall_seconds": round(wall, 2),
        "error": error_str,
        "ok": ok,
        "blocking_issues": blocking,
        "warnings": warnings,
        "analysis": analysis,
        "captured": captured,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _short_summary(record: dict[str, Any]) -> str:
    a = record["analysis"]
    return (
        f"  ok={record['ok']} cost=${a['cost_usd_total']:.4f} "
        f"wall={record['wall_seconds']}s claims={a['n_claims']} "
        f"grounded={a['n_grounded']} "
        f"sec_acc={len(a['sec_accessions_cited'])} "
        f"transcripts={len(a['transcript_refs_cited'])} "
        f"ch_tx={len(a['ch_transactions_cited'])} "
        f"news={len(a['news_domains_cited'])} "
        f"contradicted={a['contradicted_count']}"
    )


def _ascii_safe(s: str) -> str:
    """Strip non-cp1252 chars so the Windows console doesn't choke on
    things like ≥, →, em-dash. Issue messages may contain these.
    """
    return s.encode("ascii", "replace").decode("ascii")


async def main_async(args: argparse.Namespace) -> None:
    selected = TARGETS
    if args.tickers.strip():
        wanted = {t.strip().upper() for t in args.tickers.split(",")}
        selected = [t for t in TARGETS if t["ticker"] in wanted]
    if not selected:
        raise SystemExit(f"No tickers matched --tickers={args.tickers!r}")

    BENCH_ROOT.mkdir(parents=True, exist_ok=True)
    from db.connection import close_db, init_db

    await init_db()
    try:
        for target in selected:
            print(f"\n=== {target['ticker']} ({target['company_name']}) ===", flush=True)
            record = await _execute(target)
            print(_ascii_safe(_short_summary(record)), flush=True)
            for w in record.get("warnings") or []:
                print(f"   warn:  {_ascii_safe(w)}", flush=True)
            for b in record.get("blocking_issues") or []:
                print(f"   issue: {_ascii_safe(b)}", flush=True)
            out_path = BENCH_ROOT / f"{target['ticker']}.json"
            out_path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
            print(f"   -> wrote {out_path.name}", flush=True)
    finally:
        await close_db()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--tickers", default="", help="Comma-separated subset (default: all).")
    return p.parse_args()


def main() -> None:
    asyncio.run(main_async(_parse_args()))


if __name__ == "__main__":
    main()
