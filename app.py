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
            f"buildings merged: {stats['buildings_merged']} · "
            f"flagged for review: {stats['buildings_flagged']}"
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
        "       b.flag, b.flag_reasoning, b.possibly_same_as_building_id, "
        "       b.latitude, b.longitude, b.country, "
        "       COUNT(o.obs_id) AS n_obs "
        "FROM buildings b LEFT JOIN observations o ON o.building_id = b.building_id "
        "GROUP BY b.building_id ORDER BY n_obs DESC, b.building_id"
    )
    if not buildings:
        st.info("No buildings yet — process a report first.")
    else:
        # Flagged buildings get a leading ⚠️ in the dropdown so the user can see
        # at a glance which ones the LLM wants reviewed.
        options = {}
        for b in buildings:
            prefix = "⚠️ " if b['flag'] else ""
            options[f"{prefix}{b['display_name']}  ({b['n_obs']} defects)"] = b['building_id']
        choice = st.selectbox("Select building", list(options.keys()))
        row = next(b for b in buildings if b['building_id'] == options[choice])

        st.subheader(row['display_name'])
        if row['canonical_address'] and row['canonical_address'] != row['raw_address']:
            st.caption(f"Originally extracted as: \"{row['raw_address']}\"")

        # Surface the LLM's concern, if any
        if row['flag']:
            if row['flag'] == 'ambiguous_name':
                st.warning(
                    f"**⚠️ Ambiguous name** — {row['flag_reasoning']}\n\n"
                    "The geocoded location is unreliable. Edit the canonical "
                    "address with a specific city/state below and re-geocode."
                )
            elif row['flag'] == 'possible_duplicate':
                sibling = next(
                    (b for b in buildings if b['building_id'] == row['possibly_same_as_building_id']),
                    None,
                )
                sibling_name = sibling['display_name'] if sibling else "(unknown)"
                st.warning(
                    f"**⚠️ Possible duplicate of \"{sibling_name}\"** — "
                    f"{row['flag_reasoning']}\n\nIf they really are the same "
                    "building, use **Merge into another building** below."
                )

        # Edit / merge panel — auto-opens for flagged buildings
        with st.expander("Edit / merge this building", expanded=bool(row['flag'])):
            new_canonical = st.text_input(
                "Canonical address (saving re-geocodes)",
                value=row['canonical_address'] or row['raw_address'],
                key=f"edit_addr_{row['building_id']}",
            )
            if st.button("Save edit & re-geocode", key=f"save_edit_{row['building_id']}"):
                store.update_canonical_address(row['building_id'], new_canonical)
                with st.spinner("Re-geocoding…"):
                    from inspect_copilot.geocode import geocode_pending
                    geocode_pending(store)
                st.success("Saved.")
                st.rerun()

            others = [b for b in buildings if b['building_id'] != row['building_id']]
            if others:
                st.markdown("---")
                other_map = {f"{b['display_name']}  (id #{b['building_id']})": b['building_id']
                             for b in others}
                target_label = st.selectbox(
                    "Merge into another building (this row will be deleted):",
                    ["—"] + list(other_map.keys()),
                    key=f"merge_target_{row['building_id']}",
                )
                if target_label != "—" and st.button(
                    "Merge", key=f"merge_btn_{row['building_id']}"
                ):
                    store.manual_merge(other_map[target_label], row['building_id'])
                    st.success("Merged.")
                    st.rerun()

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
        c1, c2, c3 = st.columns(3)
        src = c1.multiselect("Report", sorted(df.source_file.unique()))
        dt = c2.multiselect("Defect type", sorted(df.defect_type.unique()))
        sev = c3.multiselect("Severity", sorted(df.severity.unique()))
        if src:
            df = df[df.source_file.isin(src)]
        if dt:
            df = df[df.defect_type.isin(dt)]
        if sev:
            df = df[df.severity.isin(sev)]
        st.caption(f"{len(df)} of {len(rows)} observations")
        st.dataframe(df, use_container_width=True)

elif view == "Analytics":
    st.header("Portfolio analytics")

    # Filter options from current DB state
    report_choices = [r["source_file"] for r in store.sql(
        "SELECT DISTINCT source_file FROM observations ORDER BY source_file")]
    building_rows = store.sql(
        "SELECT building_id, COALESCE(canonical_address, raw_address) AS name "
        "FROM buildings ORDER BY name"
    )
    building_label_to_id = {b["name"]: b["building_id"] for b in building_rows}

    f1, f2 = st.columns(2)
    sel_reports = f1.multiselect("Report", report_choices)
    sel_building_labels = f2.multiselect("Building", list(building_label_to_id.keys()))
    sel_building_ids = [building_label_to_id[n] for n in sel_building_labels]

    top = query.top_defect_types(store, source_files=sel_reports or None,
                                 building_ids=sel_building_ids or None, limit=10)
    sev = query.severity_breakdown(store, source_files=sel_reports or None,
                                   building_ids=sel_building_ids or None)
    if not top:
        st.info("No observations match these filters.")
    else:
        n_match = sum(r["n"] for r in top)
        filtered = bool(sel_reports or sel_building_ids)
        st.caption(f"{n_match} observations" + (" (filtered)" if filtered else ""))
        c1, c2 = st.columns(2)
        c1.subheader("Most frequent defect types")
        c1.bar_chart(pd.DataFrame(top).set_index("defect_type"), height=400)
        c2.subheader("Severity distribution")
        c2.bar_chart(pd.DataFrame(sev).set_index("severity"), height=400)

elif view == "Ask":
    st.header("Ask the corpus (semantic)")
    st.caption("For fuzzy/open-ended questions. Use Analytics for exact counts.")
    q = st.text_input("Question", placeholder="Which reports mention chloride-induced corrosion?")
    if q:
        with st.spinner("Retrieving…"):
            res = query.answer_semantic(store, q)
        st.write(res["answer"])
        st.caption("Sources: " + ", ".join(res["sources"]))
