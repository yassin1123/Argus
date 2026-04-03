"""Optional LLM-based entailment labels for claim–quote pairs (independent of analyst model)."""

import json
import os
from typing import Any

from core.json_util import parse_llm_json
from core.llm import llm_call
from core.model_router import resolve

_ENABLED = os.getenv("ARGUS_ENTAILMENT_LLM", "1").lower() in ("1", "true", "yes")


async def enrich_claim_rows_with_entailment(
    rows: list[dict[str, Any]],
    evidence_by_id: dict[str, Any],
    *,
    max_pairs: int = 12,
) -> None:
    """
    Mutates rows in place: sets nli_label, nli_confidence (0..1) when enabled.
    evidence_by_id maps id -> object with .quote or dict with quote key.
    """
    if not _ENABLED or not rows:
        return

    pairs: list[tuple[int, str, str]] = []
    for i, row in enumerate(rows):
        if row.get("support_type") == "assumption":
            continue
        ct = str(row.get("claim_text") or "")[:800]
        eids = row.get("evidence_object_ids") or []
        if not isinstance(eids, list) or not ct:
            continue
        for eid in eids[:2]:
            sid = str(eid)
            ev = evidence_by_id.get(sid)
            if ev is None:
                continue
            quote = getattr(ev, "quote", None) or (ev.get("quote") if isinstance(ev, dict) else None) or ""
            quote = str(quote)[:1200]
            if quote.strip():
                pairs.append((i, ct, quote))
        if len(pairs) >= max_pairs:
            break

    if not pairs:
        return

    payload = [{"claim": c, "evidence_quote": q} for _, c, q in pairs[:max_pairs]]
    user = json.dumps({"pairs": payload}, ensure_ascii=False)
    system = """
You judge whether each evidence_quote entails, contradicts, or is neutral/insufficient relative to the claim.
Output ONLY JSON: {"results": [{"label": "entails|contradicts|neutral|insufficient", "confidence": 0.0-1.0}]}
Same order as input pairs. Be strict: insufficient if quote does not address the claim.
"""
    try:
        cfg = resolve("entailment")
        model = os.getenv("ARGUS_ENTAILMENT_MODEL", cfg.model)
        raw = await llm_call(
            system=system,
            user=user,
            model=model,
            temperature=0.0,
            max_tokens=cfg.max_tokens,
        )
        data = parse_llm_json(raw)
    except Exception:
        return
    res = data.get("results") if isinstance(data, dict) else None
    if not isinstance(res, list):
        return
    for idx, item in enumerate(res[: len(pairs)]):
        if not isinstance(item, dict):
            continue
        row_i, _, _ = pairs[idx]
        label = str(item.get("label", "neutral")).lower()
        try:
            conf = float(item.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        row = rows[row_i]
        row["nli_label"] = label
        row["nli_confidence"] = round(min(1.0, max(0.0, conf)), 4)
        if label in ("contradicts", "insufficient"):
            row["weak_or_unsupported"] = True
        if label == "contradicts":
            row["contradiction_flag"] = True
