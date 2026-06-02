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
import os

from anthropic import Anthropic

from .store import Store

_log = logging.getLogger(__name__)

_CLIENT = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
_MODEL = os.environ.get("ANTHROPIC_MODEL")
if not _MODEL:
    raise RuntimeError(
        "ANTHROPIC_MODEL is not set. Define it in .env (see .env.example) "
        "or export it in your shell."
    )


SYSTEM = """You reconcile building references extracted from US public-building inspection reports.

You receive a JSON list of references, each with an id and the verbatim text the inspectors used. Some references may name the same physical building in different ways — typically a building referred to by both its formal name and the function or court it houses (e.g. "Garmatz Courthouse" and "Bankruptcy Courthouse" for the Edward A. Garmatz Federal Courthouse in Baltimore, which houses Maryland's U.S. Bankruptcy Court).

Task: identify groups of ids that refer to the same physical building, using verifiable knowledge of US federal/public buildings. For each group, return a canonical address (full official name + city + state) and a one-sentence reason.

STRICT RULES:
- Merge ONLY when you are confident the references identify the same physical building.
- DO NOT merge based on similar names alone. "Federal Building" + "Atlanta Federal Building" is NOT a merge — those are different buildings.
- DO NOT merge different buildings that happen to be in the same city.
- DO NOT merge if you are uncertain. Returning fewer merges is better than wrong merges.
- canonical_address must be specific enough to geocode: full official name, city, and state (e.g. "Edward A. Garmatz U.S. Courthouse, Baltimore, MD").
- A group must contain at least 2 ids.

Return ONLY a JSON object of the form:
{"merges": [{"canonical_address": str, "alias_ids": [int, ...], "reasoning": str}]}
No prose, no code fences. If no merges apply, return {"merges": []}."""


def semantic_dedupe(store: Store) -> int:
    """LLM dedup pass. Returns count of buildings merged away (0 on any failure)."""
    rows = store.sql("SELECT building_id, raw_address FROM buildings ORDER BY building_id")
    if len(rows) < 2:
        return 0

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
        return 0

    return store.apply_canonical_merges(data.get("merges") or [])
