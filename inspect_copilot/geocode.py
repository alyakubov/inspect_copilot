"""Nominatim geocoder: raw_address -> (latitude, longitude, country_code).

Single source of geocoding for the project. Wraps geopy's Nominatim with a
custom User-Agent (Nominatim policy requires a meaningful one) and respects the
1 req/sec public-server rate limit. Failures are tolerated — addresses that
can't be resolved leave the building's lat/lon as NULL and will be retried on
the next pipeline run.
"""

from __future__ import annotations

import logging

from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter

from .store import Store

_log = logging.getLogger(__name__)

_USER_AGENT = "inspect_copilot/0.1 (https://github.com/alyakubov/inspect_copilot)"

_geocoder = Nominatim(user_agent=_USER_AGENT)
# RateLimiter enforces Nominatim's 1 req/sec policy and backs off on transient errors.
_rate_limited_geocode = RateLimiter(_geocoder.geocode, min_delay_seconds=1.0)


def geocode_pending(store: Store) -> dict:
    """Fill lat/lon/country for buildings where latitude is NULL.

    Returns {"attempted": N, "resolved": K}. K can be < N when an address
    fails to resolve; those rows stay NULL for a future retry.
    """
    # Use the LLM-resolved canonical_address when set — it's more specific and
    # geocodes better than the as-extracted raw_address.
    rows = store.sql(
        "SELECT building_id, COALESCE(canonical_address, raw_address) AS address "
        "FROM buildings WHERE latitude IS NULL"
    )
    attempted = 0
    resolved = 0
    for r in rows:
        attempted += 1
        try:
            # country_codes biases Nominatim to US results — matches the MVP scope
            # (US public buildings). Drop or extend (e.g. ["us","be","nl","fr"]) to
            # geocode reports from other countries.
            loc = _rate_limited_geocode(
                r["address"],
                addressdetails=True,
                country_codes=["us"],
                timeout=10,
            )
        except Exception as e:  # noqa: BLE001 — never let geocoding break ingest
            _log.warning("geocoding failed for %r: %s", r["address"], e)
            continue
        if loc is None:
            continue
        country = (loc.raw.get("address") or {}).get("country_code")
        store.update_building_coords(
            building_id=r["building_id"],
            latitude=loc.latitude,
            longitude=loc.longitude,
            country=country.upper() if country else None,
        )
        resolved += 1
    return {"attempted": attempted, "resolved": resolved}
