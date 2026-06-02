"""Config + auth endpoints (always open, so the SPA can bootstrap and log in)."""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..config import auth_enabled, check_credentials, deletion_disabled

router = APIRouter(prefix="/api", tags=["system"])


class LoginIn(BaseModel):
    username: str
    password: str


@router.get("/config")
def get_config(request: Request) -> dict:
    """Bootstrap info for the SPA: whether to show login, feature flags, token."""
    return {
        "auth_required": auth_enabled(),
        "authenticated": (not auth_enabled()) or bool(request.session.get("user")),
        "no_delete_report": deletion_disabled(),
        "cesium_token_present": bool(os.environ.get("CESIUM_ION_TOKEN")),
    }


@router.post("/login")
def login(body: LoginIn, request: Request) -> dict:
    if not auth_enabled():
        return {"authenticated": True}
    if check_credentials(body.username, body.password):
        request.session["user"] = body.username
        return {"authenticated": True}
    raise HTTPException(status_code=401, detail="Invalid username or password")


@router.post("/logout")
def logout(request: Request) -> dict:
    request.session.clear()
    return {"authenticated": False}
