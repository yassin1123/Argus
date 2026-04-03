"""Report-side blueprint: fingerprinting and narrative document assembly."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from deliverables.assemble import build_deliverable_document
from deliverables.models import DeliverableDocument


def report_fingerprint(report: dict[str, Any]) -> str:
    try:
        raw = json.dumps(report, sort_keys=True, default=str)[:12000]
    except (TypeError, ValueError):
        raw = str(id(report))
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def build_report_document(
    *,
    report: dict[str, Any],
    session_query: str,
    session_title: str,
) -> DeliverableDocument:
    return build_deliverable_document(
        report=report, session_query=session_query, session_title=session_title
    )
