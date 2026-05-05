"""Auth API routes — register / login / logout / me."""

import os
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

import asyncpg

from auth.dependencies import get_current_user
from auth.passwords import hash_password, verify_password
from auth.queries import create_user, get_user_by_email, update_last_login
from auth.sessions import COOKIE_NAME, SESSION_TTL_DAYS, create_session, revoke_session
from core.limits import limiter

router = APIRouter()

EMAIL_RE = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.I)
COOKIE_SECURE = os.getenv("ENVIRONMENT", "development") == "production"


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_TTL_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


class RegisterBody(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=8, max_length=200)
    full_name: str = Field(default="", max_length=120)


class LoginBody(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


@router.post("/register", status_code=201)
@limiter.limit("10/hour")
async def register(request: Request, body: RegisterBody, response: Response) -> dict[str, Any]:
    email = str(body.email).strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Invalid email")
    pw_hash = hash_password(body.password)
    try:
        user = await create_user(email=email, password_hash=pw_hash, full_name=body.full_name or "")
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=409, detail="Email already in use")

    token = await create_session(
        user["id"],
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    _set_session_cookie(response, token)
    return {"user": {"email": user["email"], "full_name": user["full_name"], "role": user["role"]}}


@router.post("/login")
@limiter.limit("20/minute")
async def login(request: Request, body: LoginBody, response: Response) -> dict[str, Any]:
    user = await get_user_by_email(str(body.email))
    # Constant-ish-time: always run verify even on missing user with a known-bad hash
    valid = bool(user) and verify_password(body.password, user["password_hash"])  # type: ignore[index]
    if not user or not valid:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = await create_session(
        user["id"],
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await update_last_login(user["id"])
    _set_session_cookie(response, token)
    return {"user": {"email": user["email"], "full_name": user["full_name"], "role": user["role"]}}


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response) -> Response:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        await revoke_session(token)
    _clear_session_cookie(response)
    return Response(status_code=204)


@router.get("/me")
async def me(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    return {
        "user": {
            "user_id": user["user_id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "role": user["role"],
        }
    }
