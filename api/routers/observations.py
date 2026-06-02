"""Browse view endpoint: every observation + report-number index."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from inspect_copilot.store import Store

from ..auth import require_auth
from ..deps import get_store

router = APIRouter(prefix="/api", tags=["observations"], dependencies=[Depends(require_auth)])


@router.get("/observations")
def list_observations(store: Store = Depends(get_store)) -> dict:
    rows = store.sql(
        "SELECT source_file, page, defect_type, building_element, material, "
        "       severity, confidence, verbatim_quote FROM observations"
    )
    docs = store.sql("SELECT rowid AS report_id, source_file FROM documents ORDER BY rowid")
    return {
        "observations": [dict(r) for r in rows],
        # filename -> user-facing report number (same as Browse/Analytics IDs)
        "report_index": {d["source_file"]: d["report_id"] for d in docs},
    }
