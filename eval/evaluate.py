"""Evaluate extraction against a hand-labelled gold set.

Workflow:
  1. Hand-label ~30-50 observations across 3 documents in gold.jsonl, each:
     {"source_file","page","defect_type","severity"}
  2. Run the pipeline on those 3 docs.
  3. This script matches predicted observations to gold on (source_file,page)
     and reports precision/recall on defect_type and severity.

This is deliberately simple: matching on (file,page) over-counts when a page has
multiple defects, so treat the numbers as a directional quality signal, not a
benchmark. Naming that limitation is the point — see README "Evaluation & limits".
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from inspect_copilot.store import Store

GOLD = Path("eval/gold.jsonl")


def load_gold() -> list[dict]:
    if not GOLD.exists():
        return []
    return [json.loads(line) for line in GOLD.read_text().splitlines() if line.strip()]


def evaluate(store: Store) -> dict:
    gold = load_gold()
    if not gold:
        return {"error": "no gold set — create eval/gold.jsonl first"}

    files = {g["source_file"] for g in gold}
    pred = [dict(r) for r in store.sql(
        "SELECT source_file,page,defect_type,severity FROM observations "
        f"WHERE source_file IN ({','.join('?'*len(files))})", tuple(files))]

    def score(field: str) -> dict:
        g = Counter((x["source_file"], x["page"], x[field]) for x in gold)
        p = Counter((x["source_file"], x["page"], x[field]) for x in pred)
        tp = sum((g & p).values())
        prec = tp / sum(p.values()) if p else 0.0
        rec = tp / sum(g.values()) if g else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        return {"precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3)}

    return {"defect_type": score("defect_type"), "severity": score("severity"),
            "n_gold": len(gold), "n_pred": len(pred)}


if __name__ == "__main__":
    print(json.dumps(evaluate(Store("data/db/inspect_copilot.sqlite", "data/db/vectors.faiss")), indent=2))
