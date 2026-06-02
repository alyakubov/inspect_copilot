"""Analytics view endpoints: exact SQL aggregations (defect freq + severity)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from inspect_copilot import query
from inspect_copilot.store import Store

from ..auth import require_auth
from ..deps import get_store

router = APIRouter(prefix="/api", tags=["analytics"], dependencies=[Depends(require_auth)])


@router.get("/analytics/top-defects")
def top_defects(
    reports: list[str] = Query(default=[]),
    buildings: list[int] = Query(default=[]),
    limit: int = 10,
    store: Store = Depends(get_store),
) -> list[dict]:
    return query.top_defect_types(
        store,
        source_files=reports or None,
        building_ids=buildings or None,
        limit=limit,
    )


@router.get("/analytics/severity")
def severity(
    reports: list[str] = Query(default=[]),
    buildings: list[int] = Query(default=[]),
    store: Store = Depends(get_store),
) -> list[dict]:
    return query.severity_breakdown(
        store,
        source_files=reports or None,
        building_ids=buildings or None,
    )
