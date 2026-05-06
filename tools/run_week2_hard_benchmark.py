"""Hard benchmark runner — verification-only on the planted-overstatement
fixture, three configs (llm_only / llm_plus_deberta / full_ensemble).

Phase 1 / Week 2 / Day 4. Loads
backend/tests/fixtures/germany_vs_france_hard/analyst_output.json plus
the same fixture's evidence catalogue (from
backend/tests/fixtures/germany_vs_france/evidence.json), runs ONLY the
verification stage (LLM verifier + build_claim_support + ensemble
enrichment), and scores recall / precision / false-flag-rate against
planted_overstatements.json under each of the three configs.

Configs
-------
- ``llm_only``         — aggregator returns the LLM verdict directly
                          (mapped to ensemble vocabulary). Lexical and
                          DeBERTa results are computed for diagnostics
                          but ignored.
- ``llm_plus_deberta`` — aggregator runs as Day 3 ships, but the lexical
                          signal is forced to ``score=1.0, missing=[]``
                          on every row so numeric/entity drift never
                          contributes.
- ``full_ensemble``    — aggregator + lexical + DeBERTa, exactly as
                          Day 3 ships.

Output
------
- ``docs/eval/week2_hard_benchmark_run.json`` — the full result blob
  (per-claim verdicts under each config, plus aggregate metrics).
- Console summary in the format the spec specifies.

The runner does NOT run the planner / researcher / analyst / writer.
It only exercises the verification stage so failures get attributed
to the verification system, not to upstream noise.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")


# Paths -----------------------------------------------------------------

FIXTURE_DIR = _REPO_ROOT / "backend" / "tests" / "fixtures" / "germany_vs_france_hard"
ANALYST_PATH = FIXTURE_DIR / "analyst_output.json"
PLANTED_PATH = FIXTURE_DIR / "planted_overstatements.json"
EVIDENCE_PATH = (
    _REPO_ROOT / "backend" / "tests" / "fixtures" / "germany_vs_france" / "evidence.json"
)
RESULT_PATH = _REPO_ROOT / "docs" / "eval" / "week2_hard_benchmark_run.json"


# Verdict bucketing -----------------------------------------------------

# A claim is "flagged" by the ensemble when its mapped verdict is one
# of these. supported_high / supported_low map to "supported" via
# core.feature_flags.effective_verdict; anything else here means the
# verifier did not fully ratify the claim.
_FLAGGED_VERDICTS = frozenset({"weak", "unsupported", "contradicted"})


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _load_fixture() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    analyst = json.loads(ANALYST_PATH.read_text(encoding="utf-8"))
    planted = json.loads(PLANTED_PATH.read_text(encoding="utf-8"))
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    return analyst, planted, evidence


def _build_evidence_objects(evidence_dicts: list[dict[str, Any]]):
    """Reconstruct the EvidenceObject Pydantic instances the verifier expects.

    Late import so this script's module load is cheap.
    """
    from models.evidence import EvidenceObject  # noqa: WPS433

    # session_id is required by the Pydantic model but isn't load-bearing
    # for the verification stage (the verifier only reads ID + quote +
    # source metadata). Use the seeded engagement's deterministic UUID
    # so any debug log mentioning session_id resolves cleanly.
    SYNTHETIC_SESSION_ID = "11111111-1111-4111-8111-111111111111"
    out = []
    for e in evidence_dicts:
        out.append(
            EvidenceObject(
                id=e["id"],
                session_id=SYNTHETIC_SESSION_ID,
                task_id=e.get("task_id"),
                claim=e.get("claim", ""),
                quote=e.get("quote", ""),
                source_title=e.get("source_title", ""),
                source_url=e.get("source_url", ""),
                source_date=e.get("source_date"),
                source_type=e.get("source_type", "web"),
                source_score=float(e.get("source_score", 0.0)),
                confidence=e.get("confidence", "medium"),
                is_inference=bool(e.get("is_inference", False)),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Verification stage (LLM judge + build_claim_support + ensemble enrich)
# ---------------------------------------------------------------------------


async def _run_llm_verifier(analysis: dict[str, Any], evidence_objects) -> dict[str, Any]:
    """Run only the existing LLM verifier (gpt-4o per Phase 1 routing)."""
    from agents.verifier import VerifierAgent  # noqa: WPS433

    agent = VerifierAgent()
    return await agent.run(analysis, evidence_objects)


async def _build_rows(analysis: dict[str, Any], evidence_objects, ver_dict) -> list[dict[str, Any]]:
    from core.claim_support import build_claim_support  # noqa: WPS433

    return build_claim_support(analysis, evidence_objects, ver_dict)


# ---------------------------------------------------------------------------
# Per-config enrichment
# ---------------------------------------------------------------------------

# Reuse the Day-3 enrichment helpers verbatim; we just substitute the
# lexical signal / DeBERTa result for the disabled-signal configs.

async def _enrich_full_ensemble(rows, evidence_objects):
    from core.nli.ensemble_enrich import enrich_with_ensemble_signals  # noqa: WPS433

    return await enrich_with_ensemble_signals(rows, evidence_objects)


async def _enrich_llm_plus_deberta(rows, evidence_objects):
    """Day-3 enrichment but with the lexical signal disabled.

    We patch ``score_overlap`` for the duration of this enrichment so it
    returns the no-drift sentinel; the aggregator then sees a
    "no numeric drift" signal regardless of what the claim actually says.
    DeBERTa runs normally.
    """
    from core.nli import ensemble_enrich as ee  # noqa: WPS433
    from core.nli.lexical_overlap import LexicalSignal  # noqa: WPS433

    original = ee.score_overlap

    def _stub(_claim: str, _chunk: str) -> LexicalSignal:
        return LexicalSignal(
            numeric_overlap_score=1.0,
            numeric_missing=[],
            entity_overlap_score=1.0,
            entity_missing=[],
        )

    ee.score_overlap = _stub  # type: ignore[assignment]
    try:
        return await ee.enrich_with_ensemble_signals(rows, evidence_objects)
    finally:
        ee.score_overlap = original  # type: ignore[assignment]


async def _enrich_llm_only(rows, evidence_objects):
    """LLM-only mode. The aggregator is bypassed entirely — we just
    promote the LLM verdict to ensemble_verdict, mapped to the
    ensemble vocabulary so the rest of the pipeline (and the scoring
    harness) sees the same column shape.
    """
    out = []
    for row in rows:
        new_row = {**row}
        llm = (row.get("verifier_verdict") or "").strip().lower()
        # Map LLM verdicts straight through. supported_high vs
        # supported_low cannot be inferred from the LLM alone, so we
        # collapse the LLM "supported" to "supported_high" for parity
        # with full_ensemble's no-flag class.
        mapping = {
            "supported": "supported_high",
            "weak": "weak",
            "unsupported": "unsupported",
            "overstates": "weak",
            "contradicted": "contradicted",
        }
        ensemble_verdict = mapping.get(llm, "weak")
        new_row["ensemble_verdict"] = ensemble_verdict
        new_row["ensemble_reason"] = "llm only mode"
        # Leave the other ensemble columns NULL — this config is
        # deliberately not running them.
        new_row.setdefault("nli_label", None)
        new_row.setdefault("nli_confidence", None)
        new_row.setdefault("numeric_overlap_score", None)
        new_row.setdefault("numeric_overlap_missing", [])
        new_row.setdefault("entity_overlap_score", None)
        new_row.setdefault("entity_overlap_missing", [])
        out.append(new_row)
    return out


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _legacy_class(ensemble_verdict: str | None) -> str:
    """Map ensemble verdict -> {supported, weak, unsupported, contradicted}.

    Mirrors core.feature_flags.effective_verdict's mapping so the score
    harness uses the same flag-on semantics the writer would.
    """
    v = (ensemble_verdict or "").strip().lower()
    if v in ("supported_high", "supported_low"):
        return "supported"
    if v in _FLAGGED_VERDICTS:
        return v
    return v or "supported"  # benign fallback so missing data isn't a flag


def _score_config(rows: list[dict[str, Any]], planted_ids: set[str]) -> dict[str, Any]:
    flagged_planted: list[str] = []
    flagged_unplanted: list[str] = []
    by_claim: dict[str, dict[str, Any]] = {}

    # Score only the analyst's KEY_CLAIM rows. build_claim_support also
    # emits one row per assumption (support_type="assumption") with no
    # cited evidence; those naturally flag under any verifier and would
    # contaminate the precision/false-flag metrics if treated as
    # "unplanted" rows. The benchmark question is "did the verifier
    # flag the planted overstatements?" — the answer should be measured
    # against the same population the analyst's overstatements live in.
    for row in rows:
        if (row.get("support_type") or "").lower() == "assumption":
            continue
        cid = str(row.get("claim_id"))
        ensemble = row.get("ensemble_verdict")
        legacy = _legacy_class(ensemble)
        is_flagged = legacy in _FLAGGED_VERDICTS
        is_planted = cid in planted_ids
        by_claim[cid] = {
            "ensemble_verdict": ensemble,
            "legacy_class": legacy,
            "is_flagged": is_flagged,
            "is_planted": is_planted,
            "verifier_verdict": row.get("verifier_verdict"),
            "nli_label": row.get("nli_label"),
            "nli_confidence": row.get("nli_confidence"),
            "numeric_overlap_score": row.get("numeric_overlap_score"),
            "numeric_overlap_missing": row.get("numeric_overlap_missing"),
            "entity_overlap_score": row.get("entity_overlap_score"),
            "entity_overlap_missing": row.get("entity_overlap_missing"),
            "ensemble_reason": row.get("ensemble_reason"),
        }
        if is_flagged and is_planted:
            flagged_planted.append(cid)
        elif is_flagged and not is_planted:
            flagged_unplanted.append(cid)

    n_planted = len(planted_ids)
    n_unplanted = max(0, len(by_claim) - n_planted)
    n_flagged = len(flagged_planted) + len(flagged_unplanted)

    recall = (len(flagged_planted) / n_planted) if n_planted else 0.0
    precision = (len(flagged_planted) / n_flagged) if n_flagged else 0.0
    false_flag_rate = (
        len(flagged_unplanted) / n_unplanted
    ) if n_unplanted else 0.0

    return {
        "rows": by_claim,
        "metrics": {
            "n_total_claims": len(by_claim),
            "n_planted": n_planted,
            "n_unplanted": n_unplanted,
            "flagged_planted": flagged_planted,
            "flagged_unplanted": flagged_unplanted,
            "recall_on_planted": round(recall, 4),
            "precision_on_planted": round(precision, 4),
            "false_flag_rate": round(false_flag_rate, 4),
        },
    }


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


async def main_async() -> int:
    if not ANALYST_PATH.is_file():
        print(f"missing fixture {ANALYST_PATH}", file=sys.stderr)
        return 1

    analyst, planted, evidence_dicts = _load_fixture()
    planted_ids = {p["claim_id"] for p in planted}
    evidence_objects = _build_evidence_objects(evidence_dicts)

    if not (os.getenv("OPENAI_API_KEY") or "").strip():
        print("OPENAI_API_KEY not set; LLM verifier cannot run", file=sys.stderr)
        return 1

    print(
        f"hard benchmark: {len(analyst.get('key_claims', []))} claims, "
        f"{len(evidence_objects)} evidence rows, {len(planted_ids)} planted"
    )

    # The LLM verifier output is shared across all three configs (it's
    # deterministic-ish — temperature=0.05 — and only depends on the
    # analyst+evidence). build_claim_support is also shared.
    print("step 1/4: running LLM verifier (one call, shared by all configs) …")
    t0 = time.perf_counter()
    ver_dict = await _run_llm_verifier(analyst, evidence_objects)
    llm_verifier_seconds = round(time.perf_counter() - t0, 2)
    print(f"  done in {llm_verifier_seconds}s")

    base_rows = await _build_rows(analyst, evidence_objects, ver_dict)
    print(f"  build_claim_support produced {len(base_rows)} rows")

    configs: list[tuple[str, Any]] = [
        ("llm_only", _enrich_llm_only),
        ("llm_plus_deberta", _enrich_llm_plus_deberta),
        ("full_ensemble", _enrich_full_ensemble),
    ]

    results: dict[str, Any] = {
        "fixture": {
            "analyst_path": ANALYST_PATH.relative_to(_REPO_ROOT).as_posix(),
            "evidence_path": EVIDENCE_PATH.relative_to(_REPO_ROOT).as_posix(),
            "planted_path": PLANTED_PATH.relative_to(_REPO_ROOT).as_posix(),
            "n_total_rows_from_build_claim_support": len(base_rows),
            "n_planted": len(planted_ids),
            "planted_ids": sorted(planted_ids),
            "scoring_filter": "assumption rows excluded — only key_claim rows are scored",
        },
        "configs": {},
        "wall_seconds": 0.0,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    overall_t0 = time.perf_counter()
    for name, fn in configs:
        print(f"step: enriching for {name} …")
        t1 = time.perf_counter()
        rows = await fn([dict(r) for r in base_rows], evidence_objects)
        scored = _score_config(rows, planted_ids)
        scored["wall_seconds"] = round(time.perf_counter() - t1, 2)
        results["configs"][name] = scored
        m = scored["metrics"]
        print(
            f"  {name:18s} "
            f"recall={len(m['flagged_planted'])}/{m['n_planted']}  "
            f"precision={len(m['flagged_planted'])}/"
            f"{len(m['flagged_planted']) + len(m['flagged_unplanted'])}  "
            f"false_flags={len(m['flagged_unplanted'])}"
        )

    results["llm_verifier_seconds"] = llm_verifier_seconds
    results["enrichment_seconds_per_config"] = {
        name: results["configs"][name]["wall_seconds"] for name, _ in configs
    }
    results["wall_seconds"] = round(
        llm_verifier_seconds + sum(c["wall_seconds"] for c in results["configs"].values()),
        2,
    )

    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {RESULT_PATH}")

    # Decision-check (informational; doesn't affect exit code).
    full = results["configs"]["full_ensemble"]["metrics"]
    llm = results["configs"]["llm_only"]["metrics"]
    full_caught = len(full["flagged_planted"])
    llm_caught = len(llm["flagged_planted"])

    print()
    print(f"DECISION CHECK (informational):")
    print(f"  full_ensemble caught {full_caught}/5 planted")
    print(f"  llm_only      caught {llm_caught}/5 planted")
    if full_caught >= 4 and llm_caught <= 1:
        print("  -> wedge confirmed: proceed to Day 5 with confidence.")
    elif full_caught < 3:
        print("  -> SURFACE: full_ensemble caught < 3/5. Truth table likely needs revision.")
    elif llm_caught >= 3:
        print("  -> SURFACE: llm_only caught >= 3/5. Benchmark may be too easy.")
    else:
        print("  -> partial signal; review per-config breakdown before Day 5.")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
