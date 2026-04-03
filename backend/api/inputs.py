import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from core.chunker import chunk_pdf_by_pages
from core.embeddings import chunk_text, embed_texts
from db.queries import save_embeddings, save_uploaded_file
from parsers.csv_parser import parse_csv, parse_json
from parsers.pdf_parser import parse_pdf
from parsers.url_parser import parse_url, validate_public_url

router = APIRouter()

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_TABULAR_BYTES = 10 * 1024 * 1024


class UrlBody(BaseModel):
    url: str
    session_id: str


@router.post("/upload")
async def upload_file(
    session_id: str = Form(...),
    file: UploadFile = File(...),
) -> dict:
    content = await file.read()
    filename = file.filename or "upload"
    lower = filename.lower()
    if lower.endswith(".pdf"):
        if len(content) > MAX_PDF_BYTES:
            raise HTTPException(status_code=400, detail="PDF exceeds 20MB limit")
        parsed = parse_pdf(content)
        file_type = "pdf"
    elif lower.endswith(".csv"):
        if len(content) > MAX_TABULAR_BYTES:
            raise HTTPException(status_code=400, detail="CSV exceeds 10MB limit")
        parsed = parse_csv(content)
        file_type = "csv"
    elif lower.endswith(".json"):
        if len(content) > MAX_TABULAR_BYTES:
            raise HTTPException(status_code=400, detail="JSON exceeds 10MB limit")
        parsed = parse_json(content)
        file_type = "json"
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type")
    file_id = str(uuid.uuid4())
    await save_uploaded_file(
        file_id, session_id, filename, file_type, parsed["content"], len(content)
    )
    if lower.endswith(".pdf"):
        pairs = chunk_pdf_by_pages(content)
        chunks = [p[0] for p in pairs] if pairs else []
        if not chunks:
            chunks = chunk_text(parsed["content"])
            chunk_metas = [
                {"filename": filename, "file_type": file_type, "chunk_index": i} for i in range(len(chunks))
            ]
        else:
            chunk_metas = [
                {"filename": filename, "file_type": file_type, "chunk_index": i, **meta}
                for i, (_, meta) in enumerate(pairs)
            ]
    else:
        chunks = chunk_text(parsed["content"])
        chunk_metas = [
            {
                "filename": filename,
                "file_type": file_type,
                "chunk_index": i,
                "chunk_type": "tabular_or_text_window",
                "structure": "tabular_or_text_window",
                "section_hint": "body",
            }
            for i in range(len(chunks))
        ]
    if not chunks:
        return {"file_id": file_id, "chunks": 0}
    embeddings = await embed_texts(chunks)
    await save_embeddings(session_id, file_id, chunks, embeddings, chunk_metas=chunk_metas)
    return {"file_id": file_id, "chunks": len(chunks)}


@router.post("/url")
async def submit_url(body: UrlBody) -> dict:
    try:
        validate_public_url(body.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    parsed = await parse_url(body.url)
    file_id = str(uuid.uuid4())
    title = parsed.get("title") or body.url
    await save_uploaded_file(
        file_id,
        body.session_id,
        title,
        "url",
        parsed["content"],
        len(parsed["content"].encode("utf-8")),
    )
    chunks = chunk_text(parsed["content"])
    if not chunks:
        return {"file_id": file_id, "chunks": 0}
    embeddings = await embed_texts(chunks)
    chunk_metas = [
        {
            "filename": title,
            "file_type": "url",
            "chunk_index": i,
            "source_url": body.url,
            "chunk_type": "url_text_window",
            "structure": "url_text_window",
            "section_hint": "body",
        }
        for i in range(len(chunks))
    ]
    await save_embeddings(body.session_id, file_id, chunks, embeddings, chunk_metas=chunk_metas)
    return {"file_id": file_id, "chunks": len(chunks)}
