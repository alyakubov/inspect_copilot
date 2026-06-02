"""LLM-based semantic deduplication of extracted building references.

Some buildings appear under multiple names that string heuristics can't connect:
a court referred to by its formal building name in one chunk ("Garmatz Courthouse")
and by the court it houses in another ("Bankruptcy Courthouse") — both naming the
same Edward A. Garmatz Federal Courthouse in Baltimore. Only world knowledge of
US public buildings can collapse those into one.

We send the full list of extracted references for one PDF to the LLM and ask it
to group same-building references, returning a canonical official name for each.
Result is applied via Store.apply_canonical_merges(); failures (network, parsing)
leave the buildings table untouched so the pipeline continues normally.
"""

from __future__ import annotations

import json
import logging
import math
import os

from anthropic import Anthropic

from .geocode import geocode_address
from .store import Store

_log = logging.getLogger(__name__)

# A merge group is REJECTED when two or more of its members independently
# geocode to points farther apart than this. The LLM's world knowledge is a
# guess; an address that resolves a kilometre away is hard evidence the guess
# is wrong. 250 m comfortably covers a single large federal complex while still
# catching cross-town hallucinations (e.g. the GSA Headquarters Building at
# 1800 F St NW vs the William Jefferson Clinton Federal Building at the Federal
# Triangle, ~1 km apart, which an earlier run wrongly merged).
_MERGE_MAX_SPREAD_M = 250.0


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in metres."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _geo_consistent(store: Store, alias_ids: list[int]) -> bool:
    """True unless there is positive geographic evidence the members differ.

    For each member we use its stored coords if known, else geocode its
    raw_address independently. We REJECT (return False) only when at least two
    members resolve and the farthest pair exceeds _MERGE_MAX_SPREAD_M. When
    fewer than two members geocode we cannot disprove the merge, so we allow it
    — this preserves function-alias merges where one name doesn't geocode
    (e.g. 'Bankruptcy Courthouse' for the Garmatz courthouse).
    """
    if len(alias_ids) < 2:
        return True
    placeholders = ",".join("?" * len(alias_ids))
    rows = store.sql(
        f"SELECT building_id, raw_address, latitude, longitude "
        f"FROM buildings WHERE building_id IN ({placeholders})",
        tuple(alias_ids),
    )
    coords: list[tuple[float, float]] = []
    for r in rows:
        if r["latitude"] is not None and r["longitude"] is not None:
            coords.append((r["latitude"], r["longitude"]))
            continue
        geo = geocode_address(r["raw_address"])
        if geo is not None:
            coords.append((geo[0], geo[1]))
    if len(coords) < 2:
        return True
    spread = max(
        _haversine_m(*coords[i], *coords[j])
        for i in range(len(coords))
        for j in range(i + 1, len(coords))
    )
    return spread <= _MERGE_MAX_SPREAD_M

_CLIENT = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
_MODEL = os.environ.get("ANTHROPIC_MODEL")
if not _MODEL:
    raise RuntimeError(
        "ANTHROPIC_MODEL is not set. Define it in .env (see .env.example) "
        "or export it in your shell."
    )


SYSTEM = """You reconcile building references extracted from US public-building inspection reports.

You receive a JSON list of references, each with an id and the verbatim text the inspectors used. Some references may name the same physical building in different ways — typically a building referred to by both its formal name and the function or court it houses (e.g. "Garmatz Courthouse" and "Bankruptcy Courthouse" for the Edward A. Garmatz Federal Courthouse in Baltimore, which houses Maryland's U.S. Bankruptcy Court).

You produce TWO kinds of output:

1) MERGES — confident same-building groupings.
2) CONCERNS — references you want a human to review.

--- MERGES ---
For each group of ids that you are CONFIDENT refer to the same physical building, return a canonical address (full official name + city + state) and a one-sentence reason.

STRICT RULES for merges:
- Merge ONLY when you are confident based on verifiable knowledge of US public/federal buildings.
- DO NOT merge based on similar names alone. "Federal Building" + "Atlanta Federal Building" is NOT a merge — those are different buildings.
- DO NOT merge different buildings that happen to be in the same city.
- DO NOT merge if you are uncertain. Returning fewer merges is better than wrong merges.
- canonical_address must be geocodeable: full official name, city, and state (e.g. "Edward A. Garmatz Federal Courthouse, Baltimore, MD"). Prefer "Federal" over "U.S." in building names — Nominatim's tokenizer mishandles abbreviations with internal periods like "U.S." and the lookup will silently return no result.
- A merge group must contain at least 2 ids.

--- CONCERNS ---
Flag references whose extraction is risky. Two concern types:

(a) "ambiguous_name" — name alone is too generic to identify a specific building. Without explicit city/state, geocoding will land on an arbitrary one. Examples: "Federal Building", "Bankruptcy Courthouse", "Post Office", "Courthouse", "Annex". Always flag these.

(b) "possible_duplicate" — you suspected a reference might refer to the same building as another in the list, but you lack enough evidence to merge confidently. Surface it for human review. Include `possibly_same_as_id` pointing at the suspected sibling.

For concerns, be GENEROUS — when in doubt, flag it. A flag the user can dismiss is far cheaper than a silent wrong pin on a map.

--- OUTPUT ---
Return ONLY a JSON object of the form:
{
  "merges": [
    {"canonical_address": str, "alias_ids": [int, ...], "reasoning": str}
  ],
  "concerns": [
    {"building_id": int,
     "concern": "ambiguous_name" | "possible_duplicate",
     "reasoning": str,
     "possibly_same_as_id": int  /* only for possible_duplicate; omit otherwise */
    }
  ]
}
No prose, no code fences. Either list may be empty."""


def semantic_dedupe(store: Store) -> dict:
    """LLM dedup + concern pass.

    Returns {"merged": int, "concerns": int} — 0/0 on any failure (network,
    parse, etc.). Pipeline never fails because of this step.
    """
    rows = store.sql("SELECT building_id, raw_address FROM buildings ORDER BY building_id")
    if len(rows) < 2:
        return {"merged": 0, "concerns": 0}

    refs = [{"id": r["building_id"], "name": r["raw_address"]} for r in rows]

    try:
        msg = _CLIENT.messages.create(
            model=_MODEL,
            max_tokens=2000,
            system=SYSTEM,
            messages=[{
                "role": "user",
                "content": "Building references:\n" + json.dumps(refs, indent=2),
            }],
        )
        raw = "".join(b.text for b in msg.content if b.type == "text").strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw[raw.find("{"):]
        data = json.loads(raw)
    except Exception as e:  # noqa: BLE001 — never let semantic dedup break ingest
        _log.warning("semantic dedup LLM call failed: %s", e)
        return {"merged": 0, "concerns": 0}

    # Geographic verification: drop any LLM merge whose members independently
    # geocode far apart. Catches same-named-organisation hallucinations the
    # prompt can't be trusted to avoid. Rejections are logged, never silent.
    proposed = data.get("merges") or []
    verified = []
    for grp in proposed:
        if _geo_consistent(store, grp.get("alias_ids") or []):
            verified.append(grp)
        else:
            store.log(
                -1, "merge_rejected_geo",
                f"alias_ids={grp.get('alias_ids')} canonical={grp.get('canonical_address')!r} "
                f"reasoning={grp.get('reasoning','')!r}",
            )

    merged = store.apply_canonical_merges(verified)
    concerns = store.apply_concerns(data.get("concerns") or [])
    return {"merged": merged, "concerns": concerns, "rejected_geo": len(proposed) - len(verified)}
