"""Tests for the two safeguards against the child-care/Clinton mis-merge:

1. ingest._strip_boilerplate — publisher contact-block addresses (e.g. the OIG
   letterhead '1800 F Street NW') never reach extraction, while a genuine
   building address in body prose survives.
2. dedupe._confirm_merge_members — region-anchored confirm-only: a merge is
   applied only for the subset of members that geocode into one ~250m cluster;
   un-geocodable members are dropped and unconfirmed groups are skipped.
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


# --- geocode-verified merge guard (region-anchored, confirm-only) ----------

def _fake_geo(addr: str):
    """Stand-in for Nominatim. Mimics the real failure modes we measured:
    'Garmatz'/'Clinton' resolve (to Baltimore / DC), everything else — bare
    'GSA Headquarters Building', 'Child Care Center', 'Wing 0' — is unresolvable.
    """
    a = addr.lower()
    if "garmatz" in a:
        return (39.2871, -76.6174, "US")   # Baltimore
    if "clinton" in a:
        return (38.8940, -77.0288, "US")   # DC, Federal Triangle
    return None


def test_haversine_dc_buildings_about_1km():
    # GSA HQ (1800 F St NW) vs Clinton Federal Building (Federal Triangle)
    d = dedupe._haversine_m(38.8970, -77.0426, 38.8940, -77.0288)
    assert 1000 < d < 1400


def test_anchor_region():
    assert dedupe._anchor_region("Edward A. Garmatz Federal Courthouse, Baltimore, MD") == "Baltimore, MD"
    assert dedupe._anchor_region("") == ""


def test_confirms_building_with_its_own_alias(tmp_path, monkeypatch):
    # 'Clinton Building' is anchored to DC and resolves to the same spot as the
    # full name -> both confirmed and merged.
    store = _store(tmp_path)
    a = store.get_or_create_building("William Jefferson Clinton Federal Building, Washington, DC")
    b = store.get_or_create_building("Clinton Building")
    monkeypatch.setattr(dedupe, "geocode_address", _fake_geo)
    confirmed = dedupe._confirm_merge_members(
        store, [a, b], "William Jefferson Clinton Federal Building, Washington, DC")
    assert set(confirmed) == {a, b}


def test_drops_ungeocodable_member_no_merge(tmp_path, monkeypatch):
    # The actual bug: GSA HQ won't geocode, so it can't be confirmed at Clinton's
    # location -> fewer than two confirm -> nothing merges.
    store = _store(tmp_path)
    a = store.get_or_create_building("William Jefferson Clinton Federal Building, Washington, DC")
    gsa = store.get_or_create_building("GSA Headquarters Building")
    monkeypatch.setattr(dedupe, "geocode_address", _fake_geo)
    assert dedupe._confirm_merge_members(
        store, [a, gsa], "William Jefferson Clinton Federal Building, Washington, DC") == []


def test_partial_keeps_only_confirmed_cluster(tmp_path, monkeypatch):
    # Mixed group: the two Clinton refs confirm; the un-geocodable GSA HQ ref is
    # dropped from the merge.
    store = _store(tmp_path)
    a = store.get_or_create_building("William Jefferson Clinton Federal Building, Washington, DC")
    b = store.get_or_create_building("Clinton Building")
    gsa = store.get_or_create_building("GSA Headquarters Building")
    monkeypatch.setattr(dedupe, "geocode_address", _fake_geo)
    confirmed = dedupe._confirm_merge_members(
        store, [a, b, gsa], "William Jefferson Clinton Federal Building, Washington, DC")
    assert set(confirmed) == {a, b}


def test_rejects_two_different_buildings(tmp_path, monkeypatch):
    # Even if the LLM proposes it, a DC building and a Baltimore building never
    # cluster -> no confirmed pair.
    store = _store(tmp_path)
    a = store.get_or_create_building("Clinton Building")
    b = store.get_or_create_building("Garmatz Courthouse")
    monkeypatch.setattr(dedupe, "geocode_address", _fake_geo)
    assert dedupe._confirm_merge_members(
        store, [a, b], "William Jefferson Clinton Federal Building, Washington, DC") == []


def test_confirm_uses_stored_coords_without_geocoding(tmp_path, monkeypatch):
    store = _store(tmp_path)
    a = store.get_or_create_building("Building A")
    b = store.get_or_create_building("Building B")
    store.update_building_coords(a, 40.00000, -75.0, "US")
    store.update_building_coords(b, 40.00100, -75.0, "US")  # ~111 m apart -> same cluster

    def _boom(addr):
        raise AssertionError("should not geocode when coords are stored")

    monkeypatch.setattr(dedupe, "geocode_address", _boom)
    assert set(dedupe._confirm_merge_members(store, [a, b], "X, City, ST")) == {a, b}


def test_confirm_single_member_group_returns_empty(tmp_path):
    store = _store(tmp_path)
    a = store.get_or_create_building("Lone Building")
    assert dedupe._confirm_merge_members(store, [a], "Lone Building, City, ST") == []
