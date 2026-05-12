"""W10/D3: 1-pager context builder + classification helpers.

Pure functions over the payload + branding + citations. No DB or IO —
the exporter calls these to assemble the Jinja context dict, then
renders ``base.html.j2`` once.

Public surface:
- :func:`build_one_pager_context` — main entry, returns a dict that
  the Jinja base template renders against.
- :func:`get_recommendation_text` / :func:`classify_recommendation` —
  helpers exposed for tests + the future PDF renderer (D4).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from ._base import ClaimCitation, payload_get


def _coerce_to_list(v: Any) -> list[Any]:
    """Robust list coercion. Some upstream writers double-encode a list
    column as a JSON string (e.g. the W7 M&A demo session's
    ``reports.key_reasons`` is a JSONB string holding a JSON array).
    Try to recover transparently here so the renderer doesn't iterate
    characters."""
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("[") and s.endswith("]"):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass
        # Fall back: a non-JSON string is a single item.
        return [s]
    return [v]


_REASONS_RISKS_MAX = 3
_FORCE_NAMES: list[str] = [
    "rivalry",
    "supplier_power",
    "buyer_power",
    "substitute_threat",
    "new_entrant_threat",
]
_INTENSITY_RANK: dict[str, int] = {"high": 3, "moderate": 2, "medium": 2, "low": 1}


# ---------------------------------------------------------------------------
# Recommendation text + color classification
# ---------------------------------------------------------------------------


def get_recommendation_text(payload: Any) -> str:
    """Surface the recommendation prose across mode-specific shapes.

    Order of preference:
      1. ``executive_summary.recommendation`` (future executive_summary
         block, per spec).
      2. ``recommendation`` (WriterReportBase flat field — every mode).
      3. ``recommendation_text`` (legacy alias seen in some payloads).
    """
    es = payload_get(payload, "executive_summary", default=None)
    if isinstance(es, dict):
        rec = es.get("recommendation")
        if isinstance(rec, str) and rec.strip():
            return rec.strip()
    rec = payload_get(payload, "recommendation", "recommendation_text", default="")
    return str(rec).strip()


def classify_recommendation(text: str) -> str:
    """Map recommendation prose to a CSS color class.

    Returns one of: ``green`` | ``amber`` | ``red`` | ``neutral``.
    Falls back to ``neutral`` for non-M&A modes whose recommendations
    are long-form prose without a leading enum verdict.
    """
    if not text:
        return "neutral"
    head = text.strip().split(".")[0].split("—")[0].split(":")[0].upper()
    head = re.sub(r"\s+", " ", head)
    # PROCEED WITH CONDITIONS lands BEFORE plain PROCEED in classification:
    # the more specific match wins, so we check it first.
    if "PROCEED WITH CONDITIONS" in head:
        return "amber"
    if head.startswith("PROCEED"):
        return "green"
    if "WALK AWAY" in head or "WALK-AWAY" in head or "REJECT" in head:
        return "red"
    if "RENEGOTIATE" in head:
        return "red"
    return "neutral"


# ---------------------------------------------------------------------------
# Citation indexing
# ---------------------------------------------------------------------------


def _index_citations(citations: list[ClaimCitation]) -> list[dict[str, Any]]:
    """Project citations to the template-friendly shape with 1-based
    indices. Deduplicates by ``claim_id`` (preserving the first
    occurrence's metadata)."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    idx = 1
    for c in citations or []:
        cid = (c.claim_id or "").strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        out.append(
            {
                "idx": idx,
                "claim_id": cid,
                "text": (c.text or "")[:240],
                "source_title": c.source_title or "",
                "source_type": c.source_type or "",
            }
        )
        idx += 1
    return out


# ---------------------------------------------------------------------------
# Reasons + risks normalization (and single-page trim)
# ---------------------------------------------------------------------------


def _stringify_item(x: Any) -> str:
    """Best-effort coerce a reason/risk into a single string."""
    if isinstance(x, str):
        return x.strip()
    if isinstance(x, dict):
        for k in ("text", "summary", "description", "title"):
            v = x.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return str(x).strip()


def _extract_reasons(payload: Any, *, max_items: int = _REASONS_RISKS_MAX) -> tuple[list[str], int]:
    """Top-N reasons across schema variants. Returns
    ``(top_n, trimmed_count)``."""
    direct = _coerce_to_list(payload_get(payload, "key_reasons", default=[]))
    items: list[str] = [_stringify_item(x) for x in direct if _stringify_item(x)]
    if not items:
        ei = _coerce_to_list(payload_get(payload, "executive_insights", default=[]))
        items = [_stringify_item(x) for x in ei if _stringify_item(x)]
    return items[:max_items], max(0, len(items) - max_items)


def _extract_risks(payload: Any, *, max_items: int = _REASONS_RISKS_MAX) -> tuple[list[str], int]:
    """Top-N risks across schema variants."""
    direct = _coerce_to_list(payload_get(payload, "risks", default=[]))
    items: list[str] = [_stringify_item(x) for x in direct if _stringify_item(x)]
    if not items:
        krs = _coerce_to_list(payload_get(payload, "key_risks_structured", default=[]))
        items = [_stringify_item(x) for x in krs if _stringify_item(x)]
    if not items:
        rms = _coerce_to_list(payload_get(payload, "risks_and_mitigations", default=[]))
        items = [_stringify_item(x) for x in rms if _stringify_item(x)]
    return items[:max_items], max(0, len(items) - max_items)


# ---------------------------------------------------------------------------
# Source panel
# ---------------------------------------------------------------------------


_SOURCE_LABELS: dict[str, str] = {
    "sec_filing": "SEC filings",
    "edgar": "SEC filings",
    "10-K": "SEC filings",
    "10-Q": "SEC filings",
    "transcript": "earnings transcripts",
    "earnings_call": "earnings transcripts",
    "earnings_transcript": "earnings transcripts",
    "firm_library": "firm-library chunks",
    "firm_content": "firm-library chunks",
    "news": "news sources",
    "tavily": "news sources",
    "companies_house": "Companies House filings",
    "document": "documents",
    "upload": "uploaded documents",
}


def _label_source_type(t: str) -> str:
    t = (t or "").strip()
    if not t:
        return "other sources"
    return _SOURCE_LABELS.get(t, t.replace("_", " "))


def _source_counts(payload: Any) -> list[dict[str, Any]]:
    """Aggregate ``sources[].type`` (or chunk source_type) into counts."""
    srcs = _coerce_to_list(payload_get(payload, "sources", default=[]))
    types = []
    for s in srcs:
        if isinstance(s, dict):
            t = s.get("type") or s.get("source_type") or ""
            types.append(t)
        elif isinstance(s, str):
            types.append(s)
    if not types:
        return []
    c = Counter(types)
    # Group by display label so duplicates collapse (e.g. 10-K + edgar both label "SEC filings").
    grouped: Counter[str] = Counter()
    for t, n in c.items():
        grouped[_label_source_type(t)] += n
    return [
        {"label": label, "count": n}
        for label, n in sorted(grouped.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


# ---------------------------------------------------------------------------
# Mode-specific supplements
# ---------------------------------------------------------------------------


def _m_and_a_supplement(payload: Any) -> dict[str, Any]:
    vr = payload_get(payload, "valuation_range", default={}) or {}
    if not isinstance(vr, dict):
        vr = {}

    def _gbp(k: str) -> float | None:
        node = vr.get(k) or {}
        if isinstance(node, dict):
            v = node.get("gbp_m")
            if isinstance(v, (int, float)):
                return float(v)
        # Some payloads flatten as valuation_range.low_gbp_m etc.
        flat = vr.get(f"{k}_gbp_m")
        if isinstance(flat, (int, float)):
            return float(flat)
        return None

    walk_away = None
    ds = payload_get(payload, "deal_structure_implications", default={}) or {}
    if isinstance(ds, dict):
        wa = ds.get("walk_away_triggers") or []
        if isinstance(wa, list) and wa:
            walk_away = _stringify_item(wa[0])
    if not walk_away:
        # Fall back to top-level kill_criteria.
        kc = payload_get(payload, "kill_criteria", default=[]) or []
        if kc:
            walk_away = _stringify_item(kc[0])

    return {
        "valuation_low_gbp_m": _gbp("low"),
        "valuation_base_gbp_m": _gbp("base"),
        "valuation_high_gbp_m": _gbp("high"),
        "walk_away_trigger": walk_away,
    }


def _growth_strategy_supplement(payload: Any) -> dict[str, Any]:
    frameworks = payload_get(payload, "frameworks", default={}) or {}
    if not isinstance(frameworks, dict):
        return {"top_competitive_force": None, "top_competitive_force_intensity": None}
    p5 = frameworks.get("porters_five_forces") or {}
    if not isinstance(p5, dict):
        return {"top_competitive_force": None, "top_competitive_force_intensity": None}

    best: tuple[int, str, str] | None = None
    for fname in _FORCE_NAMES:
        block = p5.get(fname) or {}
        if not isinstance(block, dict):
            continue
        intensity = str(block.get("intensity") or "").lower().strip()
        rank = _INTENSITY_RANK.get(intensity, 0)
        if rank > 0 and (best is None or rank > best[0]):
            best = (rank, fname, intensity)

    if best is None:
        return {"top_competitive_force": None, "top_competitive_force_intensity": None}
    return {
        "top_competitive_force": best[1].replace("_", " "),
        "top_competitive_force_intensity": best[2],
    }


# ---------------------------------------------------------------------------
# Mode detection
# ---------------------------------------------------------------------------


def _detect_mode(payload: Any, mode_hint: str | None) -> str:
    """Resolve the consulting mode for template dispatch.

    Order:
      1. Explicit ``mode_hint`` passed by the service layer (read
         from ``sessions.report_mode``).
      2. ``payload.mode`` (set by the writer's schema).
      3. Heuristic: presence of ``valuation_range`` /
         ``synergy_estimate`` → m_and_a_diligence.
      4. Default ``general``.
    """
    for candidate in (mode_hint, payload_get(payload, "mode", default=None)):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    if (
        payload_get(payload, "valuation_range", default=None)
        or payload_get(payload, "synergy_estimate", default=None)
    ):
        return "m_and_a_diligence"
    return "general"


# ---------------------------------------------------------------------------
# Public: build_one_pager_context
# ---------------------------------------------------------------------------


def build_one_pager_context(
    payload: Any,
    firm_branding: dict[str, Any],
    citations: list[ClaimCitation],
    *,
    engagement_title: str = "Argus 1-pager",
    target_name: str = "",
    prepared_by: str = "",
    mode_hint: str | None = None,
    firm_name: str = "Argus",
    now: datetime | None = None,
    reasons_max: int = _REASONS_RISKS_MAX,
    risks_max: int = _REASONS_RISKS_MAX,
) -> dict[str, Any]:
    """Build the Jinja render context for the 1-pager.

    Pure: no DB / no IO. Tolerant of payloads arriving as Pydantic
    instances or plain dicts. ``reasons_max`` / ``risks_max`` allow
    the PDF exporter to retry with a tighter cap when content
    overflows a single page (W10/D4).
    """
    branding = firm_branding or {}
    now = now or datetime.now(tz=timezone.utc)

    mode = _detect_mode(payload, mode_hint)
    rec_text = get_recommendation_text(payload)
    rec_color = classify_recommendation(rec_text)
    reasons, reasons_trim = _extract_reasons(payload, max_items=reasons_max)
    risks, risks_trim = _extract_risks(payload, max_items=risks_max)
    ctx_citations = _index_citations(citations or [])

    supplement: dict[str, Any] = {}
    if mode == "m_and_a_diligence":
        supplement = _m_and_a_supplement(payload)
    elif mode == "growth_strategy":
        supplement = _growth_strategy_supplement(payload)

    return {
        # Branding
        "primary_color": branding.get("primary_color") or "#1a1a1a",
        "secondary_color": branding.get("secondary_color") or "#666",
        "font_family": branding.get("font_family") or "Inter, system-ui, sans-serif",
        "logo_url": branding.get("logo_url") or "",
        "footer_text": branding.get("footer_text") or "",
        # Header meta
        "engagement_title": engagement_title or "Argus 1-pager",
        "target_name": target_name,
        "prepared_by": prepared_by,
        "firm_name": firm_name,
        "generated_at_display": now.strftime("%Y-%m-%d"),
        # Body
        "mode": mode,
        "recommendation_text": rec_text or "(no recommendation provided)",
        "recommendation_color": rec_color,
        "confidence_level": payload_get(payload, "confidence_level", default=""),
        "reasons": reasons,
        "reasons_truncated": reasons_trim,
        "risks": risks,
        "risks_truncated": risks_trim,
        # Mode supplement (merged so the template can reference flat names)
        **supplement,
        # Source panel
        "source_counts": _source_counts(payload),
        "citations": ctx_citations,
    }
