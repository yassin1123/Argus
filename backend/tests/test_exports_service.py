"""Phase 3 / Week 10 / Day 2 — export pipeline foundation tests.

Five tests per spec:

  1. test_generate_artifact_writes_row
  2. test_artifact_payload_snapshot_frozen
  3. test_unknown_exporter_returns_failed
  4. test_cross_firm_access_returns_404
  5. test_generation_creates_file_on_disk

Tests 1-3, 5 mock the DB so they run without Postgres. Test 4 uses
FastAPI's TestClient with the auth + permission dependencies overridden
so it exercises the API surface without hitting the DB.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest import mock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import session_exports as se_module
from auth.dependencies import get_current_user
from core.exports import (
    GenerateArtifactRequest,
    generate_artifact,
)
from core.exports import service as exports_service


# ---------------------------------------------------------------------------
# Sample payload used across tests
# ---------------------------------------------------------------------------

_SAMPLE_PAYLOAD: dict[str, Any] = {
    "recommendation": "PROCEED WITH CONDITIONS",
    "confidence_level": "Medium-High",
    "summary": "TargetCo de-risks via earnouts.",
    "key_reasons": ["Stable cash flow.", "Strong segment leadership."],
    "risks": ["Customer concentration."],
    "counterarguments": [],
    "next_steps": [],
    "sources": [],
    "caveats": "",
}

_SAMPLE_BRANDING: dict[str, Any] = {
    "primary_color": "#0F6E56",
    "footer_text": "Test Firm · Confidential",
}


# ---------------------------------------------------------------------------
# Fake `acquire()` factory — mirrors the section-deepening test pattern
# ---------------------------------------------------------------------------


def _fake_acquire_factory(
    stored: dict[str, Any],
    *,
    payload: dict[str, Any] | None = None,
    branding: dict[str, Any] | None = None,
    firm_id: UUID | None = None,
) -> Any:
    payload = payload if payload is not None else _SAMPLE_PAYLOAD
    branding = branding if branding is not None else _SAMPLE_BRANDING
    firm_id = firm_id or stored.setdefault("firm_id", uuid4())

    class _FakeConn:
        async def execute(self, sql: str, *args: Any) -> None:
            s = " ".join(sql.split()).lower()
            if "insert into export_artifacts" in s:
                # cols: id, session_id, firm_id, artifact_type, format,
                #       payload_snapshot, generated_by, status
                stored["insert_args"] = args
                stored["id"] = args[0]
                stored["session_id"] = args[1]
                stored["firm_id"] = args[2]
                stored["artifact_type"] = args[3]
                stored["format"] = args[4]
                stored["payload_snapshot"] = args[5]
                stored["status"] = "generating"
            elif "update export_artifacts" in s:
                if "status = 'ready'" in s:
                    stored["status"] = "ready"
                    stored["file_path"] = args[1]
                    stored["file_size_bytes"] = args[2]
                    stored["claim_citation_count"] = args[3]
                    stored["generation_wall_seconds"] = args[4]
                    stored["metadata"] = args[5]
                elif "status = 'failed'" in s:
                    stored["status"] = "failed"
                    stored["failure_reason"] = args[1]
                    stored["generation_wall_seconds"] = args[2]
            else:
                stored.setdefault("other_sql", []).append((s, args))

        async def fetchrow(self, sql: str, *args: Any) -> Any:
            s = " ".join(sql.split()).lower()
            if "select firm_id from sessions" in s:
                return {"firm_id": firm_id}
            if "from sessions where id" in s:
                # _session_meta query
                return {
                    "title": "Test Engagement",
                    "query": "test brief",
                    "report_mode": stored.get("report_mode") or "general",
                    "metadata": {},
                }
            if "from firms where id" in s:
                return {"name": "Test Firm", "branding": dict(branding)}
            if "from reports where session_id" in s:
                cp_keys = (
                    "recommendation", "confidence_level", "summary",
                    "key_reasons", "risks", "counterarguments",
                    "next_steps", "sources", "caveats",
                )
                row: dict[str, Any] = {k: payload.get(k) for k in cp_keys}
                cp_extras = {k: v for k, v in payload.items() if k not in cp_keys}
                row["consulting_payload"] = cp_extras
                return row
            return None

        async def fetch(self, sql: str, *args: Any) -> list[Any]:
            return []

    class _FakeAcquire:
        async def __aenter__(self) -> Any:
            return _FakeConn()

        async def __aexit__(self, *exc: Any) -> None:
            return None

    def factory() -> Any:
        return _FakeAcquire()

    return factory


@pytest.fixture
def tmp_artifacts_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ARGUS_ARTIFACTS_ROOT at a pytest-managed temp dir so the
    real filesystem isn't littered with stub files."""
    monkeypatch.setenv("ARGUS_ARTIFACTS_ROOT", str(tmp_path))
    return tmp_path


