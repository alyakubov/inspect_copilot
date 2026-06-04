# InspectCopilot — building defect intelligence from inspection reports

Turn a folder of heterogeneous building-inspection PDFs into a searchable,
analyzable database of structured defect observations — plus semantic Q&A over
the raw text.

## What problem, and for whom?

We have inspection reports as free-text PDFs. Each
describes defects (cracks, corrosion, damp, fire-safety
non-compliance…), their location, severity, and recommended action for a 
number of buildings. 
That knowledge is locked in prose: you cannot aggregate it, filter it, count it, or
analyze it across a portfolio.

- **Primary user:** the insurance specialist or investor (asset manager) receiving the reports.
- **Person who checks the database:** a construction inspector / control engineer.

InspectCopilot extracts every observation into a structured schema, so questions
like *"the five most frequent defect types on 1980s concrete buildings"* or
*"every urgent observation, by element"* become exact queries instead of manual
re-reading.

## Why is this relevant

With this app we are trying to resolve the main challenge: extract information from 
huge volumes of technical data in free-text PDFs that "remain largely
underexploited." The underexploitation isn't an inability to ask questions —
it's that the knowledge can't be aggregated. That makes this an **extraction**
problem first, a retrieval problem second. 

InspectCopilot offers the following functionality:
- Extraction of building defect from free text PDF reports linked to the building
- Person who supervises database should check that the building was geolocated correctly
- User (investor or insurance manager) can see the buildings in 2D maps and in 3D views with 
the defect list from the inspection reports.
- User can filter all defects in the portfolio by their severity
and by other params like reports and defect type. Charts are available in Analytics section.
- And, of course, user can ask any question like
*"Give me a summary for urgent severity defects for the whole portfolio"*.

## Data sources
We used public inspection and validation reports of US Office of Inspector General.
They are all in free-text PDF with one report covering sometimes multiple buildings.

The reports concern federal property, so our app can be also useful for:
- Insurance specialists working with the federal government
- Investors planning participate in the privatisation

https://www.gsaig.gov/inspection-and-evaluation-report 


## Architecture

One upfront pass over each PDF builds **two indexes** and geolocation as building index extension:

| Index                                 | Built by                                   | Answers | How                         |
|---------------------------------------|--------------------------------------------|---------|-----------------------------|
| **1. Structured rows** (SQLite)       | LLM extraction → Pydantic validation       | count / group / filter / rank | exact SQL over *all* rows   |
| **2. Text vectors** (FAISS)           | sentence-transformers embeddings           | fuzzy / open-ended follow-ups | top-k retrieval → LLM (RAG) |
| **3. Geolocation** (checked by human) | building address (not full) → coordinates | association of the building from different reports | free or paid services       |

The expensive LLM call happens **once per chunk at ingestion**, never per
question and never over a whole file. Aggregation questions hit SQL (exact,
complete, auditable); only genuinely semantic questions use RAG. 
We spend <0.01 USD per report.

**Why not RAG for everything?** Retrieval returns a top-k *subset*, so "how many
urgent defects across 40 reports" becomes a guess. `SELECT COUNT(*)` over the
structured index is exact. RAG is the right tool only for the residual fuzzy
questions — so it's additive, not the spine.

```
ingest (text layer + OCR fallback) → chunk + language-detect
   → LLM extract → geolocation → SQLite        [Index 1]
   → embedding   → chunk link  → FAISS         [Index 2]
```

## Technical decisions & trade-offs

- **SQLite + FAISS, not Postgres + pgvector/ ChromaDB.** At 15–40 reports (a few thousand
  vectors) Postgres is premature; SQLite is a single reproducible file. The
  storage layer (`store.py`) is a thin interface, so migrating to pgvector at
  portfolio scale means rewriting one file. Trade-off: no concurrent writers,
  no ANN index — both irrelevant at this scale.
- **Multi-language embedding bge-m3.** Local deployment (implies no payments). 
  Better performance for FR/NL compared to LlamaIndex's default embedder. 
  Large BERT position table limit of more than 700 words fully covering our page chunks. 
- **React + FastAPI (migrated from Streamlit).** 
  Streamlit got to usable fastest; the React frontend is the production-shaped
  rebuild on traditional stack. The engine (extraction, SQL, FAISS, geocoding,
  dedup) is unchanged — FastAPI just exposes it over JSON. The old `app.py`
  Streamlit UI is retained for reference but is no longer the entry point.
- **Controlled vocabulary in the schema.** Enums make aggregation meaningful
  but lose nuance; free-text fields (`recommended_action`, `location`) keep it.
- **Validation quarantine, not silent drops.** Failed extractions go to
  `extraction_log`, so robustness is measurable, not hidden. 
Every observation carries a verbatim quote + page
for audit.
- **Deduplication of buildings, geolocation.** Building deduplication is 
a crucial challenge solved with additional LLM request, geolocation check
and human control.

## Evaluation & limits (plain FAISS vs LlamaIndex)

A hand-labelled gold set (`eval/`) measures extraction precision/recall on
`defect_type` and `severity`. 
Although detailed analysis was not conducted due to lack of time, 
visual analysis shows reasonable extraction

Known **limitations** of FAISS compared to LlamaIndex:
1. Plain FAISS split to chunks is based on pages, not on text sections/structure. 
LlamaIndex implements text structure split by default with section overlaps, 
metadata and cross-section links. However, OCR extraction degrades the structure
of the documents (which can be seen in HTML/Markdown).
Thus for our specific tasks FAISS may have chance to keep in line with LlamaIndex.
2. We use plain nearest-neighbour index for RAG instead of LlamaIndex's ANN concept useful for
larger datasets. It gives us higher retrieval precision at the expense of delays, 
which are immaterial given our dataset size.

Where FAISS still can outperform LlamaIndex:
1. With fixed chunk of 1 page we control the limit of position table for BERT-embeddings
per chunk. With more sophisticated chunk split there is a risk that some chunk tails are
ignored by the index.
2. Small dataset based on SQL extraction and FAISS shows smaller execution delays
compared to LlamaIndex, which is designed for larger datasets. 

## Production tomorrow vs. throw away

**Keep in production:** the extraction schema, validation/quarantine layer, SQL aggregation,
verbatim-quote traceability, geolocation with human in the loop, 
2D/3D building views for the end-users.

**Throw away:** any extraction not backed by a double check on two LLMs ; OCR without a
quality gate; RAG without the eval (to be conducted, code available).

## If I had 3 months

- Migration to Postgres+pgvector (<5M chunks) or to Spark+Qdrant(>5M chunks) 
- Section-aware chunking (switch to LlamaIndex), embedding trade-off
of position table limit vs chunk size.
- Computer-vision defect detection from inspection **photos** (cracks, corrosion);
- Additional human-in-the-loop correction (inspectors fix extractions; corrections fine-tune
the extractor); 
- Research on cross-report portfolio risk patterns 
(*What are the most typical defects of 1980s buildings*).

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
