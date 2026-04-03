"""Assemble workspace API payload: session detail + presentation DTOs."""

from __future__ import annotations

from typing import Any

from db.queries import get_session_detail
from models.workspace_dto import build_presentation_from_detail


async def build_workspace_payload(session_id: str) -> dict[str, Any] | None:
    detail = await get_session_detail(session_id)
    if not detail:
        return None
    presentation = build_presentation_from_detail(detail)
    return {**detail, "presentation": presentation}
