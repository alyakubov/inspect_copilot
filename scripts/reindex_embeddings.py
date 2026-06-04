"""Rebuild the FAISS vector index with the current embedding model.

Run after changing EMBED_MODEL/EMBED_DIM (e.g. the all-MiniLM-L6-v2 -> bge-m3
migration). Re-encodes every chunk's text and writes a fresh index sized to
EMBED_DIM. Local-only: no LLM / Anthropic calls, so it costs nothing but CPU.
The structured tables (chunks, observations, buildings) are untouched.

Usage:
    python scripts/reindex_embeddings.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import faiss  # noqa: E402

from inspect_copilot.embedding import EMBED_DIM, get_embedder  # noqa: E402
from inspect_copilot.store import Store  # noqa: E402

DB = "data/db/inspect_copilot.sqlite"
FAISS = "data/db/vectors.faiss"


def main() -> int:
    store = Store(DB, FAISS)
    rows = store.sql("SELECT chunk_id, text FROM chunks ORDER BY chunk_id")
    if not rows:
        print("No chunks to index.")
        return 0

    # Back up the existing index before replacing it.
    if Path(FAISS).exists():
        shutil.copy2(FAISS, FAISS + ".bak")
        print(f"backed up old index -> {FAISS}.bak")

    embedder = get_embedder()
    print(f"re-embedding {len(rows)} chunks with EMBED_DIM={EMBED_DIM} …")

    # Fresh, correctly-sized index; add_vector normalizes for cosine.
    store.index = faiss.IndexIDMap(faiss.IndexFlatIP(EMBED_DIM))
    for i, r in enumerate(rows, 1):
        store.add_vector(r["chunk_id"], embedder.encode(r["text"]))
        if i % 20 == 0 or i == len(rows):
            print(f"  {i}/{len(rows)}")
    store.save_vectors()

    print(f"done. index now has {store.index.ntotal} vectors of dim {store.index.d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
