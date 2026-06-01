"""Storage layer: SQLite for structured truth + raw chunks, FAISS for vectors.

The whole module sits behind a thin `Store` class. The extraction and query
code never touch SQL or FAISS directly. This is deliberate: migrating to
Postgres + pgvector in production means rewriting *this file only*, not the
pipeline. That keeps the README's "migrate to pgvector at scale" claim honest
rather than hand-wavy.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import faiss
import numpy as np

from .schema import Observation


@dataclass
class Chunk:
    chunk_id: int
    source_file: str
    page: int
    language: str
    text: str


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    source_file TEXT PRIMARY KEY,
    n_pages     INTEGER,
    ocr_used    INTEGER,            -- 0/1: did any page need OCR?
    language    TEXT
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT REFERENCES documents(source_file),
    page        INTEGER,
    language    TEXT,
    text        TEXT
);

CREATE TABLE IF NOT EXISTS buildings (
    building_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_address         TEXT,
    normalized_address  TEXT UNIQUE,
    latitude            REAL,
    longitude           REAL,
    country             TEXT
);

CREATE TABLE IF NOT EXISTS observations (
    obs_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id            INTEGER REFERENCES chunks(chunk_id),
    source_file         TEXT,
    page                INTEGER,
    building_id         INTEGER REFERENCES buildings(building_id),
    defect_type         TEXT,
    building_element    TEXT,
    material            TEXT,
    severity            TEXT,
    recommended_action  TEXT,
    regulatory_reference TEXT,
    location_in_building TEXT,
    confidence          REAL,
    verbatim_quote      TEXT
);

-- failures are quarantined, never silently dropped
CREATE TABLE IF NOT EXISTS extraction_log (
    log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id    INTEGER,
    status      TEXT,               -- ok | validation_error | llm_error
    detail      TEXT
);
"""


def _normalize_address(s: str) -> str:
    return " ".join(s.lower().strip().split()).rstrip(".,;:")


class Store:
    def __init__(self, db_path: str | Path, faiss_path: str | Path, dim: int = 384):
        self.db_path = str(db_path)
        self.faiss_path = str(faiss_path)
        self.dim = dim
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_SQL)
        self._migrate_observations_building_id()
        self.conn.commit()
        # FAISS index keyed by chunk_id (IDMap lets us store our own ids)
        if Path(self.faiss_path).exists():
            self.index = faiss.read_index(self.faiss_path)
        else:
            self.index = faiss.IndexIDMap(faiss.IndexFlatIP(dim))

    def _migrate_observations_building_id(self) -> None:
        """Add observations.building_id on pre-existing DBs without wiping data."""
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(observations)")}
        if "building_id" not in cols:
            self.conn.execute(
                "ALTER TABLE observations ADD COLUMN building_id INTEGER REFERENCES buildings(building_id)"
            )

    # ---- writes (ingestion side) ----
    def add_document(self, source_file: str, n_pages: int, ocr_used: bool, language: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO documents VALUES (?,?,?,?)",
            (source_file, n_pages, int(ocr_used), language),
        )
        self.conn.commit()

    def add_chunk(self, source_file: str, page: int, language: str, text: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO chunks (source_file,page,language,text) VALUES (?,?,?,?)",
            (source_file, page, language, text),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_or_create_building(self, raw_address: str) -> int:
        """Dedup by normalized_address. Returns building_id."""
        norm = _normalize_address(raw_address)
        row = self.conn.execute(
            "SELECT building_id FROM buildings WHERE normalized_address = ?", (norm,)
        ).fetchone()
        if row:
            return row["building_id"]
        cur = self.conn.execute(
            "INSERT INTO buildings (raw_address, normalized_address) VALUES (?, ?)",
            (raw_address, norm),
        )
        self.conn.commit()
        return cur.lastrowid

    def add_observations(
        self,
        chunk_id: int,
        source_file: str,
        page: int,
        obs: list[Observation],
        address_to_building_id: dict[str, int] | None = None,
    ) -> None:
        addr_map = address_to_building_id or {}
        rows = [
            (chunk_id, source_file, page,
             addr_map.get(o.building_address) if o.building_address else None,
             o.defect_type.value, o.building_element, o.material,
             o.severity.value, o.recommended_action, o.regulatory_reference,
             o.location_in_building, o.confidence, o.verbatim_quote)
            for o in obs
        ]
        self.conn.executemany(
            """INSERT INTO observations
               (chunk_id,source_file,page,building_id,defect_type,building_element,material,
                severity,recommended_action,regulatory_reference,location_in_building,
                confidence,verbatim_quote)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        self.conn.commit()

    def log(self, chunk_id: int, status: str, detail: str = "") -> None:
        self.conn.execute(
            "INSERT INTO extraction_log (chunk_id,status,detail) VALUES (?,?,?)",
            (chunk_id, status, detail),
        )
        self.conn.commit()

    def add_vector(self, chunk_id: int, vector: np.ndarray) -> None:
        v = vector.astype("float32").reshape(1, -1)
        faiss.normalize_L2(v)  # cosine similarity via inner product
        self.index.add_with_ids(v, np.array([chunk_id], dtype="int64"))

    def save_vectors(self) -> None:
        faiss.write_index(self.index, self.faiss_path)

    # ---- reads (query side) ----
    def sql(self, query: str, params: tuple = ()) -> list[sqlite3.Row]:
        """Run an arbitrary read query against the structured index.

        This is what answers the aggregation questions (count/group/filter/rank).
        No LLM, no retrieval — exact results over ALL observations.
        """
        return self.conn.execute(query, params).fetchall()

    def search(self, query_vec: np.ndarray, k: int = 5) -> list[Chunk]:
        """Vector search for the fuzzy/semantic follow-up questions (RAG side)."""
        v = query_vec.astype("float32").reshape(1, -1)
        faiss.normalize_L2(v)
        _, ids = self.index.search(v, k)
        out: list[Chunk] = []
        for cid in ids[0]:
            if cid == -1:
                continue
            r = self.conn.execute(
                "SELECT chunk_id,source_file,page,language,text FROM chunks WHERE chunk_id=?",
                (int(cid),),
            ).fetchone()
            if r:
                out.append(Chunk(r["chunk_id"], r["source_file"], r["page"], r["language"], r["text"]))
        return out
