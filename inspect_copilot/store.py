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
    raw_address         TEXT,                -- as extracted from the report (audit)
    normalized_address  TEXT UNIQUE,         -- for INSERT-time dedup
    canonical_address   TEXT,                -- LLM-resolved official name+city (if set)
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


def _name_tokens(s: str) -> list[str]:
    import re
    cleaned = re.sub(r"[^\w\s]", " ", s.lower())
    return [t for t in cleaned.split() if len(t) > 1]


# Building-type suffixes that don't identify *which* building.
# Stripping them stops "Federal Building" from collapsing into every other
# "X Federal Building" purely on the shared generic words.
_GENERIC_BUILDING_WORDS = frozenset({
    "building", "buildings", "courthouse", "courthouses", "center", "centre",
    "complex", "facility", "facilities", "hall", "station", "office",
    "headquarters", "annex", "tower", "plaza", "post", "court", "federal",
})


def _names_likely_same_building(a: str, b: str) -> bool:
    """Heuristic for two extracted names referring to the same building.

    Catches:
    1. Containment — shorter name's distinctive tokens fully appear in longer.
       'Clinton Building' vs 'William Jefferson Clinton Federal Building'.
    2. Acronym expansion — uppercase token in one spells initials of consecutive
       words in the other. 'Oroville LPOE' vs 'Oroville Land Port of Entry'.

    Refuses to merge when both sides are all generic terms.
    """
    import re
    tok_a = _name_tokens(a)
    tok_b = _name_tokens(b)
    if not tok_a or not tok_b:
        return False

    distinctive_a = set(tok_a) - _GENERIC_BUILDING_WORDS
    distinctive_b = set(tok_b) - _GENERIC_BUILDING_WORDS
    if not distinctive_a or not distinctive_b:
        return False

    shorter, longer = (
        (distinctive_a, distinctive_b)
        if len(distinctive_a) <= len(distinctive_b)
        else (distinctive_b, distinctive_a)
    )
    if shorter.issubset(longer):
        return True

    def _matches_via_acronym(src: str, target_tokens: list[str]) -> bool:
        for acronym in re.findall(r"\b[A-Z]{2,5}\b", src):
            n = len(acronym)
            for i in range(len(target_tokens) - n + 1):
                if all(target_tokens[i + j][:1] == acronym[j].lower() for j in range(n)):
                    return True
        return False

    return _matches_via_acronym(a, tok_b) or _matches_via_acronym(b, tok_a)


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
        bcols = {r["name"] for r in self.conn.execute("PRAGMA table_info(buildings)")}
        if "canonical_address" not in bcols:
            self.conn.execute("ALTER TABLE buildings ADD COLUMN canonical_address TEXT")

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

    def update_building_coords(
        self,
        building_id: int,
        latitude: float,
        longitude: float,
        country: str | None,
    ) -> None:
        self.conn.execute(
            "UPDATE buildings SET latitude=?, longitude=?, country=? WHERE building_id=?",
            (latitude, longitude, country, building_id),
        )
        self.conn.commit()

    def merge_duplicate_buildings(self, eps_deg: float = 0.0005) -> int:
        """Merge buildings whose geocoded coords fall within `eps_deg` of each
        other (default ~55m at the equator). Survivor is the row with the
        lowest building_id; observations are repointed at the survivor and
        duplicate building rows are deleted. Returns count of merged-away rows.
        Idempotent — running again on a clean DB returns 0.
        """
        from collections import defaultdict

        rows = self.conn.execute(
            "SELECT building_id, latitude, longitude FROM buildings "
            "WHERE latitude IS NOT NULL AND longitude IS NOT NULL"
        ).fetchall()

        clusters: dict[tuple[float, float], list[int]] = defaultdict(list)
        for r in rows:
            key = (
                round(r["latitude"] / eps_deg) * eps_deg,
                round(r["longitude"] / eps_deg) * eps_deg,
            )
            clusters[key].append(r["building_id"])

        n_merged = 0
        for ids in clusters.values():
            if len(ids) < 2:
                continue
            survivor = min(ids)
            dupes = [i for i in ids if i != survivor]
            self.conn.executemany(
                "UPDATE observations SET building_id=? WHERE building_id=?",
                [(survivor, d) for d in dupes],
            )
            self.conn.executemany(
                "DELETE FROM buildings WHERE building_id=?",
                [(d,) for d in dupes],
            )
            n_merged += len(dupes)
        self.conn.commit()
        return n_merged

    def apply_canonical_merges(self, merges: list[dict]) -> int:
        """Apply LLM-suggested same-building merges.

        Each merge group is {canonical_address, alias_ids, reasoning?}. Survivor
        is the lowest alias_id; its canonical_address is set, lat/lon cleared
        (so geocoding re-runs on the better name), observations from other ids
        are repointed at the survivor, dupe rows deleted. Each merge is logged
        in extraction_log with the LLM's reasoning for audit.

        Hallucinated ids (not in the DB) are silently dropped. Groups with
        fewer than 2 valid ids are skipped. Returns count of merged-away rows.
        """
        valid_ids = {
            r["building_id"]
            for r in self.conn.execute("SELECT building_id FROM buildings")
        }
        n_merged = 0
        for grp in merges:
            canonical = (grp.get("canonical_address") or "").strip()
            ids = [i for i in grp.get("alias_ids") or [] if i in valid_ids]
            if len(ids) < 2 or not canonical:
                continue
            survivor = min(ids)
            dupes = [i for i in ids if i != survivor]
            self.conn.execute(
                "UPDATE buildings SET canonical_address=?, latitude=NULL, longitude=NULL, country=NULL "
                "WHERE building_id=?",
                (canonical, survivor),
            )
            self.conn.executemany(
                "UPDATE observations SET building_id=? WHERE building_id=?",
                [(survivor, d) for d in dupes],
            )
            self.conn.executemany(
                "DELETE FROM buildings WHERE building_id=?",
                [(d,) for d in dupes],
            )
            self.conn.execute(
                "INSERT INTO extraction_log (chunk_id,status,detail) VALUES (?,?,?)",
                (-1, "semantic_merge",
                 f"canonical={canonical!r} survivor_id={survivor} from_ids={ids}"
                 f" reasoning={grp.get('reasoning','')!r}"),
            )
            n_merged += len(dupes)
        self.conn.commit()
        return n_merged

    def merge_similar_named_buildings(self) -> int:
        """Merge buildings whose extracted names look like the same place under
        a shorter or abbreviated form (see _names_likely_same_building).

        Survivor: the longer name (more specific). Survivor's coords are kept as-is —
        the shorter-named row's coords are discarded because the shorter name is
        more likely to have been geocoded to the wrong place.

        Idempotent — running again on a clean DB returns 0.
        """
        rows = self.conn.execute(
            "SELECT building_id, raw_address FROM buildings "
            "ORDER BY length(raw_address) DESC, building_id"
        ).fetchall()

        survivors: list[tuple[int, str]] = []
        merges: list[tuple[int, int]] = []  # (survivor_id, dupe_id)
        for r in rows:
            bid, addr = r["building_id"], r["raw_address"]
            match_id = next(
                (s_id for s_id, s_addr in survivors if _names_likely_same_building(addr, s_addr)),
                None,
            )
            if match_id is None:
                survivors.append((bid, addr))
            else:
                merges.append((match_id, bid))

        for survivor_id, dupe_id in merges:
            self.conn.execute(
                "UPDATE observations SET building_id=? WHERE building_id=?",
                (survivor_id, dupe_id),
            )
            self.conn.execute(
                "DELETE FROM buildings WHERE building_id=?",
                (dupe_id,),
            )
        self.conn.commit()
        return len(merges)

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
