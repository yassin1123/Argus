"""DB queries for users."""

from __future__ import annotations

from typing import Any

from db.connection import acquire


async def create_user(email: str, password_hash: str, full_name: str = "", role: str = "member") -> dict[str, Any]:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO users (email, password_hash, full_name, role)
            VALUES ($1, $2, $3, $4)
            RETURNING id, email, full_name, role, created_at
            """,
            email.strip().lower(),
            password_hash,
            full_name.strip()[:200],
            role,
        )
    return {
        "id": str(row["id"]),
        "email": row["email"],
        "full_name": row["full_name"] or "",
        "role": row["role"] or "member",
    }


async def get_user_by_email(email: str) -> dict[str, Any] | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, email, password_hash, full_name, role
            FROM users WHERE email = $1
            """,
            email.strip().lower(),
        )
    if not row:
        return None
    return {
        "id": str(row["id"]),
        "email": row["email"],
        "password_hash": row["password_hash"],
        "full_name": row["full_name"] or "",
        "role": row["role"] or "member",
    }


async def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, email, full_name, role FROM users WHERE id = $1::uuid",
            user_id,
        )
    if not row:
        return None
    return {
        "id": str(row["id"]),
        "email": row["email"],
        "full_name": row["full_name"] or "",
        "role": row["role"] or "member",
    }


async def update_last_login(user_id: str) -> None:
    async with acquire() as conn:
        await conn.execute("UPDATE users SET last_login_at = NOW() WHERE id = $1::uuid", user_id)
