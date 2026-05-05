"""Claim–support table: deterministic join of key_claims + evidence + verifier."""

import re
import uuid
from typing import Any

from models.evidence import EvidenceObject

_STOP = frozenset("the a an is to of and or for in on at as by be it we you".split())


def _norm_tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"\w+", s.lower()) if len(t) > 2 and t not in _STOP}


def lexical_entailment_score(claim: str, quote: str) -> float:
    ct = _norm_tokens(claim)
    qt = _norm_tokens(quote)
    if not ct:
        return 0.0
    return len(ct & qt) / max(len(ct), 1)


def _classify_support(eobjs: list[EvidenceObject]) -> str:
    if not eobjs:
        return "assumption"
    if all(o.is_inference for o in eobjs):
        return "inference"
    docs = [o for o in eobjs if o.source_type == "document"]
    webs = [o for o in eobjs if o.source_type == "web"]
    if docs:
        return "direct_quote"
    if webs:
        return "paraphrase"
    return "inference"


def _verdict_for_claim(claim_text: str, assessments: list[Any]) -> tuple[str | None, bool]:
    prefix = _norm_key(claim_text)[:80]
    for a in assessments:
        if not isinstance(a, dict):
            continue
        ac = str(a.get("claim", ""))
        if _norm_key(ac)[:80] == prefix or prefix in _norm_key(ac) or _norm_key(ac)[:40] in prefix:
            v = str(a.get("verdict", "")).lower()
            weak = v in ("unsupported", "overstates", "weak")
            return v, weak
    return None, False


def _norm_key(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def build_claim_support(
    analysis: dict[str, Any],
    evidence_objects: list[EvidenceObject],
    verification: dict[str, Any],
) -> list[dict[str, Any]]:
    by_id: dict[str, EvidenceObject] = {str(o.id): o for o in evidence_objects if o.id}
    assessments = verification.get("claim_assessments") or []
    if not isinstance(assessments, list):
        assessments = []

    rows: list[dict[str, Any]] = []
    kc = analysis.get("key_claims")
    if not isinstance(kc, list):
        return rows

    for i, item in enumerate(kc):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        raw_ids = item.get("evidence_ids")
        eids = [str(x) for x in raw_ids] if isinstance(raw_ids, list) else []
        eobjs = [by_id[e] for e in eids if e in by_id]
        stype = _classify_support(eobjs)
        combined_quote = " ".join((o.quote or "")[:500] for o in eobjs)
        ent = max((lexical_entailment_score(text, o.quote or "") for o in eobjs), default=0.0)
        if stype == "direct_quote" and ent < 0.08:
            stype = "paraphrase"

        verdict, weak = _verdict_for_claim(text, assessments)
        contradiction = verdict in ("unsupported", "overstates")

        rows.append(
            {
                "claim_id": str(item.get("claim_id") or f"kc_{i}_{uuid.uuid4().hex[:8]}"),
                "claim_text": text[:2000],
                "evidence_object_ids": eids,
                "support_type": stype,
                "verifier_verdict": verdict,
                "contradiction_flag": contradiction,
                "staleness_hint": "",
                "entailment_score": round(float(ent), 4),
                "weak_or_unsupported": weak,
            }
        )

    # Assumptions as separate rows
    for j, a in enumerate(analysis.get("assumptions") or []):
        if isinstance(a, str) and a.strip():
            rows.append(
                {
                    "claim_id": f"as_{j}",
                    "claim_text": a.strip()[:2000],
                    "evidence_object_ids": [],
                    "support_type": "assumption",
                    "verifier_verdict": None,
                    "contradiction_flag": False,
                    "staleness_hint": "",
                    "entailment_score": 0.0,
                    "weak_or_unsupported": False,
                }
            )

    return rows
