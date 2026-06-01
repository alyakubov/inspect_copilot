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

from sentence_transformers import SentenceTransformer
from pydantic import ValidationError

from .ingest import ingest
from .extract import extract
from .store import Store

_EMBEDDER = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")  # 384-dim, free, local


def process_pdf(pdf_path: str | Path, store: Store) -> dict:
    pdf_path = Path(pdf_path)
    chunks, ocr_used = ingest(pdf_path)
    doc_lang = chunks[0].language if chunks else "unknown"
    store.add_document(pdf_path.name, n_pages=len(chunks), ocr_used=ocr_used, language=doc_lang)

    n_obs = 0
    for ch in chunks:
        chunk_id = store.add_chunk(pdf_path.name, ch.page, ch.language, ch.text)

        # Index 2: embedding (always succeeds, cheap, local)
        vec = _EMBEDDER.encode(ch.text)
        store.add_vector(chunk_id, vec)

        # Index 1: structured extraction (validated; failures quarantined)
        try:
            result = extract(pdf_path.name, ch.page, ch.language, ch.text)
            store.add_observations(chunk_id, pdf_path.name, ch.page, result.observations)
            store.log(chunk_id, "ok", f"{len(result.observations)} observations")
            n_obs += len(result.observations)
        except (ValidationError, ValueError) as e:
            store.log(chunk_id, "validation_error", str(e)[:500])
        except Exception as e:  # noqa: BLE001 — log everything, drop nothing silently
            store.log(chunk_id, "llm_error", str(e)[:500])

    store.save_vectors()
    return {"file": pdf_path.name, "chunks": len(chunks), "ocr_used": ocr_used, "observations": n_obs}


def process_folder(folder: str | Path, store: Store) -> list[dict]:
    return [process_pdf(p, store) for p in sorted(Path(folder).glob("*.pdf"))]
