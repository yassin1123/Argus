"""Use contradictions / tensions as trust signals: severity score, confidence cap, caveats."""

import os
from typing import Any

from models.report import WriterReportPayload

_RANK = {"low": 0, "medium": 1, "medium-high": 2, "high": 3}
_LABELS = ("Low", "Medium", "Medium-High", "High")


def _norm_confidence(level: str) -> str:
    s = str(level or "").strip()
    if not s:
        return "Medium"
    return s[0].upper() + s[1:].lower() if s.lower() in ("low", "high") else s


def confidence_to_rank(level: str) -> int:
    key = str(level or "").strip().lower().replace(" ", "-")
    return _RANK.get(key, 1)


def rank_to_confidence(rank: int) -> str:
    r = max(0, min(3, int(rank)))
    return _LABELS[r]


def compute_contradiction_severity(
    *,
    research_contradictions: list[str],
    verification: dict[str, Any],
    claim_support: list[dict[str, Any]],
) -> int:
    """Higher = more tension / contradiction signal."""
    n = 0
    n += len([x for x in research_contradictions if str(x).strip()])
    ver_contra = verification.get("contradictions") if isinstance(verification, dict) else None
    if isinstance(ver_contra, list):
        n += len([x for x in ver_contra if isinstance(x, str) and x.strip()])
    for row in claim_support:
        if not isinstance(row, dict):
            continue
        nli = str(row.get("nli_label") or "").lower()
        if nli in ("contradicts", "insufficient"):
            n += 2
        if row.get("contradiction_flag"):
            n += 1
        vv = str(row.get("verifier_verdict") or "").lower()
        if vv in ("unsupported", "overstates"):
            n += 1
    return n


def max_allowed_rank_for_severity(severity: int) -> int:
    """Cap model confidence when evidence is contested."""
    cap_high = int(os.getenv("ARGUS_CONTRADICTION_CAP_HIGH_SEVERITY", "2"))
    cap_med = int(os.getenv("ARGUS_CONTRADICTION_CAP_MED_SEVERITY", "4"))
    cap_low = int(os.getenv("ARGUS_CONTRADICTION_CAP_LOW_SEVERITY", "6"))
    if severity >= cap_low:
        return 0
    if severity >= cap_med:
        return 1
    if severity >= cap_high:
        return 2
    return 3


def apply_confidence_cap(payload: WriterReportPayload, severity: int) -> None:
    """Mutates confidence_level downward if severity exceeds thresholds."""
    max_r = max_allowed_rank_for_severity(severity)
    cur_r = confidence_to_rank(payload.confidence_level)
    if cur_r > max_r:
        payload.confidence_level = rank_to_confidence(max_r)


def build_contradiction_caveat(
    severity: int,
    research_contradictions: list[str],
    verification: dict[str, Any],
) -> str:
    if severity <= 0:
        return ""
    parts = [
        f"Contradiction/tension severity score: {severity} (research disagreements, verifier flags, "
        "or claim–evidence mismatch)."
    ]
    rc = [str(x).strip() for x in research_contradictions if str(x).strip()][:3]
    if rc:
        parts.append("Research tensions noted: " + "; ".join(rc) + ".")
    vc = verification.get("contradictions") if isinstance(verification, dict) else None
    if isinstance(vc, list):
        vs = [str(x).strip() for x in vc if isinstance(x, str) and x.strip()][:2]
        if vs:
            parts.append("Verifier tensions: " + "; ".join(vs) + ".")
    return " ".join(parts)


def merge_contradiction_into_caveats(payload: WriterReportPayload, line: str) -> None:
    if not line.strip():
        return
    prev = (payload.caveats or "").strip()
    payload.caveats = (line.strip() + (" " + prev if prev else "")).strip()
