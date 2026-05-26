"""Golden-set loader — Phase 5 / Week 21 / Day 1.

Loads the synthetic backbone + any labelled real-run files into
one :class:`GoldenSet`. Iteration order is **stable**: synthetic
entries first (in their hand-built order), then real-run entries
sorted by ``id`` ascending. Stability matters because the Day 2-3
tuning runs sweep thresholds + score the same set — non-stable
iteration would create spurious accuracy diffs.

Real-run files live in ``backend/eval/golden_set/real_runs/`` as
YAML lists (one file per labelling session, named with the date).
Each entry is the same shape :class:`GoldenEntry` carries, with
``evidence_source: real_run`` and a ``real_run_session_id`` so the
original engagement is traceable.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable

from .build_synthetic import build_synthetic_entries
from .types import GoldenEntry, GoldenSet

logger = logging.getLogger(__name__)


REAL_RUNS_DIR = Path(__file__).resolve().parent / "real_runs"


def _try_yaml_load(path: Path) -> list[dict[str, Any]]:
    """Load a YAML or JSON file of golden entries. We import yaml
    lazily because the rest of the package doesn't need it — and
    we fall back to JSON if pyyaml isn't installed (we don't
    require it as a hard dep for tests)."""
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError:
            logger.warning(
                "pyyaml not installed — skipping %s. Install pyyaml or "
                "rename to .json.",
                path,
            )
            return []
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if data is None:
        return []
    if isinstance(data, dict) and "entries" in data:
        data = data["entries"]
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a list of entries")
    return data


def _coerce_entry(row: dict[str, Any]) -> GoldenEntry:
    return GoldenEntry(
        id=str(row["id"]),
        claim=str(row["claim"]),
        evidence=str(row["evidence"]),
        evidence_source=str(row.get("evidence_source", "real_run")),
        ground_truth=str(row["ground_truth"]),
        label_rationale=str(row.get("label_rationale", "")),
        category=str(row["category"]),
        adversarial=bool(row.get("adversarial", False)),
        real_run_session_id=row.get("real_run_session_id"),
        real_run_claim_id=row.get("real_run_claim_id"),
        extra=dict(row.get("extra") or {}),
    )


def load_real_run_entries(
    real_runs_dir: Path | None = None,
) -> list[GoldenEntry]:
    """Load every labelled real-run file under ``real_runs_dir``.
    Returns ``[]`` when the directory is missing or empty — the
    synthetic backbone alone is a valid bench.
    """
    root = real_runs_dir or REAL_RUNS_DIR
    if not root.exists() or not root.is_dir():
        return []
    out: list[GoldenEntry] = []
    seen_ids: set[str] = set()
    files = sorted(
        list(root.glob("*.yaml")) + list(root.glob("*.yml"))
        + list(root.glob("*.json"))
    )
    for path in files:
        rows = _try_yaml_load(path)
        for row in rows:
            try:
                entry = _coerce_entry(row)
            except Exception as e:  # noqa: BLE001
                logger.warning("%s: dropping row: %s", path, e)
                continue
            if entry.id in seen_ids:
                logger.warning(
                    "%s: duplicate id %s — keeping the earlier one",
                    path, entry.id,
                )
                continue
            seen_ids.add(entry.id)
            out.append(entry)
    out.sort(key=lambda e: e.id)
    return out


def load_golden_set(
    *,
    include_synthetic: bool = True,
    include_real_runs: bool = True,
    real_runs_dir: Path | None = None,
) -> GoldenSet:
    """Compose the golden set. Synthetic entries first (in their
    deterministic order), then real-run entries by id ascending.
    """
    entries: list[GoldenEntry] = []
    if include_synthetic:
        entries.extend(build_synthetic_entries())
    if include_real_runs:
        entries.extend(load_real_run_entries(real_runs_dir=real_runs_dir))
    return GoldenSet(entries=entries)


__all__ = ["load_golden_set", "load_real_run_entries", "REAL_RUNS_DIR"]
