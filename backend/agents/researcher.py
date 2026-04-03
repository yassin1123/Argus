import json
import re

from core.json_util import parse_llm_json
from core.llm import llm_call_for_task
from core.retrieval import retrieve_evidence
from core.web_search import search_web
from models.evidence import ResearchPayload, RetrievedChunk

RESEARCHER_SYSTEM = """
You are the Researcher agent in the Argus decision system.
For ONE research task you must ground claims in the evidence provided.

Rules:
1. Every substantive claim in "finding" must be supported by at least one entry in "evidence".
2. Each evidence item MUST use a chunk_id from the ALLOWED_CHUNK_IDS list and a "quote" that is copied VERBATIM from that chunk's text (substring).
3. For web results, put URLs and titles only in "web_citations" (not in evidence.chunk_id).
4. If the evidence is insufficient, say so in "gaps" and lower confidence.

Output ONLY valid JSON:
{
  "findings": [
    {
      "task_id": 1,
      "question": "The research question",
      "finding": "Synthesis grounded in evidence only",
      "confidence": "high|medium|low",
      "evidence": [
        {
          "chunk_id": "uuid-from-allowed-list",
          "quote": "verbatim excerpt from that chunk",
          "filename": "optional hint",
          "similarity": 0.0
        }
      ],
      "web_citations": [{"title": "", "url": "", "snippet": ""}],
      "gaps": "What we could not verify from evidence"
    }
  ]
}
"""


def _normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def _quote_grounded(quote: str, chunk_text: str) -> bool:
    if not quote or not chunk_text:
        return False
    qn, cn = _normalize_ws(quote), _normalize_ws(chunk_text)
    if len(qn) < 8:
        return qn in cn
    return qn in cn or quote.strip() in chunk_text


def _sanitize_finding(
    finding: dict,
    chunks_by_id: dict[str, RetrievedChunk],
) -> dict:
    raw_ev = finding.get("evidence") or []
    kept: list[dict] = []
    for e in raw_ev if isinstance(raw_ev, list) else []:
        if not isinstance(e, dict):
            continue
        cid = str(e.get("chunk_id", ""))
        quote = str(e.get("quote", ""))
        hit = chunks_by_id.get(cid)
        if not hit:
            continue
        if not _quote_grounded(quote, hit.text):
            continue
        kept.append(
            {
                "chunk_id": cid,
                "quote": quote[:2000],
                "filename": hit.filename or e.get("filename", ""),
                "file_type": hit.file_type,
                "similarity": round(hit.similarity, 4),
                "chunk_index": hit.chunk_index,
                "source_url": hit.source_url,
            }
        )
    finding = dict(finding)
    finding["evidence"] = kept
    wc = finding.get("web_citations")
    if not isinstance(wc, list):
        finding["web_citations"] = []
    else:
        clean_wc = []
        for w in wc:
            if isinstance(w, dict):
                clean_wc.append(
                    {
                        "title": str(w.get("title", ""))[:500],
                        "url": str(w.get("url", ""))[:2000],
                        "snippet": str(w.get("snippet", ""))[:1500],
                    }
                )
        finding["web_citations"] = clean_wc
    if not kept and not finding.get("web_citations"):
        finding["confidence"] = "low"
        gaps = str(finding.get("gaps") or "")
        finding["gaps"] = (gaps + " No chunk evidence passed grounding checks.").strip()
    return finding


class ResearcherAgent:
    async def run(self, plan: dict, session_id: str, context: str) -> dict:
        all_findings: list[dict] = []
        for task in plan.get("tasks", []):
            q = task.get("question", "")
            hits = await retrieve_evidence(session_id, q, top_k=8)
            chunks_by_id = {h.chunk_id: h for h in hits}
            allowed_ids = list(chunks_by_id.keys())
            hits_payload = [h.model_dump() for h in hits]
            web_results = ""
            if task.get("priority") == "high":
                web_results = await search_web(q)
            user_msg = f"""
Task: {json.dumps(task)}
ALLOWED_CHUNK_IDS: {json.dumps(allowed_ids)}
Retrieved chunks (use only these chunk_id values; quotes must be substrings of "text"):
{json.dumps(hits_payload, indent=2)[:12000]}
Web search results: {web_results[:6000]}
Additional context: {context[:1000]}
"""
            response = await llm_call_for_task(
                "researcher",
                RESEARCHER_SYSTEM,
                user=user_msg,
                temperature=0.2,
            )
            parsed = parse_llm_json(response)
            findings = parsed.get("findings") or []
            for f in findings if isinstance(findings, list) else []:
                if isinstance(f, dict):
                    all_findings.append(_sanitize_finding(f, chunks_by_id))
        try:
            ResearchPayload.model_validate({"findings": all_findings})
        except Exception:
            pass
        return {"findings": all_findings}
