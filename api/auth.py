"""Auth gate dependency.

Mirrors the Streamlit gate: if USER_LOGIN/USER_PASSWORD are unset, every route
is open; otherwise a valid session cookie is required.
"""
from __future__ import annotations

from fastapi import HTTPException, Request, status

from .config import auth_enabled


def require_auth(request: Request) -> None:
    if not auth_enabled():
        return
    if request.session.get("user"):
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )
