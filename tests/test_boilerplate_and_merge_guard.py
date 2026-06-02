"""Tests for the two safeguards against the child-care/Clinton mis-merge:

1. ingest._strip_boilerplate — publisher contact-block addresses (e.g. the OIG
   letterhead '1800 F Street NW') never reach extraction, while a genuine
   building address in body prose survives.
2. dedupe._geo_consistent — an LLM merge whose members geocode far apart is
   rejected; close or unverifiable groups are allowed.
"""
import os

# dedupe imports the Anthropic client at module load and requires a model name.
os.environ.setdefault("ANTHROPIC_MODEL", "test-model")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from inspect_copilot import dedupe  # noqa: E402
from inspect_copilot.ingest import _strip_boilerplate  # noqa: E402
from inspect_copilot.store import Store  # noqa: E402


def _store(tmp_path) -> Store:
    return Store(":memory:", str(tmp_path / "vectors.faiss"))


# --- boilerplate stripping -------------------------------------------------

def test_strip_removes_oig_contact_block_keeps_body_address():
    pages = [
        (3, "Roof slab shows corrosion at 200 Main St, Springfield, IL 62701.\n"
            "Severe spalling observed on the north facade."),
        (9, "OFFICE OF\nINSPECTOR GENERAL\nFor media inquiries\n"
            "OIG_PublicAffairs@gsaig.gov\n(202) 501-0450\n"
            "REPORT FRAUD, WASTE, AND ABUSE\n(800) 424-5210\nfraudnet@gsaig.gov\n"
            "www.gsaig.gov ●  1800 F Street NW, Washington, DC 20405"),
    ]
    out = dict(_strip_boilerplate(pages))

    # body page: a real building address and content are untouched
    assert "200 Main St, Springfield, IL 62701" in out[3]
    assert "spalling" in out[3]

    # contact page: the agency's own address and contact tokens are gone
    assert "1800 F Street NW" not in out[9]
    assert "gsaig.gov" not in out[9]
    assert "424-5210" not in out[9]


def test_strip_removes_running_footer_across_pages():
    footer = "GSA OIG Report JE99-001"
    pages = [(i, f"Body finding {i}: corrosion on beam.\n{footer}") for i in range(1, 6)]
    out = dict(_strip_boilerplate(pages))
    for i in range(1, 6):
        assert footer not in out[i]
        assert f"Body finding {i}" in out[i]


# --- geocode-verified merge guard ------------------------------------------

def test_haversine_dc_buildings_about_1km():
    # GSA HQ (1800 F St NW) vs Clinton Federal Building (Federal Triangle)
    d = dedupe._haversine_m(38.8970, -77.0426, 38.8940, -77.0288)
    assert 1000 < d < 1400


def test_guard_rejects_members_far_apart(tmp_path, monkeypatch):
    store = _store(tmp_path)
    a = store.get_or_create_building("GSA Headquarters Building")
    b = store.get_or_create_building("William Jefferson Clinton Federal Building")
    coords = {
        "GSA Headquarters Building": (38.8970, -77.0426, "US"),
        "William Jefferson Clinton Federal Building": (38.8940, -77.0288, "US"),
    }
    monkeypatch.setattr(dedupe, "geocode_address", lambda addr: coords.get(addr))
    assert dedupe._geo_consistent(store, [a, b]) is False


def test_guard_allows_members_same_place(tmp_path, monkeypatch):
    store = _store(tmp_path)
    a = store.get_or_create_building("Garmatz Courthouse")
    b = store.get_or_create_building("Edward A. Garmatz Federal Courthouse")
    monkeypatch.setattr(dedupe, "geocode_address", lambda addr: (39.2871, -76.6174, "US"))
    assert dedupe._geo_consistent(store, [a, b]) is True


def test_guard_allows_when_only_one_member_geocodes(tmp_path, monkeypatch):
    # function-alias case: 'Bankruptcy Courthouse' won't geocode on its own,
    # so there is no positive evidence to block the merge.
    store = _store(tmp_path)
    a = store.get_or_create_building("Garmatz Courthouse")
    b = store.get_or_create_building("Bankruptcy Courthouse")
    monkeypatch.setattr(
        dedupe, "geocode_address",
        lambda addr: (39.2871, -76.6174, "US") if "Garmatz" in addr else None,
    )
    assert dedupe._geo_consistent(store, [a, b]) is True


def test_guard_uses_stored_coords_without_geocoding(tmp_path, monkeypatch):
    store = _store(tmp_path)
    a = store.get_or_create_building("Building A")
    b = store.get_or_create_building("Building B")
    store.update_building_coords(a, 40.0000, -75.0000, "US")
    store.update_building_coords(b, 40.0500, -75.0000, "US")  # ~5.5 km away

    def _boom(addr):
        raise AssertionError("should not geocode when coords are stored")

    monkeypatch.setattr(dedupe, "geocode_address", _boom)
    assert dedupe._geo_consistent(store, [a, b]) is False


def test_guard_allows_single_member_group(tmp_path):
    store = _store(tmp_path)
    a = store.get_or_create_building("Lone Building")
    assert dedupe._geo_consistent(store, [a]) is True
