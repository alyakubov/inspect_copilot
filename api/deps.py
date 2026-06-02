"""Request-scoped dependencies."""
from __future__ import annotations

from collections.abc import Iterator

from inspect_copilot.store import Store

from .config import DB, FAISS


def get_store() -> Iterator[Store]:
    """Open a Store per request and close its SQLite connection afterwards.

    The heavy singletons (embedding model, Anthropic client) live in the engine
    modules and load once at import; only the cheap SQLite+FAISS handles are
    per-request. Single-user tool, so this is simpler and safer than sharing one
    connection across threads.
    """
    store = Store(DB, FAISS)
    try:
        yield store
    finally:
        store.conn.close()
