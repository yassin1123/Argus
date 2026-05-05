"""Config-driven reasoning skeleton: required slots must appear in analyst output."""

import os
from pathlib import Path
from typing import Any

import yaml

_SKEL: dict[str, Any] | None = None


def _config_path() -> Path:
    base = Path(__file__).resolve().parent.parent / "config" / "reasoning_skeletons.yaml"
    override = os.getenv("ARGUS_REASONING_SKELETONS_PATH")
    if override:
        return Path(override)
    return base


def load_skeleton_config() -> dict[str, Any]:
    global _SKEL
    if _SKEL is not None:
        return _SKEL
    path = _config_path()
    if not path.is_file():
        _SKEL = {}
        return _SKEL
    with path.open(encoding="utf-8") as f:
        _SKEL = yaml.safe_load(f) or {}
    return _SKEL


def get_required_slots(report_mode: str) -> list[str]:
    cfg = load_skeleton_config().get(report_mode) or load_skeleton_config().get("general") or {}
    if not isinstance(cfg, dict):
        return []
    raw = cfg.get("required_slots") or []
    if not isinstance(raw, list):
        return []
    return [str(x).strip().lower().replace(" ", "_") for x in raw if str(x).strip()]


def skeleton_hint_for_prompt(report_mode: str) -> str:
    slots = get_required_slots(report_mode)
    if not slots:
        return ""
    return (
        f"\nYou MUST include reasoning_slots: a list with one object per required dimension: "
        f"{', '.join(slots)}. Each object: "
        '{"slot_id": "<id>", "summary": "<non-empty insight>", "claim_ids": ["<key_claim claim_id>", ...]}. '
        "claim_ids must only reference claim_id values from your key_claims entries.\n"
    )


def _key_claim_ids(analysis: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    kc = analysis.get("key_claims")
    if not isinstance(kc, list):
        return out
    for item in kc:
        if isinstance(item, dict):
            cid = str(item.get("claim_id") or "").strip()
            if cid:
                out.add(cid)
    return out


def validate_reasoning_skeleton(
    analysis: dict[str, Any],
    report_mode: str,
    *,
    require_claim_link: bool = True,
) -> tuple[bool, list[str]]:
    """
    Returns (ok, errors).
    When required_slots is empty, passes.
    Otherwise each slot_id must have non-empty summary; if require_claim_link, each slot needs >=1 valid claim_id.
    """
    required = get_required_slots(report_mode)
    if not required:
        return True, []

    rs = analysis.get("reasoning_slots")
    errors: list[str] = []
    if not isinstance(rs, list):
        errors.append(
            "reasoning_slots must be a non-empty list when this report mode defines required reasoning slots."
        )
        return False, errors

    by_slot: dict[str, dict[str, Any]] = {}
    for i, row in enumerate(rs):
        if not isinstance(row, dict):
            errors.append(f"reasoning_slots[{i}] is not an object.")
            continue
        sid = str(row.get("slot_id", "")).strip().lower().replace(" ", "_")
        if not sid:
            errors.append(f"reasoning_slots[{i}] missing slot_id.")
            continue
        by_slot[sid] = row

    allowed_claims = _key_claim_ids(analysis)

    for rid in required:
        if rid not in by_slot:
            errors.append(f'Missing reasoning slot "{rid}" (required for report_mode={report_mode}).')
            continue
        row = by_slot[rid]
        summary = str(row.get("summary", "")).strip()
        if len(summary) < 12:
            errors.append(f'Reasoning slot "{rid}" needs a substantive summary (at least 12 characters).')
        raw_cids = row.get("claim_ids")
        cids = [str(x).strip() for x in raw_cids] if isinstance(raw_cids, list) else []
        if require_claim_link and allowed_claims:
            if not cids:
                errors.append(
                    f'Reasoning slot "{rid}" must include at least one claim_ids entry '
                    "matching a key_claims.claim_id."
                )
            else:
                bad = [c for c in cids if c not in allowed_claims]
                if bad:
                    errors.append(
                        f'Reasoning slot "{rid}" references unknown claim_ids (not in key_claims): {bad[:5]}'
                    )

    return len(errors) == 0, errors


def normalize_reasoning_slots_for_graph(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a clean list for persistence on reasoning_graph."""
    rs = analysis.get("reasoning_slots")
    if not isinstance(rs, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rs:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("slot_id", "")).strip().lower().replace(" ", "_")
        if not sid:
            continue
        raw_cids = row.get("claim_ids")
        cids = [str(x).strip() for x in raw_cids] if isinstance(raw_cids, list) else []
        out.append(
            {
                "slot_id": sid,
                "summary": str(row.get("summary", ""))[:4000],
                "claim_ids": cids[:24],
            }
        )
    return out
