"""Structure-aware chunking for PDFs (page boundaries). Plain text uses word windows."""

from typing import Any

import fitz


def _layout_blocks_for_page(page: fitz.Page, *, max_blocks: int = 14) -> dict[str, Any]:
    """Summarize PyMuPDF text blocks (bbox + type) for provenance."""
    try:
        d = page.get_text("dict")
    except Exception:
        return {"layout_blocks": [], "block_count": 0}
    blocks = d.get("blocks") or []
    summary: list[dict[str, Any]] = []
    for b in blocks[:max_blocks]:
        btype = b.get("type")
        bbox = b.get("bbox")
        bbox_list = [float(x) for x in bbox] if bbox and len(bbox) >= 4 else None
        if btype == 0:
            parts: list[str] = []
            for line in b.get("lines") or []:
                for sp in line.get("spans") or []:
                    parts.append(str(sp.get("text", "")))
            preview = "".join(parts).strip().replace("\n", " ")[:140]
            summary.append({"kind": "text", "bbox": bbox_list, "preview": preview})
        elif btype == 1:
            summary.append({"kind": "image", "bbox": bbox_list})
    return {"layout_blocks": summary, "block_count": len(blocks)}


def _section_hint_for_chunk(chunk: str) -> str:
    first = (chunk.strip().split("\n") or [""])[0].strip()
    if 0 < len(first) < 100 and first.upper() == first and any(c.isalpha() for c in first):
        return "heading_candidate"
    return "body"


def chunk_pdf_by_pages(
    pdf_bytes: bytes,
    *,
    chunk_words: int = 400,
    overlap: int = 50,
) -> list[tuple[str, dict[str, Any]]]:
    """Return (chunk_text, chunk_meta) pairs with page numbers."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    out: list[tuple[str, dict[str, Any]]] = []
    step = max(1, chunk_words - overlap)
    try:
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("text").strip()
            if not text:
                continue
            layout = _layout_blocks_for_page(page)
            words = text.split()
            for i in range(0, len(words), step):
                chunk = " ".join(words[i : i + chunk_words])
                if chunk:
                    out.append(
                        (
                            chunk,
                            {
                                "page": page_num + 1,
                                "section_hint": _section_hint_for_chunk(chunk),
                                "chunk_type": "pdf_text_window",
                                "structure": "pdf_page_window",
                                "provenance": "pymupdf_blocks",
                                **layout,
                            },
                        )
                    )
    finally:
        doc.close()
    return out
