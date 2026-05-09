"""Firm library permissions + audit tests (Phase 2 / Week 5 / Day 3).

Hits the FastAPI app via httpx.AsyncClient + ASGITransport so the full
middleware + dependency chain runs. Auth is bypassed by patching
``get_current_user`` per test to inject the right user identity.

Cross-firm isolation is the load-bearing contract here — these tests
exist to prove that a member of firm A can never see firm B's content,
no matter which endpoint they hit.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from auth import dependencies as auth_dep


@pytest.fixture(autouse=True)
async def _db_pool():
    from db.connection import close_db, init_db

    await init_db()
    try:
        yield
    finally:
        await close_db()


@pytest.fixture
def stub_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hash-based deterministic 1536-d vector — no OpenAI calls."""
    import hashlib

    async def _stub(texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            full = (h * (1536 // len(h) + 1))[:1536]
            out.append([(b - 128) / 128.0 for b in full])
        return out

    import core.firm_library.service as svc

    monkeypatch.setattr(svc, "embed_texts", _stub)


def _user_dict(user_id: str, email: str, role: str = "member") -> dict[str, Any]:
    return {
        "user_id": user_id,
        "email": email,
        "full_name": email.split("@")[0],
        "role": role,
    }


@pytest.fixture
async def two_firms_two_users():
    """Build two firms, four users:
      - admin_a / member_a — firm A
      - admin_b / member_b — firm B
    Yields the IDs and cleans up.
    """
    from db.connection import acquire

    firm_a = str(uuid.uuid4())
    firm_b = str(uuid.uuid4())
    admin_a = str(uuid.uuid4())
    member_a = str(uuid.uuid4())
    admin_b = str(uuid.uuid4())
    member_b = str(uuid.uuid4())

    async with acquire() as conn:
        await conn.execute(
            "INSERT INTO firms (id, name, slug) VALUES "
            "($1::uuid, $2, $3), ($4::uuid, $5, $6)",
            firm_a, f"Firm A {firm_a[:6]}", f"firm-a-{firm_a[:8]}",
            firm_b, f"Firm B {firm_b[:6]}", f"firm-b-{firm_b[:8]}",
        )
        await conn.execute(
            """
            INSERT INTO users (id, email, password_hash, full_name, role) VALUES
            ($1::uuid, $2, 'x', 'AdminA', 'member'),
            ($3::uuid, $4, 'x', 'MemberA', 'member'),
            ($5::uuid, $6, 'x', 'AdminB', 'member'),
            ($7::uuid, $8, 'x', 'MemberB', 'member')
            """,
            admin_a, f"admin-a-{firm_a[:8]}@test.argus.invalid",
            member_a, f"mem-a-{firm_a[:8]}@test.argus.invalid",
            admin_b, f"admin-b-{firm_b[:8]}@test.argus.invalid",
            member_b, f"mem-b-{firm_b[:8]}@test.argus.invalid",
        )
        await conn.execute(
            """
            INSERT INTO firm_memberships (firm_id, user_id, role) VALUES
            ($1::uuid, $2::uuid, 'admin'),
            ($1::uuid, $3::uuid, 'member'),
            ($4::uuid, $5::uuid, 'admin'),
            ($4::uuid, $6::uuid, 'member')
            """,
            firm_a, admin_a, member_a,
            firm_b, admin_b, member_b,
        )
    try:
        yield {
            "firm_a": firm_a, "firm_b": firm_b,
            "admin_a": admin_a, "member_a": member_a,
            "admin_b": admin_b, "member_b": member_b,
            "admin_a_user": _user_dict(admin_a, f"admin-a-{firm_a[:8]}@test.argus.invalid"),
            "member_a_user": _user_dict(member_a, f"mem-a-{firm_a[:8]}@test.argus.invalid"),
            "admin_b_user": _user_dict(admin_b, f"admin-b-{firm_b[:8]}@test.argus.invalid"),
            "member_b_user": _user_dict(member_b, f"mem-b-{firm_b[:8]}@test.argus.invalid"),
        }
    finally:
        async with acquire() as conn:
            uids = (admin_a, member_a, admin_b, member_b)
            fids = (firm_a, firm_b)
            await conn.execute(
                "DELETE FROM chunks WHERE firm_id = ANY($1::uuid[])", list(fids)
            )
            await conn.execute(
                "DELETE FROM firm_content WHERE firm_id = ANY($1::uuid[])", list(fids)
            )
            await conn.execute(
                "DELETE FROM audit_events WHERE actor_user_id = ANY($1::uuid[])", list(uids)
            )
            await conn.execute(
                "DELETE FROM firms WHERE id = ANY($1::uuid[])", list(fids)
            )
            await conn.execute(
                "DELETE FROM users WHERE id = ANY($1::uuid[])", list(uids)
            )


def _set_current_user(monkeypatch: pytest.MonkeyPatch, user: dict[str, Any]) -> None:
    """Wire FastAPI's get_current_user dependency to return ``user``.

    The override callable's signature must NOT take *args/**kwargs —
    FastAPI inspects it and turns those into query parameters, leading
    to a 422 before the endpoint code runs. A no-arg async function is
    the right shape.
    """
    async def _stub() -> dict[str, Any]:
        return user

    app.dependency_overrides[auth_dep.get_current_user] = _stub


def _clear_current_user() -> None:
    app.dependency_overrides.pop(auth_dep.get_current_user, None)


def _md_blob() -> bytes:
    return (
        b"# Playbook\n\n"
        b"When advising on a payments target screen the partner-led checklist "
        b"is to confirm three things before the next-step gate. "
        * 6
    )


async def _upload_as(client: AsyncClient, firm_id: str, *, title: str = "P") -> Any:
    files = {"file": ("p.md", _md_blob(), "text/markdown")}
    data = {"title": title, "category": "playbook"}
    return await client.post(f"/api/firms/{firm_id}/library", data=data, files=files)


# ---------------------------------------------------------------------------
# 1. test_member_cannot_upload (403)
# ---------------------------------------------------------------------------


async def test_member_cannot_upload(
    two_firms_two_users, monkeypatch, stub_embed
) -> None:
    _set_current_user(monkeypatch, two_firms_two_users["member_a_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await _upload_as(c, two_firms_two_users["firm_a"])
        assert r.status_code == 403, r.text
        assert "admin" in r.json().get("detail", "").lower()
    finally:
        _clear_current_user()


# ---------------------------------------------------------------------------
# 2. test_member_can_list (200)
# ---------------------------------------------------------------------------


async def test_member_can_list(
    two_firms_two_users, monkeypatch, stub_embed
) -> None:
    # Admin uploads first so there's something to list.
    _set_current_user(monkeypatch, two_firms_two_users["admin_a_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await _upload_as(c, two_firms_two_users["firm_a"], title="LB1")
        assert r.status_code == 200, r.text
    finally:
        _clear_current_user()

    # Now member lists — must succeed.
    _set_current_user(monkeypatch, two_firms_two_users["member_a_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get(f"/api/firms/{two_firms_two_users['firm_a']}/library")
        assert r.status_code == 200, r.text
        rows = r.json().get("firm_content") or []
        assert len(rows) >= 1
        assert any(r["title"] == "LB1" for r in rows)
    finally:
        _clear_current_user()


# ---------------------------------------------------------------------------
# 3. test_admin_can_retire (200)
# ---------------------------------------------------------------------------


async def test_admin_can_retire(
    two_firms_two_users, monkeypatch, stub_embed
) -> None:
    _set_current_user(monkeypatch, two_firms_two_users["admin_a_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await _upload_as(c, two_firms_two_users["firm_a"], title="ToRetire")
            assert r.status_code == 200
            cid = r.json()["firm_content"]["id"]
            r = await c.post(
                f"/api/firms/{two_firms_two_users['firm_a']}/library/{cid}/retire"
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["firm_content"]["retired_at"] is not None
        assert body["already_retired"] is False
    finally:
        _clear_current_user()


# ---------------------------------------------------------------------------
# 4. test_cross_firm_list_returns_404
# ---------------------------------------------------------------------------


async def test_cross_firm_list_returns_404(
    two_firms_two_users, monkeypatch
) -> None:
    """Per spec the cross-firm denial is a 404, not 403, so non-members
    can't enumerate firm UUIDs by probing for 403 vs 404 responses."""
    _set_current_user(monkeypatch, two_firms_two_users["admin_a_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get(f"/api/firms/{two_firms_two_users['firm_b']}/library")
        assert r.status_code == 404, r.text
    finally:
        _clear_current_user()


# ---------------------------------------------------------------------------
# 5. test_cross_firm_get_returns_404
# ---------------------------------------------------------------------------


async def test_cross_firm_get_returns_404(
    two_firms_two_users, monkeypatch, stub_embed
) -> None:
    # Admin B uploads to firm B.
    _set_current_user(monkeypatch, two_firms_two_users["admin_b_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await _upload_as(c, two_firms_two_users["firm_b"], title="FirmB-secret")
        assert r.status_code == 200
        cid = r.json()["firm_content"]["id"]
    finally:
        _clear_current_user()

    # Admin A tries to fetch the firm-B content row by its actual id —
    # should 404 (not "Firm content not found") because Firm A doesn't
    # have read access to Firm B at all.
    _set_current_user(monkeypatch, two_firms_two_users["admin_a_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get(f"/api/firms/{two_firms_two_users['firm_b']}/library/{cid}")
        assert r.status_code == 404, r.text
    finally:
        _clear_current_user()


# ---------------------------------------------------------------------------
# 6. test_audit_log_entry_on_upload
# ---------------------------------------------------------------------------


async def test_audit_log_entry_on_upload(
    two_firms_two_users, monkeypatch, stub_embed
) -> None:
    from db.connection import acquire

    _set_current_user(monkeypatch, two_firms_two_users["admin_a_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await _upload_as(c, two_firms_two_users["firm_a"], title="AuditUpload")
        assert r.status_code == 200, r.text
        cid = r.json()["firm_content"]["id"]
    finally:
        _clear_current_user()

    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT action, resource_id, payload FROM audit_events
            WHERE action = 'firm_library.upload'
              AND actor_user_id = $1::uuid
            ORDER BY created_at DESC LIMIT 5
            """,
            two_firms_two_users["admin_a"],
        )
    assert any(str(r["resource_id"]) == cid for r in rows), (
        f"no firm_library.upload audit row found for content_id={cid}"
    )
    matching = next(r for r in rows if str(r["resource_id"]) == cid)
    payload = matching["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    assert payload.get("firm_id") == two_firms_two_users["firm_a"]
    assert payload.get("title") == "AuditUpload"
    assert payload.get("category") == "playbook"
    assert isinstance(payload.get("chunks_written"), int)


# ---------------------------------------------------------------------------
# 7. test_audit_log_entry_on_unauthorized
# ---------------------------------------------------------------------------


async def test_audit_log_entry_on_unauthorized(
    two_firms_two_users, monkeypatch
) -> None:
    """Member of firm A pokes firm B's library list — endpoint returns
    404 AND a domain-level audit row is written so cross-firm probing is
    visible in the audit trail."""
    from db.connection import acquire

    _set_current_user(monkeypatch, two_firms_two_users["member_a_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get(f"/api/firms/{two_firms_two_users['firm_b']}/library")
        assert r.status_code == 404
    finally:
        _clear_current_user()

    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT action, payload FROM audit_events
            WHERE action = 'firm_library.list_unauthorized_attempt'
              AND actor_user_id = $1::uuid
            ORDER BY created_at DESC LIMIT 5
            """,
            two_firms_two_users["member_a"],
        )
    assert rows, "expected a list_unauthorized_attempt audit row"
    payload = rows[0]["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    assert payload.get("attempted_firm_id") == two_firms_two_users["firm_b"]


# ---------------------------------------------------------------------------
# Bonus — admin-unauthorized audit on member-tries-to-upload
# ---------------------------------------------------------------------------


async def test_audit_log_entry_on_member_upload_attempt(
    two_firms_two_users, monkeypatch
) -> None:
    """Membership check passes (member is in firm A); admin check fails;
    domain-level admin_unauthorized_attempt audit row recorded."""
    from db.connection import acquire

    _set_current_user(monkeypatch, two_firms_two_users["member_a_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await _upload_as(c, two_firms_two_users["firm_a"], title="should-fail")
        assert r.status_code == 403
    finally:
        _clear_current_user()

    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT action FROM audit_events
            WHERE action = 'firm_library.admin_unauthorized_attempt'
              AND actor_user_id = $1::uuid
            ORDER BY created_at DESC LIMIT 3
            """,
            two_firms_two_users["member_a"],
        )
    assert rows, "expected an admin_unauthorized_attempt audit row"
