"""InspectCopilot — minimal Streamlit UI.

Four views, each mapping to a piece of the design:
  Process   -> run the dual-index pipeline, show the extraction log (robustness evidence)
  Browse    -> filterable observation table with verbatim-quote traceability (SQL)
  Analytics -> defect frequency / severity charts (SQL aggregation, exact)
  Ask       -> semantic Q&A with cited sources (RAG, for fuzzy follow-ups)
"""

from pathlib import Path

from dotenv import load_dotenv
load_dotenv()  # must run before inspect_copilot imports — they create the API client at import time

import pandas as pd
import streamlit as st

from inspect_copilot.store import Store
from inspect_copilot.pipeline import process_pdf
from inspect_copilot import query

DB = "data/db/inspect_copilot.sqlite"
FAISS = "data/db/vectors.faiss"

st.set_page_config(page_title="InspectCopilot", layout="wide")
store = Store(DB, FAISS)

st.title("InspectCopilot — building defect intelligence")
view = st.sidebar.radio("View", ["Process", "Browse", "Analytics", "Ask"])

if view == "Process":
    st.header("Process inspection reports")
    up = st.file_uploader("Upload a report PDF", type="pdf")
    if up and st.button("Run pipeline"):
        Path("data/raw").mkdir(parents=True, exist_ok=True)
        dest = Path("data/raw") / up.name
        dest.write_bytes(up.getbuffer())
        with st.spinner("Ingesting, extracting, embedding…"):
            stats = process_pdf(dest, store)
        st.success(f"{stats['observations']} observations from {stats['chunks']} chunks "
                   f"(OCR used: {stats['ocr_used']})")
    log = store.sql("SELECT status, COUNT(*) n FROM extraction_log GROUP BY status")
    if log:
        st.subheader("Extraction log")
        st.table(pd.DataFrame([dict(r) for r in log]))

elif view == "Browse":
    st.header("Observations")
    rows = store.sql("SELECT source_file,page,defect_type,building_element,material,"
                     "severity,confidence,verbatim_quote FROM observations")
    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        st.info("No observations yet — process a report first.")
    else:
        c1, c2 = st.columns(2)
        dt = c1.multiselect("Defect type", sorted(df.defect_type.unique()))
        sev = c2.multiselect("Severity", sorted(df.severity.unique()))
        if dt:
            df = df[df.defect_type.isin(dt)]
        if sev:
            df = df[df.severity.isin(sev)]
        st.dataframe(df, use_container_width=True)

elif view == "Analytics":
    st.header("Portfolio analytics")
    top = query.top_defect_types(store, limit=10)
    sev = query.severity_breakdown(store)
    if not top:
        st.info("No data yet.")
    else:
        c1, c2 = st.columns(2)
        c1.subheader("Most frequent defect types")
        c1.bar_chart(pd.DataFrame(top).set_index("defect_type"))
        c2.subheader("Severity distribution")
        c2.bar_chart(pd.DataFrame(sev).set_index("severity"))

elif view == "Ask":
    st.header("Ask the corpus (semantic)")
    st.caption("For fuzzy/open-ended questions. Use Analytics for exact counts.")
    q = st.text_input("Question", placeholder="Which reports mention chloride-induced corrosion?")
    if q:
        with st.spinner("Retrieving…"):
            res = query.answer_semantic(store, q)
        st.write(res["answer"])
        st.caption("Sources: " + ", ".join(res["sources"]))
