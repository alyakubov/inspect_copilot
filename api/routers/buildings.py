"""Buildings view endpoints: list / defects / dismiss / edit+regeocode / merge / 3D."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from inspect_copilot.cesium import viewer_html
from inspect_copilot.geocode import geocode_pending
from inspect_copilot.store import Store

from ..auth import require_auth
from ..deps import get_store

router = APIRouter(prefix="/api", tags=["buildings"], dependencies=[Depends(require_auth)])


@router.get("/buildings")
def list_buildings(store: Store = Depends(get_store)) -> list[dict]:
    rows = store.sql(
        "SELECT b.building_id, "
        "       COALESCE(b.canonical_address, b.raw_address) AS display_name, "
        "       b.raw_address, b.canonical_address, b.flag, b.flag_reasoning, "
        "       b.possibly_same_as_building_id, b.latitude, b.longitude, b.country, "
        "       COUNT(o.obs_id) AS n_obs "
        "FROM buildings b LEFT JOIN observations o ON o.building_id = b.building_id "
        "GROUP BY b.building_id ORDER BY n_obs DESC, b.building_id"
    )
    return [dict(r) for r in rows]


@router.get("/buildings/{building_id}/observations")
def building_observations(building_id: int, store: Store = Depends(get_store)) -> list[dict]:
    rows = store.sql(
        "SELECT page, defect_type, building_element, material, severity, confidence, verbatim_quote "
        "FROM observations WHERE building_id = ? ORDER BY page",
        (building_id,),
    )
    return [dict(r) for r in rows]


@router.post("/buildings/{building_id}/dismiss-flag")
def dismiss_flag(building_id: int, store: Store = Depends(get_store)) -> dict:
    store.dismiss_flag(building_id)
    return {"ok": True}


class CanonicalIn(BaseModel):
    canonical_address: str


@router.put("/buildings/{building_id}/canonical")
def set_canonical(
    building_id: int, body: CanonicalIn, store: Store = Depends(get_store)
) -> dict:
    store.update_canonical_address(building_id, body.canonical_address)
    geocode_pending(store)  # re-resolve coords from the corrected address
    return {"ok": True}


class MergeIn(BaseModel):
    target_id: int  # survivor; this building (path param) is merged into it


@router.post("/buildings/{building_id}/merge")
def merge_building(
    building_id: int, body: MergeIn, store: Store = Depends(get_store)
) -> dict:
    if body.target_id == building_id:
        raise HTTPException(400, "Cannot merge a building into itself.")
    store.manual_merge(body.target_id, building_id)
    return {"ok": True}


@router.get("/buildings/{building_id}/cesium", response_class=HTMLResponse)
def cesium_view(building_id: int, store: Store = Depends(get_store)) -> HTMLResponse:
    row = store.sql(
        "SELECT COALESCE(canonical_address, raw_address) AS name, latitude, longitude "
        "FROM buildings WHERE building_id = ?",
        (building_id,),
    )
    if not row or row[0]["latitude"] is None:
        return HTMLResponse(
            "<div style='padding:1em;font-family:sans-serif'>No coordinates for this building.</div>"
        )
    r = row[0]
    return HTMLResponse(viewer_html(r["latitude"], r["longitude"], r["name"]))
