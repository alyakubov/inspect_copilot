"""Two answering machines, one module — this is the crux of the design.

answer_aggregation():  count / group / filter / rank  -> SQL over ALL rows (exact)
answer_semantic():     fuzzy / open-ended follow-ups   -> RAG over retrieved chunks

Same upfront indexing feeds both. The aggregation path never touches the LLM
or the vector index; the semantic path retrieves a small top-k so we never load
whole files into context.
"""

from __future__ import annotations

import os

from anthropic import Anthropic
from sentence_transformers import SentenceTransformer

from .store import Store

_CLIENT = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
_EMBEDDER = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
_MODEL = os.environ.get("ANTHROPIC_MODEL")
if not _MODEL:
    raise RuntimeError(
        "ANTHROPIC_MODEL is not set. Define it in .env (see .env.example) "
        "or export it in your shell."
    )


# ---------- Path 1: aggregation via SQL (exact, complete) ----------
def top_defect_types(store: Store, material: str | None = None, limit: int = 5):
    q = "SELECT defect_type, COUNT(*) n FROM observations"
    params: tuple = ()
    if material:
        q += " WHERE material = ?"
        params = (material,)
    q += " GROUP BY defect_type ORDER BY n DESC LIMIT ?"
    params = params + (limit,)
    return [dict(r) for r in store.sql(q, params)]


def severity_breakdown(store: Store):
    return [dict(r) for r in store.sql(
        "SELECT severity, COUNT(*) n FROM observations GROUP BY severity ORDER BY n DESC")]


def urgent_observations(store: Store):
    return [dict(r) for r in store.sql(
        "SELECT source_file,page,building_element,verbatim_quote FROM observations "
        "WHERE severity='urgent' ORDER BY source_file,page")]


# ---------- Path 2: semantic Q&A via RAG (fuzzy follow-ups) ----------
def answer_semantic(store: Store, question: str, k: int = 5) -> dict:
    qvec = _EMBEDDER.encode(question)
    hits = store.search(qvec, k=k)
    context = "\n\n".join(f"[{h.source_file} p.{h.page}] {h.text}" for h in hits)
    msg = _CLIENT.messages.create(
        model=_MODEL,
        max_tokens=600,
        system=("Answer ONLY from the provided report excerpts. Cite source file and page "
                "for each claim. If the excerpts don't contain the answer, say so."),
        messages=[{"role": "user", "content": f"Excerpts:\n{context}\n\nQuestion: {question}"}],
    )
    answer = "".join(b.text for b in msg.content if b.type == "text")
    return {"answer": answer, "sources": [f"{h.source_file} p.{h.page}" for h in hits]}
