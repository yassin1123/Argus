import hashlib
import inspect
import io
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from db.queries import (
    get_export_artifact_cache,
    get_report,
    get_session_row,
    save_deck_blueprint,
    save_export_artifact_cache,
)
from deliverables.blueprint import DeliverableBlueprint, build_deliverable_blueprint
from deliverables.pptx_build import render_pptx_from_blueprint
from deliverables.render_pdf import render_deliverable_pdf

router = APIRouter()


def _content_hash(fingerprint: str, format_key: str, variant: str = "") -> str:
    raw = f"{fingerprint}:{format_key}:{variant}".encode()
    return hashlib.sha256(raw).hexdigest()


async def _load_session_report(session_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    report = await get_report(session_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    sess = await get_session_row(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    return report, sess


def _blueprint_for_session(
    report: dict[str, Any], sess: dict[str, Any]
) -> DeliverableBlueprint:
    return build_deliverable_blueprint(
        report=report,
        session_query=str(sess.get("query", "")),
        session_title=str(sess.get("title", "Argus")),
    )


async def _cached_bytes(
    session_id: str,
    format_key: str,
    fingerprint: str,
    variant: str,
    factory: Callable[[], Awaitable[bytes]] | Callable[[], bytes],
) -> bytes:
    ch = _content_hash(fingerprint, format_key, variant)
    hit = await get_export_artifact_cache(session_id, format_key, ch)
    if hit:
        return hit
    out = factory()
    data = await out if inspect.isawaitable(out) else out  # type: ignore[assignment]
    await save_export_artifact_cache(session_id, format_key, ch, data)
    return data


@router.get("/pdf/{session_id}")
async def export_pdf(session_id: str) -> StreamingResponse:
    report, sess = await _load_session_report(session_id)
    bp = _blueprint_for_session(report, sess)

    async def make() -> bytes:
        return render_deliverable_pdf(bp.document, variant="full", report=report)

    pdf = await _cached_bytes(session_id, "pdf_full", bp.fingerprint, "full", make)
    return StreamingResponse(
        io.BytesIO(pdf),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="argus-report-{session_id[:8]}.pdf"'
        },
    )


@router.get("/memo/{session_id}")
async def export_memo_pdf(session_id: str) -> StreamingResponse:
    """Internal working memo PDF (includes verification block)."""
    report, sess = await _load_session_report(session_id)
    bp = _blueprint_for_session(report, sess)

    async def make() -> bytes:
        return render_deliverable_pdf(bp.document, variant="memo", report=report)

    pdf = await _cached_bytes(session_id, "pdf_memo", bp.fingerprint, "memo", make)
    return StreamingResponse(
        io.BytesIO(pdf),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="argus-memo-{session_id[:8]}.pdf"'
        },
    )


@router.get("/report/{session_id}")
async def export_client_pdf(session_id: str) -> StreamingResponse:
    """Client-facing report PDF."""
    report, sess = await _load_session_report(session_id)
    bp = _blueprint_for_session(report, sess)

    async def make() -> bytes:
        return render_deliverable_pdf(bp.document, variant="client", report=report)

    pdf = await _cached_bytes(session_id, "pdf_client", bp.fingerprint, "client", make)
    return StreamingResponse(
        io.BytesIO(pdf),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="argus-client-{session_id[:8]}.pdf"'
        },
    )


@router.get("/pptx/{session_id}")
async def export_pptx(session_id: str) -> StreamingResponse:
    report, sess = await _load_session_report(session_id)
    bp = _blueprint_for_session(report, sess)

    async def make() -> bytes:
        data, blueprint = render_pptx_from_blueprint(bp.slide_blueprint)
        merged = {**blueprint, "deliverable_blueprint": bp.to_meta()}
        await save_deck_blueprint(session_id, merged)
        return data

    pptx = await _cached_bytes(session_id, "pptx", bp.fingerprint, "v1", make)
    return StreamingResponse(
        io.BytesIO(pptx),
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={
            "Content-Disposition": f'attachment; filename="argus-deck-{session_id[:8]}.pptx"'
        },
    )
