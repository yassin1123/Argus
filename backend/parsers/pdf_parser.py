from typing import Any

import fitz


def parse_pdf(file_bytes: bytes) -> dict[str, Any]:
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages: list[dict[str, Any]] = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text")
        if text.strip():
            pages.append({"page": page_num + 1, "text": text.strip()})
    full_text = "\n\n".join(p["text"] for p in pages)
    metadata = doc.metadata or {}
    return {
        "content": full_text,
        "pages": len(doc),
        "page_details": [{"page": p["page"], "chars": len(p["text"])} for p in pages],
        "title": metadata.get("title") or "Untitled",
        "author": metadata.get("author") or "Unknown",
        "word_count": len(full_text.split()),
    }
