"""Eyeball check for the lexical-overlap signal (Week 2 / Day 2).

Pulls a real (claim, chunk) pair out of one of the Week 1 NEW-routing
benchmark runs and prints the LexicalSignal it produces. Useful for
operator sanity-checking before Day 3 wires the signal into the
ensemble.

Run inside the nli_worker (or main worker) container so spaCy is
available:

    docker compose exec nli_worker python /repo_tools/check_lexical_overlap.py
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

# Container vs host layout — same trick as tools/check_nli_perf.py.
if Path("/app").is_dir() and (Path("/app") / "core" / "nli").is_dir():
    sys.path.insert(0, "/app")
    _REPO_ROOT = Path("/app").parent  # actually unused inside container
    _RUN_PATH = Path("/app/eval_runs/week1_benchmark/new/run_1.json")
    _FIXTURE_PATH = Path("/app/tests/fixtures/germany_vs_france/evidence.json")
else:
    _REPO_ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(_REPO_ROOT / "backend"))
    _RUN_PATH = _REPO_ROOT / "backend" / "eval_runs" / "week1_benchmark" / "new" / "run_1.json"
    _FIXTURE_PATH = _REPO_ROOT / "backend" / "tests" / "fixtures" / "germany_vs_france" / "evidence.json"

from core.nli.lexical_overlap import score_overlap  # noqa: E402


def _wrap(text: str, indent: str = "   ") -> str:
    return textwrap.fill(text, width=92, initial_indent=indent, subsequent_indent=indent)


def main() -> int:
    if not _RUN_PATH.is_file():
        print(f"missing {_RUN_PATH} — run the Week 1 benchmark first", file=sys.stderr)
        return 1
    if not _FIXTURE_PATH.is_file():
        print(f"missing {_FIXTURE_PATH}", file=sys.stderr)
        return 1

    run = json.loads(_RUN_PATH.read_text(encoding="utf-8"))
    claim_rows = run.get("claim_support_rows") or []
    fixture_evidence = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    if not claim_rows or not fixture_evidence:
        print("no claim_support_rows or evidence to compare", file=sys.stderr)
        return 1

    # Eyeball pairs: a few representative claims paired with the seeded
    # source quote that semantically backs them. We don't try to use the
    # actual evidence_object_ids on the row because those are per-run
    # UUIDs while the fixture stores quotes directly; for an operator
    # eyeball this is enough.
    pairs: list[tuple[str, str, str]] = [
        (
            claim_rows[0]["claim_text"],
            fixture_evidence[0]["quote"],
            "claim 0 -> fixture e0000001 (German B2B SaaS market size)",
        ),
        (
            claim_rows[1]["claim_text"],
            fixture_evidence[1]["quote"],
            "claim 1 -> fixture e0000002 (France growth rate)",
        ),
        (
            claim_rows[2]["claim_text"],
            fixture_evidence[2]["quote"],
            "claim 2 -> fixture e0000003 (procurement cycles)",
        ),
    ]

    for i, (claim, chunk, label) in enumerate(pairs):
        print(f"\n--- pair {i + 1}: {label} ---")
        print("claim:")
        print(_wrap(claim))
        print("chunk:")
        print(_wrap(chunk))
        sig = score_overlap(claim, chunk)
        print(
            f"signal:  numeric={sig.numeric_overlap_score:.2f}  "
            f"entity={sig.entity_overlap_score:.2f}"
        )
        if sig.numeric_missing:
            print(f"  numeric_missing: {sig.numeric_missing}")
        if sig.entity_missing:
            print(f"  entity_missing:  {sig.entity_missing}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
