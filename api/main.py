"""FastAPI app for InspectCopilot — serves the React SPA and the JSON API.

Run (dev):   uvicorn api.main:app --reload --port 8000
Run (prod):  build the SPA (cd frontend && npm run build), then run uvicorn;
             this module serves frontend/dist at the root.
"""
from __future__ import annotations

# load_dotenv MUST run before importing the engine modules — extract/query/
# dedupe/pipeline construct the Anthropic client and read ANTHROPIC_MODEL at
# import time.
from dotenv import load_dotenv

load_dotenv()

from pathlib import Path  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from starlette.middleware.sessions import SessionMiddleware  # noqa: E402

from .config import SESSION_SECRET  # noqa: E402
from .routers import analytics, ask, buildings, observations, reports, system  # noqa: E402

app = FastAPI(title="InspectCopilot API")

# Signed cookie session (used by the optional login gate).
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site="lax")
# Allow the Vite dev server to call the API with credentials during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (system, reports, buildings, observations, analytics, ask):
    app.include_router(r.router)


# --- serve the built SPA in production (no-op in dev where Vite serves it) ---
_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        # Anything not handled by an /api route or /assets falls back to the SPA
        # entry point so client-side routing works on refresh/deep links.
        if full_path.startswith("api/"):
            return FileResponse(_DIST / "index.html", status_code=404)
        candidate = _DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_DIST / "index.html")
