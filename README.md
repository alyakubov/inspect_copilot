# InspectCopilot — building defect intelligence from inspection reports

Turn a folder of heterogeneous building-inspection PDFs into a searchable,
analyzable database of structured defect observations — plus semantic Q&A over
the raw text.

## What problem, and for whom?

SECO generates large volumes of inspection reports as free-text PDFs. Each
describes defects (cracks, corrosion, damp, spalling, fire-safety
non-compliance…), their location, severity, and recommended action. That
knowledge is locked in prose: you cannot aggregate it, filter it, count it, or
analyze it across a portfolio.

**Primary user:** the SECO inspector / control engineer.
**Secondary user:** the asset manager receiving the reports.

InspectCopilot extracts every observation into a structured schema, so questions
like *"the five most frequent defect types on 1960s concrete buildings"* or
*"every urgent observation, by element"* become exact queries instead of manual
re-reading.

## Why is this relevant to SECO?

The brief's own framing: huge volumes of technical data that "remain largely
underexploited." The underexploitation isn't an inability to ask questions —
it's that the knowledge can't be aggregated. That makes this an **extraction**
problem first, a retrieval problem second. InspectCopilot attacks exactly that.

## Data sources

Public, reproducible inspection/condition reports in EN/FR/NL (matching SECO's
Benelux footprint): municipal building audits, published façade and fire-safety
inspections, and infrastructure condition reports. Heterogeneity — born-digital
vs scanned, multilingual, varied layouts — is intentional: handling it is the
point.

## Architecture

One upfront pass over each PDF builds **two indexes**:

| Index | Built by | Answers | How |
|-------|----------|---------|-----|
| **1. Structured rows** (SQLite) | LLM extraction → Pydantic validation | count / group / filter / rank | exact SQL over *all* rows |
| **2. Vectors** (FAISS) | sentence-transformers embeddings | fuzzy / open-ended follow-ups | top-k retrieval → LLM (RAG) |

The expensive LLM call happens **once per chunk at ingestion**, never per
question and never over a whole file. Aggregation questions hit SQL (exact,
complete, auditable); only genuinely semantic questions use RAG.

**Why not RAG for everything?** Retrieval returns a top-k *subset*, so "how many
urgent defects across 40 reports" becomes a guess. `SELECT COUNT(*)` over the
structured index is exact. RAG is the right tool only for the residual fuzzy
questions — so it's additive, not the spine.

```
ingest (text layer + OCR fallback) → chunk + language-detect
   → LLM extract → validate → SQLite        [Index 1]
   → embed       →            FAISS          [Index 2]
```

## Technical decisions & trade-offs

- **SQLite + FAISS, not Postgres + pgvector.** At 15–40 reports (a few thousand
  vectors) Postgres is premature; SQLite is a single reproducible file. The
  storage layer (`store.py`) is a thin interface, so migrating to pgvector at
  portfolio scale means rewriting one file. Trade-off: no concurrent writers,
  no ANN index — both irrelevant at this scale.
- **React + FastAPI (migrated from Streamlit).** The UI is a React/TypeScript
  SPA (Vite + MUI) talking to a thin FastAPI wrapper around the same engine.
  Streamlit got to usable fastest; the React frontend is the production-shaped
  rebuild on SECO's stack. The engine (extraction, SQL, FAISS, geocoding,
  dedup) is unchanged — FastAPI just exposes it over JSON. The old `app.py`
  Streamlit UI is retained for reference but is no longer the entry point.
- **Controlled vocabulary in the schema.** Enums make aggregation meaningful
  but lose nuance; free-text fields (`recommended_action`, `location`) keep it.
- **Validation quarantine, not silent drops.** Failed extractions go to
  `extraction_log`, so robustness is measurable, not hidden.

## Evaluation & limits

A hand-labelled gold set (`eval/`) measures extraction precision/recall on
`defect_type` and `severity`. Known failure modes: severity is subjective; OCR
garbles tables; the model is prompted **not** to invent regulatory references
(a real hallucination risk). Every observation carries a verbatim quote + page
for audit.

## Production tomorrow vs. throw away

**Ship:** the extraction schema, validation/quarantine layer, SQL aggregation,
verbatim-quote traceability.
**Throw away:** any extraction not backed by a source quote; OCR without a
quality gate; naive RAG without the eval.

## If I had 3 months

Human-in-the-loop correction (inspectors fix extractions; corrections fine-tune
the extractor); section-aware chunking; computer-vision defect detection from
inspection **photos** (cracks, spalling, corrosion); migration to Postgres +
pgvector; cross-report portfolio risk patterns.

## Run

The app is a **FastAPI** backend (`api/`) serving a **React/Vite** frontend
(`frontend/`). Both sit on top of the unchanged `inspect_copilot/` engine.

### 1. Backend (Python 3.11 venv)
```bash
mkdir -p ~/.venvs
python3 -m venv ~/.venvs/inspect_copilot
source ~/.venvs/inspect_copilot/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

# OCR (scanned pages); add tesseract-ocr-fra tesseract-ocr-nld if needed
sudo apt-get update && sudo apt-get install -y tesseract-ocr tesseract-ocr-eng
```

### 2. Frontend (Node 20, pinned via .nvmrc)
```bash
nvm install      # reads .nvmrc -> Node 20
nvm use
cd frontend && npm install && cd ..
```

### 3. Configure
Copy `.env.example` to `.env` and fill in `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL`
(and optionally `CESIUM_ION_TOKEN`, `USER_LOGIN`/`USER_PASSWORD`, `NO_DELETE_REPORT`).

### Develop (two terminals, hot reload)
```bash
# terminal 1 — API on :8001  (8000 is Django's default; avoid the clash)
source ~/.venvs/inspect_copilot/bin/activate
uvicorn api.main:app --reload --port 8001

# terminal 2 — SPA on :5173 (proxies /api -> :8001)
cd frontend && npm run dev
# open http://localhost:5173
```

### Production (single process)
```bash
cd frontend && npm run build && cd ..   # emits frontend/dist
source ~/.venvs/inspect_copilot/bin/activate
uvicorn api.main:app --port 8001        # serves the SPA + API at http://localhost:8001
```

**Optional env flags**
- `USER_LOGIN` + `USER_PASSWORD` — if both set, the UI requires login; if either
  is absent, no login is required.
- `NO_DELETE_REPORT=true` — the report Delete button stays visible but deletion
  is blocked.
- A processed report can't be re-uploaded until it's deleted (HTTP 409).

> Legacy: the original Streamlit UI still runs via `streamlit run app.py`, but
> the React frontend above is the supported entry point.
