"""Phase 3 / Week 10 / Day 5 — export-pipeline e2e demo runner.

Generates 4 artifacts (M&A + growth_strategy × HTML + PDF), captures
per-artifact metrics + per-format quality checks, evaluates 7
headline assertions, and lands a ``summary.json`` for the Week 10
wrap-up doc.

Sessions:
  M&A         : 9da8a365-...  (W7 demo: 7/7 fields + 2x2)
  growth      : bcb54507-...  (UK competitive defence brief, growth_strategy)

Headline assertions (mirrored from W10/D5 spec):
  1. All 4 generations succeed (status='ready').
  2. Each PDF is exactly 1 page.
  3. M&A 1-pagers (HTML + PDF) contain valuation_range numbers from
     the source payload.
  4. growth_strategy 1-pagers contain a top-competitive-force
     reference (from Porter's).
  5. Each artifact has claim_citation_count >= 5.
  6. Each PDF file size < 500KB.
  7. Total generation cost < $0.10 (template rendering is zero-LLM).

Usage::

    python tools/run_week10_e2e.py
    python tools/run_week10_e2e.py --summary-only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any
from uuid import UUID

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")


M_AND_A_SESSION_ID = UUID("9da8a365-224e-4c4c-8f65-8ff1d1cef5dc")
GROWTH_SESSION_ID = UUID("bcb54507-31fc-4069-8c0d-585d075b0d07")

RUNS: list[dict[str, Any]] = [
    {"name": "m_and_a_html", "session_id": M_AND_A_SESSION_ID, "format": "html", "engagement_label": "M&A diligence (TargetCo)"},
    {"name": "m_and_a_pdf",  "session_id": M_AND_A_SESSION_ID, "format": "pdf",  "engagement_label": "M&A diligence (TargetCo)"},
    {"name": "growth_html",  "session_id": GROWTH_SESSION_ID,  "format": "html", "engagement_label": "growth_strategy (TargetCo Scotland)"},
    {"name": "growth_pdf",   "session_id": GROWTH_SESSION_ID,  "format": "pdf",  "engagement_label": "growth_strategy (TargetCo Scotland)"},
]

MIN_CITATIONS = 5
MAX_PDF_BYTES = 500_000
MAX_TOTAL_COST_USD = 0.10
# Allow override so the runner can be fired from inside a container
# where the repo root isn't ``__file__.parent.parent`` (e.g. when
# tools/ is bind-mounted at /repo_tools but the bench output should
# land on the host-bound backend/eval_runs/...).
import os as _os  # noqa: E402

_BENCH_ROOT_ENV = _os.environ.get("ARGUS_BENCH_ROOT")
BENCH_ROOT = (
    Path(_BENCH_ROOT_ENV) if _BENCH_ROOT_ENV
    else _REPO_ROOT / "backend" / "eval_runs" / "week10_e2e"
)


# ---------------------------------------------------------------------------
# Quality checks (parse the rendered artifact bytes)
# ---------------------------------------------------------------------------


def _check_m_and_a_valuation_present(file_path: str, format: str) -> dict[str, Any]:
    """The W7 M&A demo payload has valuation_range.low / base / high
    at £205 / £220 / £235m. Verify those numbers survive into the
    rendered artifact in some form."""
    if format == "html":
        text = Path(file_path).read_text(encoding="utf-8")
    elif format == "pdf":
        try:
            import fitz  # PyMuPDF
            with fitz.open(file_path) as doc:
                text = "".join(p.get_text("text") for p in doc)
        except Exception as e:
            return {"ok": False, "error": f"could not parse PDF: {e}"}
    else:
        return {"ok": False, "error": f"unsupported format {format}"}

    needed = ["205", "220", "235"]
    found = {n: (n in text) for n in needed}
    return {"ok": all(found.values()), "found": found}


def _check_growth_porters_present(file_path: str, format: str) -> dict[str, Any]:
    """growth_strategy 1-pager should surface a top-competitive-force
    reference. When the underlying payload has Porter's data, this
    fires with a force name + intensity. When the writer didn't
    produce Porter's (a known W8 Run B writer-truncation carry-forward),
    the renderer falls back to a "Competitive context: Porter's Five
    Forces not produced..." line — which is *correct exporter
    behavior* but *not* a data-level pass. We report both states."""
    if format == "html":
        text = Path(file_path).read_text(encoding="utf-8")
    elif format == "pdf":
        try:
            import fitz
            with fitz.open(file_path) as doc:
                text = "".join(p.get_text("text") for p in doc)
        except Exception as e:
            return {"ok": False, "error": f"could not parse PDF: {e}"}
    else:
        return {"ok": False, "error": f"unsupported format {format}"}

    has_top_force = "Top competitive force" in text
    has_fallback = "Porter's Five Forces not produced" in text
    return {
        "ok": has_top_force,
        "top_competitive_force_marker": has_top_force,
        "fallback_marker": has_fallback,
        "note": (
            "Source payload lacks frameworks.porters_five_forces — "
            "renderer correctly shows fallback. Tracked as Phase 3 "
            "carry-forward (W8 Run B writer-truncation)."
            if has_fallback and not has_top_force
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Run one artifact
# ---------------------------------------------------------------------------


async def _fire_one(run: dict[str, Any]) -> dict[str, Any]:
    from core.exports import GenerateArtifactRequest, generate_artifact

    print(f"\n=== {run['name']} ({run['engagement_label']} → {run['format']}) ===", flush=True)
    t0 = time.perf_counter()
    req = GenerateArtifactRequest(
        session_id=run["session_id"],
        artifact_type="one_pager",
        format=run["format"],
    )
    result = await generate_artifact(req)
    wall = time.perf_counter() - t0

    out: dict[str, Any] = {
        "run_name": run["name"],
        "engagement_label": run["engagement_label"],
        "session_id": str(run["session_id"]),
        "format": run["format"],
        "artifact_id": str(result.artifact_id),
        "status": result.status,
        "file_path": result.file_path,
        "file_size_bytes": result.file_size_bytes,
        "claim_citation_count": result.claim_citation_count,
        "generation_wall_seconds": round(wall, 3),
        "failure_reason": result.failure_reason,
        "metadata": result.metadata,
    }

    # Quality probes per engagement type
    if result.status == "ready" and result.file_path:
        is_m_and_a = run["session_id"] == M_AND_A_SESSION_ID
        is_growth = run["session_id"] == GROWTH_SESSION_ID
        if is_m_and_a:
            out["valuation_check"] = _check_m_and_a_valuation_present(
                result.file_path, run["format"]
            )
        if is_growth:
            out["porters_check"] = _check_growth_porters_present(
                result.file_path, run["format"]
            )

    print(
        f"  status={result.status}  size={result.file_size_bytes}B  "
        f"cites={result.claim_citation_count}  wall={wall:.2f}s  "
        f"pages={result.metadata.get('page_count', 'n/a')}",
        flush=True,
    )
    return out


# ---------------------------------------------------------------------------
# Headline assertions
# ---------------------------------------------------------------------------


def _headline_assertions(records: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}

    # 1: all 4 ready
    statuses = {r["run_name"]: r["status"] for r in records}
    out["all_four_ready"] = all(s == "ready" for s in statuses.values())

    # 2: each PDF exactly 1 page
    pdf_pages = {
        r["run_name"]: r["metadata"].get("page_count")
        for r in records if r["format"] == "pdf"
    }
    out["each_pdf_single_page"] = all(p == 1 for p in pdf_pages.values())
    out["pdf_pages_detail"] = pdf_pages

    # 3: M&A 1-pagers contain valuation numbers
    val_checks = {
        r["run_name"]: r.get("valuation_check", {}).get("ok", False)
        for r in records if "valuation_check" in r
    }
    out["m_and_a_valuation_visible"] = all(val_checks.values()) and len(val_checks) == 2

    # 4: growth_strategy 1-pagers contain top-force
    porters = {
        r["run_name"]: r.get("porters_check", {}).get("ok", False)
        for r in records if "porters_check" in r
    }
    out["growth_porters_visible"] = all(porters.values()) and len(porters) == 2
    out["growth_porters_detail"] = {
        r["run_name"]: r.get("porters_check") for r in records if "porters_check" in r
    }

    # 5: each artifact has >= MIN_CITATIONS
    cite_counts = {r["run_name"]: r["claim_citation_count"] for r in records}
    out[f"each_artifact_cites_ge_{MIN_CITATIONS}"] = all(
        n >= MIN_CITATIONS for n in cite_counts.values()
    )
    out["cite_counts"] = cite_counts

    # 6: each PDF < 500KB
    pdf_sizes = {
        r["run_name"]: r["file_size_bytes"]
        for r in records if r["format"] == "pdf"
    }
    out[f"each_pdf_under_{MAX_PDF_BYTES}_bytes"] = all(
        s is not None and s < MAX_PDF_BYTES for s in pdf_sizes.values()
    )
    out["pdf_sizes"] = pdf_sizes

    # 7: total cost < $0.10 (renderer is zero LLM)
    total_cost = sum(
        (r.get("metadata") or {}).get("generation_cost_usd") or 0.0 for r in records
    )
    out[f"total_cost_under_{MAX_TOTAL_COST_USD}"] = total_cost < MAX_TOTAL_COST_USD
    out["total_cost_usd"] = round(total_cost, 4)

    out["headline_pass"] = all(
        v for k, v in out.items()
        if isinstance(v, bool)
    )
    return out


def _build_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    headline = _headline_assertions(records)
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "headline_assertions": headline,
        "headline_pass": headline["headline_pass"],
        "n_artifacts": len(records),
        "runs": records,
    }


async def main_async(args: argparse.Namespace) -> None:
    BENCH_ROOT.mkdir(parents=True, exist_ok=True)

    if args.summary_only:
        records: list[dict[str, Any]] = []
        for run in RUNS:
            f = BENCH_ROOT / f"{run['name']}.json"
            if f.exists():
                records.append(json.loads(f.read_text(encoding="utf-8")))
        (BENCH_ROOT / "summary.json").write_text(
            json.dumps(_build_summary(records), indent=2, default=str),
            encoding="utf-8",
        )
        print(f"\nsummary: {BENCH_ROOT / 'summary.json'}")
        return

    from db.connection import close_db, init_db

    await init_db()
    records = []
    try:
        for run in RUNS:
            rec = await _fire_one(run)
            (BENCH_ROOT / f"{run['name']}.json").write_text(
                json.dumps(rec, indent=2, default=str), encoding="utf-8"
            )
            records.append(rec)
    finally:
        await close_db()

    summary = _build_summary(records)
    (BENCH_ROOT / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )

    print("\n=== HEADLINE ASSERTIONS ===")
    for k, v in summary["headline_assertions"].items():
        if isinstance(v, bool):
            print(f"  [{'PASS' if v else 'FAIL'}] {k}")
        elif not isinstance(v, dict):
            print(f"  {k}: {v}")
    print(f"\nheadline_pass: {summary['headline_pass']}")
    print(f"summary: {BENCH_ROOT / 'summary.json'}")
    print("\nArtifact paths (open in browser / PDF reader for visual inspection):")
    for r in records:
        print(f"  {r['run_name']}: {r['file_path']}")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--summary-only", action="store_true")
    return p.parse_args()


def main() -> None:
    asyncio.run(main_async(_parse_args()))


if __name__ == "__main__":
    main()
