import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from auth.dependencies import get_current_user
from auth.permissions import can_read, can_write
from core.chunker import chunk_pdf_by_pages
from core.embeddings import chunk_text, embed_texts
from db.queries import save_embeddings, save_uploaded_file
from ingest.pipeline import ingest as ingest_chunks
from parsers.csv_parser import parse_csv, parse_json
from parsers.pdf_parser import parse_pdf
from parsers.url_parser import parse_url, validate_public_url
from storage.blob import get_signed_url, make_blob_key, upload_bytes
from storage.queries import (
    attach_blob_to_uploaded_file,
    get_source_blob,
    insert_source_blob,
)

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_PDF_BYTES = 50 * 1024 * 1024  # bumped from 20 → 50 with blob storage
MAX_TABULAR_BYTES = 25 * 1024 * 1024


class UrlBody(BaseModel):
    url: str
    session_id: str


@router.post("/upload")
async def upload_file(
    session_id: str = Form(...),
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
) -> dict:
    if not await can_write(session_id, user):
        raise HTTPException(status_code=403, detail="No write access on this engagement")

    content = await file.read()
    filename = file.filename or "upload"
    lower = filename.lower()

    # Choose content type + size limit + parser by extension.
    if lower.endswith(".pdf"):
        if len(content) > MAX_PDF_BYTES:
            raise HTTPException(status_code=400, detail="PDF exceeds 50MB limit")
        parsed = parse_pdf(content)
        file_type = "pdf"
        content_type = "application/pdf"
    elif lower.endswith(".csv"):
        if len(content) > MAX_TABULAR_BYTES:
            raise HTTPException(status_code=400, detail="CSV exceeds 25MB limit")
        parsed = parse_csv(content)
        file_type = "csv"
        content_type = "text/csv"
    elif lower.endswith(".json"):
        if len(content) > MAX_TABULAR_BYTES:
            raise HTTPException(status_code=400, detail="JSON exceeds 25MB limit")
        parsed = parse_json(content)
        file_type = "json"
        content_type = "application/json"
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    # 1. Push original bytes to object storage.
    blob_key = make_blob_key(tenant_id=None, engagement_id=session_id, filename=filename)
    try:
        blob_meta = upload_bytes(
            key=blob_key,
            body=content,
            content_type=content_type,
            metadata={
                "engagement_id": session_id,
                "uploaded_by": user["user_id"],
                "filename": filename,
            },
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("blob upload failed")
        raise HTTPException(status_code=500, detail=f"Storage upload failed: {e}") from e

    blob_id = await insert_source_blob(
        session_id=session_id,
        s3_key=blob_meta["key"],
        size_bytes=blob_meta["size"],
        content_type=blob_meta["content_type"],
        sha256=blob_meta["sha256"],
        uploaded_by=user["user_id"],
    )

    # 2. Persist parsed text + link to blob.
    file_id = str(uuid.uuid4())
    await save_uploaded_file(
        file_id, session_id, filename, file_type, parsed["content"], len(content)
    )
    await attach_blob_to_uploaded_file(file_id, blob_id)

    # 3. Chunk + embed.
    if lower.endswith(".pdf"):
        pairs = chunk_pdf_by_pages(content)
        chunks = [p[0] for p in pairs] if pairs else []
        if not chunks:
            chunks = chunk_text(parsed["content"])
            chunk_metas = [
                {"filename": filename, "file_type": file_type, "chunk_index": i}
                for i in range(len(chunks))
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
        return {"file_id": file_id, "blob_id": blob_id, "chunks": 0}

    embeddings = await embed_texts(chunks)
    await save_embeddings(session_id, file_id, chunks, embeddings, chunk_metas=chunk_metas)

    # Phase 4: also write to the new `chunks` table with rich page/section metadata.
    new_kind = "pdf" if file_type == "pdf" else ("csv" if file_type == "csv" else ("json" if file_type == "json" else "web"))
    chunk_result = await ingest_chunks(
        session_id=session_id,
        source_file_id=file_id,
        blob_id=blob_id,
        source_kind=new_kind,  # type: ignore[arg-type]
        content=content,
        source_filename=filename,
        source_url=None,
    )

    return {
        "file_id": file_id,
        "blob_id": blob_id,
        "chunks": len(chunks),
        "rich_chunks": chunk_result.get("chunks_inserted", 0),
        "size_bytes": blob_meta["size"],
        "sha256": blob_meta["sha256"],
    }


@router.post("/url")
async def submit_url(body: UrlBody, user: dict = Depends(get_current_user)) -> dict:
    if not await can_write(body.session_id, user):
        raise HTTPException(status_code=403, detail="No write access on this engagement")
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

    # Phase 4 dual-write into rich chunks table (web kind, with the URL preserved).
    chunk_result = await ingest_chunks(
        session_id=body.session_id,
        source_file_id=file_id,
        blob_id=None,
        source_kind="web",
        content=parsed["content"],
        source_filename=title,
        source_url=body.url,
    )

    return {
        "file_id": file_id,
        "chunks": len(chunks),
        "rich_chunks": chunk_result.get("chunks_inserted", 0),
    }


@router.get("/sources/{source_file_id}/chunks")
async def list_chunks(
    source_file_id: str,
    user: dict = Depends(get_current_user),
) -> dict:
    """Inspect rich chunks (page/section/timestamp metadata) for a source."""
    from storage.chunk_queries import list_chunks_for_source
    rows = await list_chunks_for_source(source_file_id)
    if not rows:
        return {"chunks": []}
    # Permission: any chunk in the result must belong to a session the user can read.
    session_id = rows[0]["session_id"]
    if not await can_read(session_id, user):
        raise HTTPException(status_code=404, detail="Source not found")
    return {"chunks": rows}


@router.get("/blobs/{blob_id}/download")
async def download_blob(blob_id: str, user: dict = Depends(get_current_user)) -> RedirectResponse:
    """302 redirect to a short-lived signed S3 URL.

    Permission: caller must have read access on the blob's engagement.
    """
    blob = await get_source_blob(blob_id)
    if not blob:
        raise HTTPException(status_code=404, detail="Blob not found")
    if blob["session_id"] and not await can_read(blob["session_id"], user):
        raise HTTPException(status_code=404, detail="Blob not found")
    url = get_signed_url(blob["s3_key"], expires_in=900)
    return RedirectResponse(url=url, status_code=302)
