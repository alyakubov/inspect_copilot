"""Two answering machines, one module — this is the crux of the design.

answer_aggregation():  count / group / filter / rank  -> SQL over ALL rows (exact)
answer_semantic():     fuzzy / open-ended follow-ups   -> RAG over retrieved chunks

Same upfront indexing feeds both. The aggregation path never touches the LLM
or the vector index; the semantic path retrieves a small top-k so we never load
whole files into context.
"""

from __future__ import annotations

import os
import re

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
def _filter_clause(
    source_files: list[str] | None = None,
    building_ids: list[int] | None = None,
    material: str | None = None,
) -> tuple[str, tuple]:
    """Build a parameterised WHERE clause from optional filters. Empty/None
    means 'no filter on this dimension'.
    """
    parts: list[str] = []
    params: list = []
    if source_files:
        parts.append("source_file IN (" + ",".join("?" * len(source_files)) + ")")
        params.extend(source_files)
    if building_ids:
        parts.append("building_id IN (" + ",".join("?" * len(building_ids)) + ")")
        params.extend(building_ids)
    if material:
        parts.append("material = ?")
        params.append(material)
    if parts:
        return " WHERE " + " AND ".join(parts), tuple(params)
    return "", ()


def top_defect_types(
    store: Store,
    source_files: list[str] | None = None,
    building_ids: list[int] | None = None,
    material: str | None = None,
    limit: int = 5,
):
    where, params = _filter_clause(source_files, building_ids, material)
    q = (f"SELECT defect_type, COUNT(*) n FROM observations{where} "
         "GROUP BY defect_type ORDER BY n DESC LIMIT ?")
    return [dict(r) for r in store.sql(q, params + (limit,))]


def severity_breakdown(
    store: Store,
    source_files: list[str] | None = None,
    building_ids: list[int] | None = None,
):
    where, params = _filter_clause(source_files, building_ids)
    q = (f"SELECT severity, COUNT(*) n FROM observations{where} "
         "GROUP BY severity ORDER BY n DESC")
    return [dict(r) for r in store.sql(q, params)]


def urgent_observations(store: Store):
    return [dict(r) for r in store.sql(
        "SELECT source_file,page,building_element,verbatim_quote FROM observations "
        "WHERE severity='urgent' ORDER BY source_file,page")]


# ---------- Path 2: semantic Q&A via RAG (fuzzy follow-ups) ----------
_ORDINAL_WORDS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}


def report_directory(store: Store) -> dict[int, str]:
    """Map the user-facing report number -> source_file.

    The number is documents.rowid (insertion order) — the same ID shown in the
    Browse and Analytics views, so "report 1" means the same thing everywhere.
    """
    rows = store.sql("SELECT rowid AS report_id, source_file FROM documents ORDER BY rowid")
    return {r["report_id"]: r["source_file"] for r in rows}


def resolve_report_references(question: str, directory: dict[int, str]) -> list[str]:
    """Find report numbers referenced in the question and map them to files.

    Handles "report 1", "report #2", "report no. 3", "reports 1 and 3",
    "1st report", and "first report". Numbers with no matching report are
    ignored. Returns the source_files in report-number order.
    """
    if not directory:
        return []
    ql = question.lower()
    nums: set[int] = set()
    # "report 1", "report #2", "report no. 3", and lists like "reports 1 and 3".
    for m in re.finditer(
        r"reports?\s*#?\s*(?:no\.?\s*)?(\d{1,3}(?:\s*(?:,|&|and)\s*\d{1,3})*)", ql
    ):
        nums.update(int(d) for d in re.findall(r"\d{1,3}", m.group(1)))
    for m in re.finditer(r"\b(\d{1,3})(?:st|nd|rd|th)\s+report\b", ql):
        nums.add(int(m.group(1)))
    for word, num in _ORDINAL_WORDS.items():
        if re.search(rf"\b{word}\s+report\b", ql) or re.search(rf"\breport\s+{word}\b", ql):
            nums.add(num)
    return [directory[n] for n in sorted(nums) if n in directory]


def answer_semantic(store: Store, question: str, k: int = 5) -> dict:
    directory = report_directory(store)
    target_sources = resolve_report_references(question, directory)

    qvec = _EMBEDDER.encode(question)
    hits = store.search(qvec, k=k, source_files=target_sources or None)
    context = "\n\n".join(f"[{h.source_file} p.{h.page}] {h.text}" for h in hits)

    directory_text = "\n".join(f"- Report {i}: {src}" for i, src in sorted(directory.items()))
    system = (
        "Answer ONLY from the provided report excerpts. Cite source file and page "
        "for each claim. If the excerpts don't contain the answer, say so.\n\n"
        "Users refer to reports by number. Use this directory to map a number to "
        "its file; do not ask the user which report they mean:\n"
        f"{directory_text}\n\n"
        "When the question names a report by number, answer only about that report."
    )
    msg = _CLIENT.messages.create(
        model=_MODEL,
        max_tokens=600,
        system=system,
        messages=[{"role": "user", "content": f"Excerpts:\n{context}\n\nQuestion: {question}"}],
    )
    answer = "".join(b.text for b in msg.content if b.type == "text")
    return {
        "answer": answer,
        "sources": [f"{h.source_file} p.{h.page}" for h in hits],
        "scope": target_sources,
    }
