"""Phase 2 / Week 6 / Day 2 — firm-mode admin API tests.

Hits the FastAPI app via httpx.AsyncClient + ASGITransport so the full
middleware + dependency chain runs. Auth is bypassed by overriding
``get_current_user`` per test (same pattern as Week 5 firm_library tests).
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


@pytest.fixture(autouse=True)
def _resolver_cache_reset():
    """Each test starts with an empty resolver cache so cached
    resolutions from a prior test never leak across boundaries."""
    from core.consulting_modes import resolver as resolver_mod

    resolver_mod._cache_clear()
    yield
    resolver_mod._cache_clear()


def _user_dict(user_id: str, email: str) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "email": email,
        "full_name": email.split("@")[0],
        "role": "member",
    }


@pytest.fixture
async def two_firms_two_users():
    """Two firms with admin + member each. Cleans up firm_modes /
    audit_events / firm_memberships / users / firms on teardown."""
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
            firm_a, f"FA {firm_a[:6]}", f"fa-{firm_a[:8]}",
            firm_b, f"FB {firm_b[:6]}", f"fb-{firm_b[:8]}",
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
            "firm_a": firm_a,
            "firm_b": firm_b,
            "admin_a_user": _user_dict(admin_a, f"admin-a-{firm_a[:8]}@test.argus.invalid"),
            "member_a_user": _user_dict(member_a, f"mem-a-{firm_a[:8]}@test.argus.invalid"),
            "admin_b_user": _user_dict(admin_b, f"admin-b-{firm_b[:8]}@test.argus.invalid"),
        }
    finally:
        async with acquire() as conn:
            uids = (admin_a, member_a, admin_b, member_b)
            fids = (firm_a, firm_b)
            await conn.execute(
                "DELETE FROM firm_modes WHERE firm_id = ANY($1::uuid[])", list(fids)
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
    async def _stub() -> dict[str, Any]:
        return user

    app.dependency_overrides[auth_dep.get_current_user] = _stub


def _clear_current_user() -> None:
    app.dependency_overrides.pop(auth_dep.get_current_user, None)


# ---------------------------------------------------------------------------
# 1. test_admin_creates_firm_mode
# ---------------------------------------------------------------------------


async def test_admin_creates_firm_mode(two_firms_two_users, monkeypatch) -> None:
    _set_current_user(monkeypatch, two_firms_two_users["admin_a_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post(
                f"/api/firms/{two_firms_two_users['firm_a']}/modes",
                json={
                    "name": "ma_screen",
                    "base_mode": "due_diligence",
                    "config": {
                        "display_name": "M&A Screen — Firm A",
                        "writer_overlay": "Lead with target list.",
                    },
                },
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["firm_mode"]["name"] == "ma_screen"
        assert body["firm_mode"]["base_mode"] == "due_diligence"
        assert body["firm_mode"]["retired_at"] is None

        # Audit row written.
        from db.connection import acquire
        async with acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT action, payload FROM audit_events
                WHERE action = 'firm_modes.create'
                  AND actor_user_id = $1::uuid
                """,
                two_firms_two_users["admin_a_user"]["user_id"],
            )
        assert rows, "expected firm_modes.create audit row"
        payload = rows[0]["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        assert payload["mode_name"] == "ma_screen"
        assert payload["base_mode"] == "due_diligence"
        assert "display_name" in payload["config_keys"]
    finally:
        _clear_current_user()


# ---------------------------------------------------------------------------
# 2. test_member_cannot_create
# ---------------------------------------------------------------------------


async def test_member_cannot_create(two_firms_two_users, monkeypatch) -> None:
    _set_current_user(monkeypatch, two_firms_two_users["member_a_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post(
                f"/api/firms/{two_firms_two_users['firm_a']}/modes",
                json={"name": "ma_screen", "config": {}},
            )
        assert r.status_code == 403, r.text
    finally:
        _clear_current_user()


# ---------------------------------------------------------------------------
# 3. test_cross_firm_create_returns_404
# ---------------------------------------------------------------------------


async def test_cross_firm_create_returns_404(two_firms_two_users, monkeypatch) -> None:
    """Admin of firm A tries to create in firm B; 404 (anti-enumeration);
    audit log records the unauthorized attempt with action
    firm_modes.list_unauthorized_attempt."""
    _set_current_user(monkeypatch, two_firms_two_users["admin_a_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post(
                f"/api/firms/{two_firms_two_users['firm_b']}/modes",
                json={"name": "ma_screen", "config": {}},
            )
        assert r.status_code == 404, r.text

        from db.connection import acquire
        async with acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT action FROM audit_events
                WHERE action = 'firm_modes.list_unauthorized_attempt'
                  AND actor_user_id = $1::uuid
                """,
                two_firms_two_users["admin_a_user"]["user_id"],
            )
        assert rows, "expected list_unauthorized_attempt audit row"
    finally:
        _clear_current_user()


# ---------------------------------------------------------------------------
# 4. test_invalid_name_rejected
# ---------------------------------------------------------------------------


async def test_invalid_name_rejected(two_firms_two_users, monkeypatch) -> None:
    _set_current_user(monkeypatch, two_firms_two_users["admin_a_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post(
                f"/api/firms/{two_firms_two_users['firm_a']}/modes",
                json={"name": "My Mode!", "config": {}},
            )
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert detail["error"] == "invalid_mode_config"
        assert "My Mode!" in detail["message"]
    finally:
        _clear_current_user()


# ---------------------------------------------------------------------------
# 5. test_overlay_too_long_rejected
# ---------------------------------------------------------------------------


async def test_overlay_too_long_rejected(two_firms_two_users, monkeypatch) -> None:
    _set_current_user(monkeypatch, two_firms_two_users["admin_a_user"])
    big = "x" * 5000
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post(
                f"/api/firms/{two_firms_two_users['firm_a']}/modes",
                json={"name": "big_overlay", "config": {"writer_overlay": big}},
            )
        assert r.status_code == 400, r.text
        assert "writer_overlay" in r.json()["detail"]["message"]
    finally:
        _clear_current_user()


# ---------------------------------------------------------------------------
# 6. test_unknown_base_mode_rejected
# ---------------------------------------------------------------------------


async def test_unknown_base_mode_rejected(two_firms_two_users, monkeypatch) -> None:
    _set_current_user(monkeypatch, two_firms_two_users["admin_a_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post(
                f"/api/firms/{two_firms_two_users['firm_a']}/modes",
                json={
                    "name": "weird_mode",
                    "base_mode": "does_not_exist",
                    "config": {},
                },
            )
        assert r.status_code == 400, r.text
        assert "does_not_exist" in r.json()["detail"]["message"]
    finally:
        _clear_current_user()


# ---------------------------------------------------------------------------
# 7. test_retire_falls_through_to_builtin
# ---------------------------------------------------------------------------


async def test_retire_falls_through_to_builtin(
    two_firms_two_users, monkeypatch
) -> None:
    """Create override on top of built-in, retire it, confirm subsequent
    resolution returns the built-in (no firm layer in provenance)."""
    from core.consulting_modes import resolve_mode

    _set_current_user(monkeypatch, two_firms_two_users["admin_a_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post(
                f"/api/firms/{two_firms_two_users['firm_a']}/modes",
                json={
                    "name": "market_entry",
                    "base_mode": "market_entry",
                    "config": {"display_name": "Firm A Market Entry"},
                },
            )
            assert r.status_code == 200, r.text

            # Resolution sees the override.
            m = await resolve_mode("market_entry", firm_id=two_firms_two_users["firm_a"])
            assert m.display_name == "Firm A Market Entry"
            assert m.layer_provenance["display_name"] == "firm"

            r = await c.post(
                f"/api/firms/{two_firms_two_users['firm_a']}/modes/market_entry/retire"
            )
            assert r.status_code == 200, r.text
            assert r.json()["firm_mode"]["retired_at"] is not None

        # After retire, resolution falls through to built-in.
        m2 = await resolve_mode("market_entry", firm_id=two_firms_two_users["firm_a"])
        assert m2.display_name == "Market entry"  # built-in YAML label
        assert m2.layer_provenance["display_name"] == "built_in"
    finally:
        _clear_current_user()


# ---------------------------------------------------------------------------
# 8. test_update_invalidates_cache
# ---------------------------------------------------------------------------


async def test_update_invalidates_cache(two_firms_two_users, monkeypatch) -> None:
    from core.consulting_modes import resolve_mode

    _set_current_user(monkeypatch, two_firms_two_users["admin_a_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            await c.post(
                f"/api/firms/{two_firms_two_users['firm_a']}/modes",
                json={
                    "name": "growth_strategy",
                    "base_mode": "growth_strategy",
                    "config": {"display_name": "v1"},
                },
            )
            # Resolve once -> caches v1.
            m1 = await resolve_mode(
                "growth_strategy", firm_id=two_firms_two_users["firm_a"]
            )
            assert m1.display_name == "v1"

            # Update -> service layer must invalidate the cache.
            r = await c.patch(
                f"/api/firms/{two_firms_two_users['firm_a']}/modes/growth_strategy",
                json={"config": {"display_name": "v2"}},
            )
            assert r.status_code == 200, r.text

            # Next resolution must see v2 (not the cached v1).
            m2 = await resolve_mode(
                "growth_strategy", firm_id=two_firms_two_users["firm_a"]
            )
            assert m2.display_name == "v2"
    finally:
        _clear_current_user()


# ---------------------------------------------------------------------------
# 9. test_list_includes_builtin_and_overrides
# ---------------------------------------------------------------------------


async def test_list_includes_builtin_and_overrides(
    two_firms_two_users, monkeypatch
) -> None:
    """List returns the union of built-ins (each marked is_builtin=true)
    and any firm-only modes (is_builtin=false). A firm override of a
    built-in shows up under the built-in row with has_firm_override=true.
    """
    _set_current_user(monkeypatch, two_firms_two_users["admin_a_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            # Override an existing built-in.
            await c.post(
                f"/api/firms/{two_firms_two_users['firm_a']}/modes",
                json={
                    "name": "market_entry",
                    "base_mode": "market_entry",
                    "config": {"display_name": "Firm A ME"},
                },
            )
            # Define a new firm-only mode.
            await c.post(
                f"/api/firms/{two_firms_two_users['firm_a']}/modes",
                json={
                    "name": "firm_a_pivot_review",
                    "config": {"display_name": "Pivot review (firm-only)"},
                },
            )

            r = await c.get(f"/api/firms/{two_firms_two_users['firm_a']}/modes")
            assert r.status_code == 200, r.text
            modes = r.json()["modes"]
            by_name = {m["name"]: m for m in modes}

            # Built-in market_entry is present with has_firm_override=True.
            assert by_name["market_entry"]["is_builtin"] is True
            assert by_name["market_entry"]["has_firm_override"] is True
            # Firm-only mode is present, not flagged built-in.
            assert by_name["firm_a_pivot_review"]["is_builtin"] is False
            assert by_name["firm_a_pivot_review"]["has_firm_override"] is True
            # Some other built-in (e.g. "general") is present without override.
            assert by_name["general"]["is_builtin"] is True
            assert by_name["general"]["has_firm_override"] is False
    finally:
        _clear_current_user()
