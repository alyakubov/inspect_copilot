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
view = st.sidebar.radio("View", ["Process", "Buildings", "Browse", "Analytics", "Ask"])

if view == "Process":
    st.header("Process inspection reports")
    up = st.file_uploader("Upload a report PDF", type="pdf")
    if up and st.button("Run pipeline"):
        Path("data/raw").mkdir(parents=True, exist_ok=True)
        dest = Path("data/raw") / up.name
        dest.write_bytes(up.getbuffer())
        with st.spinner("Ingesting, extracting, embedding, geocoding…"):
            stats = process_pdf(dest, store)
        st.success(
            f"{stats['observations']} observations from {stats['chunks']} chunks · "
            f"OCR used: {stats['ocr_used']} · "
            f"geocoded: {stats['geocoded']} · "
            f"buildings merged: {stats['buildings_merged']}"
        )
    log = store.sql("SELECT status, COUNT(*) n FROM extraction_log GROUP BY status")
    if log:
        st.subheader("Extraction log")
        st.table(pd.DataFrame([dict(r) for r in log]))

elif view == "Buildings":
    st.header("Buildings")
    buildings = store.sql(
        "SELECT b.building_id, "
        "       COALESCE(b.canonical_address, b.raw_address) AS display_name, "
        "       b.raw_address, b.canonical_address, "
        "       b.latitude, b.longitude, b.country, "
        "       COUNT(o.obs_id) AS n_obs "
        "FROM buildings b LEFT JOIN observations o ON o.building_id = b.building_id "
        "GROUP BY b.building_id ORDER BY n_obs DESC, b.building_id"
    )
    if not buildings:
        st.info("No buildings yet — process a report first.")
    else:
        options = {f"{b['display_name']}  ({b['n_obs']} defects)": b['building_id']
                   for b in buildings}
        choice = st.selectbox("Select building", list(options.keys()))
        row = next(b for b in buildings if b['building_id'] == options[choice])

        st.subheader(row['display_name'])
        # Show original extraction when LLM dedup renamed it (audit visibility)
        if row['canonical_address'] and row['canonical_address'] != row['raw_address']:
            st.caption(f"Originally extracted as: \"{row['raw_address']}\"")

        if row['latitude'] is not None and row['longitude'] is not None:
            coord_str = f"📍 {row['latitude']:.5f}, {row['longitude']:.5f}"
            if row['country']:
                coord_str += f"  ·  {row['country']}"
            st.caption(coord_str)

            tab_2d, tab_3d = st.tabs(["2D map", "3D view"])
            with tab_2d:
                import folium
                from streamlit_folium import st_folium
                m = folium.Map(location=[row['latitude'], row['longitude']], zoom_start=17)
                # CircleMarker uses inline SVG — avoids the broken-image flash
                # on first mount that folium.Marker exhibits in Streamlit's iframe.
                folium.CircleMarker(
                    location=[row['latitude'], row['longitude']],
                    radius=9,
                    color="#1f77b4",
                    weight=2,
                    fill=True,
                    fill_color="#1f77b4",
                    fill_opacity=0.7,
                    popup=row['display_name'],
                    tooltip=row['display_name'],
                ).add_to(m)
                st_folium(m, width=700, height=500, returned_objects=[],
                          key=f"building_map_{row['building_id']}")
            with tab_3d:
                from inspect_copilot.cesium import viewer_html
                st.components.v1.html(
                    viewer_html(row['latitude'], row['longitude'], row['display_name']),
                    height=520,
                )
        else:
            st.warning("This building's address could not be geocoded — no map available.")

        obs = store.sql(
            "SELECT page, defect_type, building_element, material, severity, "
            "       confidence, verbatim_quote "
            "FROM observations WHERE building_id = ? ORDER BY page",
            (row['building_id'],),
        )
        st.subheader(f"Defects ({len(obs)})")
        if obs:
            # st.table renders as a full HTML table — text columns wrap naturally
            # so the verbatim_quote is readable in full. Loses sort/filter UX, but
            # per-building defect counts are small (this is fine here; Browse uses
            # st.dataframe for the full-corpus case where filtering matters).
            st.table(pd.DataFrame([dict(r) for r in obs]))
        else:
            st.info("No defects linked to this building.")

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
