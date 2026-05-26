"""Interactive claim labeller — Phase 5 / Week 21 / Day 1.

Reads a worksheet produced by :mod:`extract_claims_for_labeling`,
walks the rows one at a time, prompts the human (Yassin) for the
ground-truth verdict + a short rationale + a category, and saves
the labelled output as a golden-set fixture under
``backend/eval/golden_set/real_runs/``.

THIS SCRIPT DOES NOT USE AN LLM. Ground truth comes from the
human reviewer; using an LLM to label whether the LLM verifier
is right is circular. Spec hard rule.

Usage::

    # Interactive: prompt for each row's label
    python tools/label_claims.py \\
        --in backend/eval/golden_set/real_runs/_worksheet_2026-05-26.json \\
        --out backend/eval/golden_set/real_runs/labelled_2026-05-26.yaml

    # Non-interactive (CI / replay): apply a JSON map of id → label
    python tools/label_claims.py \\
        --in worksheet.json --out labelled.yaml \\
        --apply-json labels.json

Time estimate: ~30-60 sec per row for an experienced labeller.
Forty rows is a 30-minute commitment.
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---- enums ---------------------------------------------------------------

VERDICTS = ["supported", "partial", "insufficient", "contradicted"]
CATEGORIES = [
    "numeric_claim", "causal_claim", "comparative",
    "attribution", "forecast",
]

VERDICT_KEYS = {"s": "supported", "p": "partial",
                "i": "insufficient", "c": "contradicted",
                "x": "_skip", "q": "_quit"}
CATEGORY_KEYS = {"n": "numeric_claim", "c": "causal_claim",
                 "p": "comparative", "a": "attribution",
                 "f": "forecast"}


def _wrap(s: str, indent: str = "    ") -> str:
    return textwrap.fill(
        s, width=100, initial_indent=indent, subsequent_indent=indent,
    )


def _prompt_verdict() -> str:
    print()
    print("  Verdict: [s]upported  [p]artial  [i]nsufficient  [c]ontradicted")
    print("           [x] skip this row     [q] quit + save progress")
    while True:
        choice = input("  > ").strip().lower()
        if not choice:
            continue
        # Accept the full word or the first letter.
        if choice in VERDICTS:
            return choice
        if choice in VERDICT_KEYS:
            return VERDICT_KEYS[choice]
        print(
            "  Enter one of [s], [p], [i], [c], [x] skip, [q] quit."
        )


def _prompt_category() -> str:
    print(
        "  Category: [n]umeric_claim  [c]ausal_claim  com[p]arative  "
        "[a]ttribution  [f]orecast"
    )
    while True:
        choice = input("  > ").strip().lower()
        if not choice:
            continue
        if choice in CATEGORIES:
            return choice
        if choice in CATEGORY_KEYS:
            return CATEGORY_KEYS[choice]
        print("  Enter one of [n], [c], [p], [a], [f].")


def _prompt_rationale() -> str:
    print("  Rationale (one line, helps the next reviewer):")
    return input("  > ").strip()


# ---- non-interactive path -----------------------------------------------


def _apply_json(
    rows: list[dict[str, Any]], apply_path: Path,
) -> list[dict[str, Any]]:
    """Apply pre-recorded labels from a JSON map. Each row keyed
    by id → ``{"label": ..., "category": ..., "label_rationale": ...,
    "adversarial": bool}``. Skips rows whose id isn't in the map."""
    raw = json.loads(apply_path.read_text(encoding="utf-8"))
    by_id: dict[str, dict[str, Any]] = (
        raw if isinstance(raw, dict) else {r["id"]: r for r in raw}
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        rid = row["id"]
        label_info = by_id.get(rid)
        if not label_info:
            continue
        label = label_info.get("label")
        category = label_info.get("category")
        if label not in VERDICTS:
            print(f"  skipping {rid}: invalid label {label!r}")
            continue
        if category not in CATEGORIES:
            print(f"  skipping {rid}: invalid category {category!r}")
            continue
        out.append({
            **row,
            "label": label,
            "category": category,
            "label_rationale": label_info.get("label_rationale", ""),
            "adversarial": bool(label_info.get("adversarial", False)),
        })
    return out


def _interactive(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    print()
    print(f"  Labelling {len(rows)} rows. [q] saves progress and exits.")
    print()
    labelled: list[dict[str, Any]] = []
    for i, row in enumerate(rows, start=1):
        if row.get("label"):
            # Already labelled — preserve as-is.
            labelled.append(row)
            continue
        print(f"==== {i}/{len(rows)} — {row['id']} ====")
        print(f"  session: {row.get('session_id', '—')[:8]}...  "
              f"verifier said: {row.get('verifier_verdict') or '—'}")
        print(f"  evidence_source: {row.get('evidence_source_type') or '—'}")
        print()
        print("  CLAIM:")
        print(_wrap(row["claim"]))
        print()
        print("  EVIDENCE:")
        print(_wrap(row["evidence"]))

        verdict = _prompt_verdict()
        if verdict == "_skip":
            print("  (skipped)")
            continue
        if verdict == "_quit":
            print("  (quitting — saving progress so far)")
            break
        category = _prompt_category()
        rationale = _prompt_rationale()
        labelled.append({
            **row,
            "label": verdict,
            "category": category,
            "label_rationale": rationale,
            "adversarial": False,
        })
    return labelled


def _write_golden_set(
    labelled: list[dict[str, Any]], out_path: Path,
) -> None:
    """Convert labelled rows into the golden-set fixture shape and
    write as YAML (or JSON if pyyaml isn't installed)."""
    entries = []
    for row in labelled:
        entries.append({
            "id": row["id"],
            "claim": row["claim"],
            "evidence": row["evidence"],
            "evidence_source": "real_run",
            "ground_truth": row["label"],
            "label_rationale": row.get("label_rationale", ""),
            "category": row["category"],
            "adversarial": bool(row.get("adversarial", False)),
            "real_run_session_id": row.get("session_id"),
            "real_run_claim_id": row.get("claim_id"),
            "extra": {
                "verifier_verdict_at_label_time": row.get("verifier_verdict"),
                "evidence_source_type": row.get("evidence_source_type"),
            },
        })
    payload = {
        "version": 1,
        "labelled_at": datetime.now(tz=timezone.utc).isoformat(),
        "entries": entries,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # The output format follows the caller's chosen extension:
    # .yaml/.yml → YAML (requires pyyaml; falls back to JSON if it
    # isn't installed); anything else → JSON. The loader sniffs the
    # same way so the round-trip is symmetric.
    use_yaml = out_path.suffix.lower() in (".yaml", ".yml")
    if use_yaml:
        try:
            import yaml  # type: ignore
            out_path.write_text(yaml.safe_dump(payload, sort_keys=False))
        except ImportError:
            out_path = out_path.with_suffix(".json")
            out_path.write_text(json.dumps(payload, indent=2))
    else:
        out_path.write_text(json.dumps(payload, indent=2))
    print(f"  wrote {len(entries)} labelled rows → {out_path}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--in", dest="in_path", required=True,
        help="Worksheet JSON from extract_claims_for_labeling.py",
    )
    ap.add_argument(
        "--out", dest="out_path", required=True,
        help="Output fixture YAML/JSON path (under "
             "backend/eval/golden_set/real_runs/).",
    )
    ap.add_argument(
        "--apply-json", default=None,
        help="Non-interactive mode: apply labels from a JSON file "
             "(id → {label, category, label_rationale, adversarial}).",
    )
    args = ap.parse_args(argv)

    worksheet_path = Path(args.in_path)
    out_path = Path(args.out_path)

    data = json.loads(worksheet_path.read_text(encoding="utf-8"))
    rows = data["rows"] if isinstance(data, dict) and "rows" in data else data

    if args.apply_json:
        labelled = _apply_json(rows, Path(args.apply_json))
    else:
        try:
            labelled = _interactive(rows)
        except (KeyboardInterrupt, EOFError):
            print()
            print("  (interrupted — saving progress so far)")
            labelled = []

    if not labelled:
        print("  no rows labelled; nothing written.")
        return 0

    _write_golden_set(labelled, out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
