"""The pipeline: one walk over each PDF builds BOTH indexes.

    for each PDF:
        chunks, ocr = ingest(pdf)            # text layer + OCR fallback
        for chunk in chunks:
            store raw chunk text             -> SQLite (chunks)
            observations = llm_extract(chunk) -> SQLite (observations)   [Index 1]
            vector = embed(chunk.text)        -> FAISS                   [Index 2]

Index 1 (structured rows) answers count/group/filter/rank via SQL — exact,
over all data. Index 2 (vectors) answers fuzzy semantic follow-ups via retrieval.
Both built once, upfront, per the design we agreed on.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from .ingest import ingest
from .extract import extract
from .dedupe import semantic_dedupe
from .embedding import embed
from .geocode import geocode_pending
from .store import Store


def process_pdf(pdf_path: str | Path, store: Store) -> dict:
    pdf_path = Path(pdf_path)
    chunks, ocr_used = ingest(pdf_path)
    doc_lang = chunks[0].language if chunks else "unknown"
    store.add_document(pdf_path.name, n_pages=len(chunks), ocr_used=ocr_used, language=doc_lang)

    n_obs = 0
    for ch in chunks:
        chunk_id = store.add_chunk(pdf_path.name, ch.page, ch.language, ch.text)

        # Index 2: embedding (always succeeds, local)
        vec = embed(ch.text)
        store.add_vector(chunk_id, vec)

        # Index 1: structured extraction (validated; failures quarantined)
        try:
            result = extract(pdf_path.name, ch.page, ch.language, ch.text)
            addr_to_id = {
                addr: store.get_or_create_building(addr)
                for addr in {o.building_address for o in result.observations if o.building_address}
            }
            store.add_observations(chunk_id, pdf_path.name, ch.page, result.observations, addr_to_id)
            store.log(chunk_id, "ok", f"{len(result.observations)} observations")
            n_obs += len(result.observations)
        except (ValidationError, ValueError) as e:
            store.log(chunk_id, "validation_error", str(e)[:500])
        except Exception as e:  # noqa: BLE001 — log everything, drop nothing silently
            store.log(chunk_id, "llm_error", str(e)[:500])

    store.save_vectors()

    # Three dedup passes + geocoding, in order of how much context each can use:
    #   1. semantic dedup (LLM) — collapses same-building references that differ
    #      arbitrarily (e.g. 'Garmatz Courthouse' + 'Bankruptcy Courthouse'); uses
    #      world knowledge of US public buildings and writes a canonical_address.
    #      Each proposed merge is geo-verified confirm-only: members are
    #      geocoded (anchored to the canonical city/state) and only those that
    #      cluster within ~250m are merged, so a confident-but-wrong LLM guess
    #      can't fuse two different buildings.
    #   2. geocode — runs on canonical_address when set, raw_address otherwise.
    #   3. coord-based merge — for buildings the LLM missed but that geocoded to
    #      the same lat/lon.
    #   4. name-based merge — string-similarity safety net.
    # All best-effort; none can fail the pipeline.
    sem = semantic_dedupe(store)
    geo = geocode_pending(store)
    merged_by_coord = store.merge_duplicate_buildings()
    merged_by_name = store.merge_similar_named_buildings()

    return {
        "file": pdf_path.name,
        "chunks": len(chunks),
        "ocr_used": ocr_used,
        "observations": n_obs,
        "geocoded": f"{geo['resolved']}/{geo['attempted']}",
        "buildings_merged": sem["merged"] + merged_by_coord + merged_by_name,
        "buildings_flagged": sem["concerns"],
        "merges_rejected_geo": sem.get("rejected_geo", 0),
    }


def process_folder(folder: str | Path, store: Store) -> list[dict]:
    return [process_pdf(p, store) for p in sorted(Path(folder).glob("*.pdf"))]
