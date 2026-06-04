"""Single source of the sentence-embedding model.

Both the ingestion side (pipeline) and the query side (RAG) import the embedder
from here, so the model is defined once and can be swapped via .env.

Default is BAAI/bge-m3: an 8192-token, multilingual (EN/FR/NL + 100 more),
1024-dim model. The long context means a full inspection-report page embeds
without truncation (the old all-MiniLM-L6-v2 capped at 256 tokens, ~190 words,
silently dropping the rest of a ~500-word page); multilingual covers the
Benelux corpus.

Swapping the model is "set EMBED_MODEL + EMBED_DIM in .env, then re-index"
(scripts/reindex_embeddings.py) — no code change. EMBED_DIM must match the
model; the loader asserts this so the two can't silently drift.
"""
from __future__ import annotations

import os

from sentence_transformers import SentenceTransformer

_MODEL_NAME = os.environ.get("EMBED_MODEL", "BAAI/bge-m3")
# Vector width the FAISS index is built at. Must equal the model's output dim;
# kept as a cheap env value so importing Store doesn't have to load the model.
EMBED_DIM = int(os.environ.get("EMBED_DIM", "1024"))
# Bound the per-input token length. Far above a normal page (~700-900 tokens),
# so real pages embed whole, while a pathologically long OCR page can't blow up
# memory. Encoding cost scales with the actual input, not this cap.
_MAX_SEQ = int(os.environ.get("EMBED_MAX_SEQ", "2048"))

_embedder: SentenceTransformer | None = None


def get_embedder() -> SentenceTransformer:
    """Lazily load and cache the shared model (heavy: deferred off import)."""
    global _embedder
    if _embedder is None:
        model = SentenceTransformer(_MODEL_NAME)
        # method renamed across sentence-transformers versions
        dim = (
            model.get_embedding_dimension()
            if hasattr(model, "get_embedding_dimension")
            else model.get_sentence_embedding_dimension()
        )
        if dim != EMBED_DIM:
            raise RuntimeError(
                f"EMBED_DIM={EMBED_DIM} but model {_MODEL_NAME!r} produces "
                f"{dim}-dim vectors. Set EMBED_DIM={dim} in .env and re-index "
                "(scripts/reindex_embeddings.py)."
            )
        if model.max_seq_length is None or model.max_seq_length > _MAX_SEQ:
            model.max_seq_length = _MAX_SEQ
        _embedder = model
    return _embedder


def embed(text):
    """Encode one string (or list) to vector(s). Thin wrapper over the model."""
    return get_embedder().encode(text)
