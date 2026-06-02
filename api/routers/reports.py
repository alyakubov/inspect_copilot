"""Process view endpoints: list / upload / download / delete reports + log."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from inspect_copilot.pipeline import process_pdf
from inspect_copilot.store import Store

from ..auth import require_auth
from ..config import RAW_DIR, deletion_disabled
from ..deps import get_store

router = APIRouter(prefix="/api", tags=["reports"], dependencies=[Depends(require_auth)])


@router.get("/extraction-log")
def extraction_log(store: Store = Depends(get_store)) -> list[dict]:
    return [
        dict(r)
        for r in store.sql("SELECT status, COUNT(*) stats FROM extraction_log GROUP BY status")
    ]


@router.get("/reports")
def list_reports(store: Store = Depends(get_store)) -> list[dict]:
    rows = store.sql(
        "SELECT d.rowid AS report_id, d.source_file, d.n_pages, "
        "       (SELECT COUNT(*) FROM observations o WHERE o.source_file = d.source_file) AS n_obs "
        "FROM documents d ORDER BY d.rowid"
    )
    return [dict(r) for r in rows]


@router.post("/reports")
async def upload_report(
    file: UploadFile = File(...), store: Store = Depends(get_store)
) -> dict:
    name = file.filename or ""
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted.")
    # Feature: a processed report cannot be loaded a second time until deleted.
    if store.sql("SELECT 1 FROM documents WHERE source_file = ?", (name,)):
        raise HTTPException(
            status_code=409,
            detail=f"“{name}” has already been processed. Delete it before loading it again.",
        )
    Path(RAW_DIR).mkdir(parents=True, exist_ok=True)
    dest = Path(RAW_DIR) / name
    dest.write_bytes(await file.read())
    return process_pdf(dest, store)


@router.get("/reports/{report_id}/download")
def download_report(report_id: int, store: Store = Depends(get_store)) -> FileResponse:
    row = store.sql("SELECT source_file FROM documents WHERE rowid = ?", (report_id,))
    if not row:
        raise HTTPException(404, "Report not found.")
    src = row[0]["source_file"]
    path = Path(RAW_DIR) / src
    if not path.exists():
        raise HTTPException(404, "PDF file missing on disk.")
    return FileResponse(path, media_type="application/pdf", filename=src)


@router.delete("/reports/{report_id}")
def delete_report(report_id: int, store: Store = Depends(get_store)) -> dict:
    # Feature: NO_DELETE_REPORT=true blocks deletion (the button still exists).
    if deletion_disabled():
        raise HTTPException(
            status_code=403,
            detail="Report deletion is disabled (NO_DELETE_REPORT=true).",
        )
    row = store.sql("SELECT source_file FROM documents WHERE rowid = ?", (report_id,))
    if not row:
        raise HTTPException(404, "Report not found.")
    src = row[0]["source_file"]
    stats = store.delete_report(src)
    path = Path(RAW_DIR) / src
    if path.exists():
        path.unlink()
    return stats
