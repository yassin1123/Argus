import json
import os
from typing import Any

from core.inference.structured import generate_structured
from core.model_router import resolve
from models.agent_structured import VerifierStructuredOutput
from models.evidence import EvidenceObject

VERIFIER_SYSTEM = """
You verify analytical claims against a catalog of evidence objects (each has id UUID, quote, source).
For each key claim in the analysis, list which evidence ids support it and a verdict:
supported | weak | unsupported | overstates
Output ONLY valid JSON:
{
  "claim_assessments": [
    {"claim": "short claim text", "evidence_ids": ["uuid"], "verdict": "supported", "notes": ""}
  ],
  "overall": "sufficient|insufficient",
  "gap_summary": "If insufficient, why",
  "suggested_searches": ["optional follow-up query"],
  "contradictions": ["tensions in evidence"]
}
Use only evidence ids from the catalog. If evidence is too thin for the recommendation, set overall to insufficient.

Verdict "overstates": use when the claim asserts a stronger fact than the evidence (e.g. evidence says "many" but the claim says "80%").
"""


def _verifier_model_and_temp() -> tuple[str | None, float]:
    cfg = resolve("verifier")
    model = os.getenv("ARGUS_VERIFIER_MODEL", "").strip() or None
    temp_s = os.getenv("ARGUS_VERIFIER_TEMPERATURE")
    temp = float(temp_s) if temp_s is not None else float(cfg.temperature)
    return model, temp


class VerifierAgent:
    async def run(
        self,
        analysis: dict[str, Any],
        evidence_objects: list[EvidenceObject],
        *,
        repair_hint: str | None = None,
        session_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        catalog = [o.for_llm_catalog() for o in evidence_objects if o.id]
        user = f"""
Analysis JSON: {json.dumps(analysis, ensure_ascii=False)[:12000]}
Evidence catalog: {json.dumps(catalog, ensure_ascii=False)[:14000]}
"""
        if repair_hint:
            user += f"\n\n{repair_hint}\n"
        vm, vt = _verifier_model_and_temp()
        out, _meta = await generate_structured(
            VerifierStructuredOutput,
            task_kind="verifier",
            system=VERIFIER_SYSTEM,
            user=user,
            temperature=vt,
            session_id=session_id,
            trace_id=trace_id,
            model_override=vm,
        )
        return out.model_dump()
