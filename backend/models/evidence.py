from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class RetrievedChunk(BaseModel):
    """One vector hit with provenance (from DB, not LLM)."""

    chunk_id: str
    text: str
    chunk_index: int
    similarity: float = Field(ge=0.0, le=1.0)
    filename: str = ""
    file_type: str = ""
    file_id: str | None = None
    page: int | None = None
    source_url: str | None = None
    section_hint: str | None = None
    chunk_type: str | None = None

    model_config = {"extra": "ignore"}

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "RetrievedChunk":
        meta = row.get("chunk_meta") or {}
        if isinstance(meta, str):
            import json

            meta = json.loads(meta)
        page = meta.get("page")
        if page is not None:
            try:
                page = int(page)
            except (TypeError, ValueError):
                page = None
        chunk_type = meta.get("chunk_type") or meta.get("structure")
        return cls(
            chunk_id=str(row["id"]),
            text=row["chunk_text"],
            chunk_index=int(row["chunk_index"]),
            similarity=float(row["similarity"]),
            filename=row.get("filename") or "",
            file_type=row.get("file_type") or "",
            file_id=str(row["file_id"]) if row.get("file_id") else None,
            page=page,
            source_url=meta.get("source_url"),
            section_hint=str(meta["section_hint"]) if meta.get("section_hint") else None,
            chunk_type=str(chunk_type) if chunk_type else None,
        )


class EvidenceRef(BaseModel):
    """Researcher must cite retrieved chunks with verbatim quotes."""

    chunk_id: str
    quote: str = Field(..., min_length=1, max_length=2000)
    filename: str = ""
    file_type: str = ""
    similarity: float | None = None
    chunk_index: int | None = None
    source_url: str | None = None

    model_config = {"extra": "ignore"}


class WebCitation(BaseModel):
    title: str = ""
    url: str = ""
    snippet: str = ""

    model_config = {"extra": "ignore"}


class ResearchFinding(BaseModel):
    task_id: int | None = None
    question: str = ""
    finding: str = ""
    confidence: str = "medium"
    evidence: list[EvidenceRef] = Field(default_factory=list)
    web_citations: list[WebCitation] = Field(default_factory=list)
    gaps: str = ""

    model_config = {"extra": "ignore"}

    @field_validator("evidence", mode="before")
    @classmethod
    def coerce_evidence(cls, v: Any) -> list:
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        out: list[EvidenceRef] = []
        for item in v:
            if isinstance(item, dict):
                try:
                    out.append(EvidenceRef.model_validate(item))
                except Exception:
                    continue
        return out


class ResearchPayload(BaseModel):
    findings: list[ResearchFinding] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class EvidenceObject(BaseModel):
    """Single citeable evidence row aligned with `evidence_objects` (V2).

    ``metadata`` (Phase 2 / Week 5 / Day 4) carries source-type-specific
    breadcrumb data the citation popover renders inline. For
    firm-library chunks today: ``firm_content_id``, ``firm_library_title``,
    ``category``, ``intended_modes``, ``section``. Other source types
    can populate it as enrichments arrive — the field is intentionally
    free-form jsonb so the schema doesn't churn per source.
    """

    id: str | None = None
    session_id: str
    task_id: int | None = None
    claim: str = ""
    quote: str = ""
    source_title: str = ""
    source_url: str = ""
    source_date: str | None = None
    source_type: str = "web"
    source_score: float = Field(0.0, ge=0.0)
    confidence: str = "medium"
    is_inference: bool = False
    created_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "ignore"}

    @classmethod
    def from_db_row(cls, row: Any) -> "EvidenceObject":
        tid = row.get("task_id")
        meta = row.get("metadata") if "metadata" in row.keys() else None
        if isinstance(meta, str):
            import json as _json

            try:
                meta = _json.loads(meta)
            except Exception:
                meta = {}
        if not isinstance(meta, dict):
            meta = {}
        return cls(
            id=str(row["id"]),
            session_id=str(row["session_id"]),
            task_id=int(tid) if tid is not None else None,
            claim=row.get("claim") or "",
            quote=row.get("quote") or "",
            source_title=row.get("source_title") or "",
            source_url=row.get("source_url") or "",
            source_date=row.get("source_date"),
            source_type=row.get("source_type") or "web",
            source_score=float(row.get("source_score") or 0),
            confidence=row.get("confidence") or "medium",
            is_inference=bool(row.get("is_inference")),
            created_at=row["created_at"] if row.get("created_at") else None,
            metadata=meta,
        )

    def for_llm_catalog(self) -> dict[str, Any]:
        """Subset for agent prompts (stable keys)."""
        d = self.model_dump(mode="json", exclude={"session_id", "created_at"})
        if d.get("id") is None:
            d.pop("id", None)
        return d
