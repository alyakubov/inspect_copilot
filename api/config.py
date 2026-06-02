"""API configuration, read from the same .env the engine uses.

All knobs are environment-driven so the API mirrors the old Streamlit app's
behaviour 1:1 (login gate, deletion lock, Cesium token).
"""
from __future__ import annotations

import os

DB = os.environ.get("INSPECT_DB", "data/db/inspect_copilot.sqlite")
FAISS = os.environ.get("INSPECT_FAISS", "data/db/vectors.faiss")
RAW_DIR = os.environ.get("INSPECT_RAW_DIR", "data/raw")

# Cookie-session signing key. Override in production via .env.
SESSION_SECRET = os.environ.get("SESSION_SECRET", "dev-insecure-secret-change-me")


def auth_enabled() -> bool:
    """Login is required only when BOTH credentials are configured."""
    return bool(os.environ.get("USER_LOGIN") and os.environ.get("USER_PASSWORD"))


def check_credentials(username: str, password: str) -> bool:
    return (
        username == os.environ.get("USER_LOGIN")
        and password == os.environ.get("USER_PASSWORD")
    )


def deletion_disabled() -> bool:
    return os.environ.get("NO_DELETE_REPORT", "").strip().lower() == "true"


def cesium_token_present() -> bool:
    return bool(os.environ.get("CESIUM_ION_TOKEN"))