# ---------------------------------------------------------------------------
# Test 1 — generate_artifact writes a row with the expected fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_artifact_writes_row(tmp_artifacts_root: Path) -> None:
    stored: dict[str, Any] = {}
    fake_acquire = _fake_acquire_factory(stored)

    req = GenerateArtifactRequest(
        session_id=uuid4(),
        artifact_type="one_pager",
        format="html",
    )

    with mock.patch.object(exports_service, "acquire", new=fake_acquire):
        result = await generate_artifact(req, triggered_by=uuid4())

    assert result.status == "ready", f"expected ready, got {result.status}: {result.failure_reason}"
    assert stored["status"] == "ready"
    assert stored["artifact_type"] == "one_pager"
    assert stored["format"] == "html"
    assert stored["file_size_bytes"] is not None and stored["file_size_bytes"] > 0
    # The stub exporter writes the recommendation into the <h1>.
    file_bytes = Path(stored["file_path"]).read_bytes()
    assert b"PROCEED WITH CONDITIONS" in file_bytes


# ---------------------------------------------------------------------------
# Test 2 — payload_snapshot is frozen at generation time
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_artifact_payload_snapshot_frozen(tmp_artifacts_root: Path) -> None:
    """The artifact row's ``payload_snapshot`` captures the payload at
    generate time. Mutating the session payload afterwards must not
    change what's stored on the artifact row."""
    mutable_payload = dict(_SAMPLE_PAYLOAD)
    stored: dict[str, Any] = {}
    fake_acquire = _fake_acquire_factory(stored, payload=mutable_payload)

    req = GenerateArtifactRequest(
        session_id=uuid4(),
        artifact_type="one_pager",
        format="html",
    )
    with mock.patch.object(exports_service, "acquire", new=fake_acquire):
        result = await generate_artifact(req)

    assert result.status == "ready"
    snapshot_raw = stored.get("payload_snapshot")
    assert snapshot_raw is not None
    snapshot = json.loads(snapshot_raw) if isinstance(snapshot_raw, str) else snapshot_raw
    assert snapshot["recommendation"] == "PROCEED WITH CONDITIONS"

    # Mutate the upstream payload — the snapshot must not move.
    mutable_payload["recommendation"] = "REJECT"
    assert snapshot["recommendation"] == "PROCEED WITH CONDITIONS"


# ---------------------------------------------------------------------------
# Test 3 — unknown (artifact_type, format) lands a failed row with reason
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_exporter_returns_failed(tmp_artifacts_root: Path) -> None:
    stored: dict[str, Any] = {}
    fake_acquire = _fake_acquire_factory(stored)

    # ``memo/json`` is in the schema whitelist but no exporter is
    # registered (W14 work). The exporter-not-found path is what we
    # want to exercise. By W13/D4 the registered combinations are
    # one_pager/html+pdf, deck/pptx, excel_model/xlsx, email/md+html+pdf,
    # interview_guide/md+html+pdf — so we use the still-unregistered
    # memo/json pair here.
    req = GenerateArtifactRequest(
        session_id=uuid4(),
        artifact_type="memo",
        format="json",
    )
    with mock.patch.object(exports_service, "acquire", new=fake_acquire):
        result = await generate_artifact(req)

    assert result.status == "failed"
    assert result.failure_reason is not None
    assert "no exporter registered" in result.failure_reason
    assert "memo" in result.failure_reason and "json" in result.failure_reason
    # Failed row persisted (not silently dropped)
    assert stored["status"] == "failed"


# ---------------------------------------------------------------------------
# Test 4 — cross-firm access via the API returns 404 (not 403)
# ---------------------------------------------------------------------------


def _build_app(user_id: str | None = None) -> tuple[FastAPI, TestClient]:
    uid = user_id or str(uuid4())
    app = FastAPI()
    app.include_router(se_module.router, prefix="/api/sessions")

    async def fake_user() -> dict:
        return {"user_id": uid, "email": "tester@argus.local", "role": "member"}

    app.dependency_overrides[get_current_user] = fake_user
    return app, TestClient(app)


def test_cross_firm_access_returns_404() -> None:
    """A firm-B member querying a firm-A artifact must see 404 (hiding
    existence), not 403."""
    sid = str(uuid4())
    aid = str(uuid4())
    app, client = _build_app()
    with mock.patch.object(se_module, "can_read", new=mock.AsyncMock(return_value=False)):
        r = client.get(f"/api/sessions/{sid}/exports/{aid}")
    assert r.status_code == 404, r.text
    assert "Session not found" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Test 5 — generation creates a file at the expected on-disk path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generation_creates_file_on_disk(tmp_artifacts_root: Path) -> None:
    stored: dict[str, Any] = {}
    firm_id = uuid4()
    fake_acquire = _fake_acquire_factory(stored, firm_id=firm_id)

    session_id = uuid4()
    req = GenerateArtifactRequest(
        session_id=session_id,
        artifact_type="one_pager",
        format="html",
    )
    with mock.patch.object(exports_service, "acquire", new=fake_acquire):
        result = await generate_artifact(req)

    assert result.status == "ready"
    assert result.file_path is not None
    fp = Path(result.file_path)
    assert fp.exists(), f"expected file at {fp}"
    # Path convention: <root>/<firm_id>/<session_id>/<artifact_id>.<format>
    assert fp.suffix == ".html"
    assert str(firm_id) in fp.as_posix()
    assert str(session_id) in fp.as_posix()
    assert str(result.artifact_id) in fp.name
    # File contains the rendered HTML (D3: recommendation panel +
    # branding-driven CSS variables + the actual recommendation text).
    body = fp.read_text(encoding="utf-8")
    assert "PROCEED WITH CONDITIONS" in body
    assert "recommendation" in body  # panel marker
    assert "#0F6E56" in body  # primary_color from _SAMPLE_BRANDING
