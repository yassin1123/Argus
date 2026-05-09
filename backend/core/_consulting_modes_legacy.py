"""Load consulting mode config: required evidence dimensions and minimum counts."""

import os
import re
from pathlib import Path
from typing import Any

import yaml

_BRANCH_TAG = re.compile(r"^\[branch:([a-z0-9_]+)\]", re.IGNORECASE)

_MODES: dict[str, Any] | None = None


def _config_path() -> Path:
    base = Path(__file__).resolve().parent.parent / "config" / "consulting_modes.yaml"
    override = os.getenv("ARGUS_CONSULTING_MODES_PATH")
    if override:
        return Path(override)
    return base


def load_modes() -> dict[str, Any]:
    global _MODES
    if _MODES is not None:
        return _MODES
    path = _config_path()
    if not path.is_file():
        _MODES = {}
        return _MODES
    with path.open(encoding="utf-8") as f:
        _MODES = yaml.safe_load(f) or {}
    return _MODES


def get_mode_config(mode: str) -> dict[str, Any]:
    m = load_modes().get(mode) or load_modes().get("general") or {}
    if not isinstance(m, dict):
        return {}
    return {
        "label": str(m.get("label", mode)),
        "required_branches": list(m.get("required_branches") or []),
        "min_evidence_objects": int(m.get("min_evidence_objects") or 0),
    }


def check_mode_satisfied(
    mode: str,
    *,
    branch_ids_present: set[str],
    evidence_count: int,
) -> tuple[bool, list[str]]:
    cfg = get_mode_config(mode)
    gaps: list[str] = []
    for b in cfg.get("required_branches", []):
        if b not in branch_ids_present:
            gaps.append(f"Missing research branch coverage: {b}")
    min_e = int(cfg.get("min_evidence_objects") or 0)
    if evidence_count < min_e:
        gaps.append(
            f"Mode '{mode}' requires at least {min_e} evidence objects; found {evidence_count}."
        )
    return len(gaps) == 0, gaps


def branch_ids_from_evidence_claims(evidence_objects: list[Any]) -> set[str]:
    """Parse `[branch:market]` prefixes on evidence.claim from branch research."""
    found: set[str] = set()
    for o in evidence_objects:
        claim = getattr(o, "claim", None) or (o.get("claim") if isinstance(o, dict) else None)
        if not claim or not isinstance(claim, str):
            continue
        m = _BRANCH_TAG.match(claim.strip())
        if m:
            found.add(m.group(1).lower())
    return found
