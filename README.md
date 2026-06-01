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
- **Streamlit, not React.** This is an internal inspector tool; speed-to-usable
  beats frontend polish. Production rebuild would be React (SECO's stack).
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

Initiation:
```bash
  # 1. Create the parent directory (one-time)                                                                                                                                                                 
mkdir -p ~/.venvs                                                                  
                                                                                                                                                                                                              
  # 2. Create the venv using system Python 3.11                                                             
python3 -m venv ~/.venvs/inspect_copilot                                                                                                                                                                    
                                                                                                                                                                                                              
  # 3. Activate it                                                                                 
source ~/.venvs/inspect_copilot/bin/activate                                                                                                                                                                
                                                                                                                                                     
  # 4. Verify you're in the right env — should print ~/.venvs/inspect_copilot/bin/python                                                                                                                      
which python                                                                       
python --version                                                                                                                                                                                            
                                                                                                                                                     
  # 5. Upgrade packaging tools inside the new venv                                                                                                                                                            
pip install --upgrade pip setuptools wheel                                         
                                                                                                                                                                                                              
  # 6. Go to the project and install requirements                                                                                                                                                             
  # cd inspect_copilot  -- go to the project folder if you are not there                                        
pip install -r requirements.txt      
```

To run the app:
```bash
source venv/bin/activate
export ANTHROPIC_API_KEY=...
streamlit run app.py
```

Optional convenience — auto-activate alias                                                                                                                                                                  
                                                                                                   
  Add to ~/.bashrc:

  alias seco='source ~/.venvs/inspect_copilot/bin/activate && cd ~/your/path/to/inspect_copilot' 

  Then just type seco to jump in.
