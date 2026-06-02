"""InspectCopilot — minimal Streamlit UI.

Four views, each mapping to a piece of the design:
  Process   -> run the dual-index pipeline, show the extraction log (robustness evidence)
  Browse    -> filterable observation table with verbatim-quote traceability (SQL)
  Analytics -> defect frequency / severity charts (SQL aggregation, exact)
  Ask       -> semantic Q&A with cited sources (RAG, for fuzzy follow-ups)
"""

from html import escape as html_escape
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()  # must run before inspect_copilot imports — they create the API client at import time

import altair as alt
import pandas as pd
import streamlit as st

from inspect_copilot.store import Store
from inspect_copilot.pipeline import process_pdf
from inspect_copilot import query

# Display-only short forms for chart labels. Schema enum values are untouched.
_DEFECT_SHORT_LABEL = {
    "damp_infiltration": "damp",
    "fire_safety_noncompliance": "fire_safety",
    "material_degradation": "degradation",
}

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

    st.subheader("Processed reports")
    docs = store.sql(
        "SELECT d.rowid AS report_id, d.source_file, d.n_pages, "
        "       (SELECT COUNT(*) FROM observations o WHERE o.source_file = d.source_file) AS n_obs "
        "FROM documents d ORDER BY d.rowid"
    )
    if not docs:
        st.caption("No reports yet.")
    else:
        for d in docs:
            cols = st.columns([1, 6, 3, 2])
            cols[0].markdown(f"**#{d['report_id']}**")
            cols[1].write(d['source_file'])
            cols[2].caption(f"{d['n_pages']} pages · {d['n_obs']} obs")
            if cols[3].button("🗑 Delete", key=f"del_report_{d['report_id']}"):
                stats = store.delete_report(d['source_file'])
                pdf_path = Path("data/raw") / d['source_file']
                if pdf_path.exists():
                    pdf_path.unlink()
                st.toast(
                    f"Deleted #{d['report_id']}: "
                    f"{stats['observations']} obs, {stats['chunks']} chunks, "
                    f"{stats['buildings_deleted']} buildings, "
                    f"{stats['audit_cleaned']} audit entries"
                )
                st.rerun()

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
            if st.button(
                "Dismiss flag (mark as reviewed)",
                key=f"dismiss_{row['building_id']}",
            ):
                store.dismiss_flag(row['building_id'])
                st.toast("Flag dismissed. This building won't be re-flagged on future runs.")
                st.rerun()

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

    # Sequential integer report ID from documents.rowid (insertion order).
    docs = store.sql("SELECT rowid AS report_id, source_file FROM documents ORDER BY rowid")
    source_to_id = {d["source_file"]: d["report_id"] for d in docs}

    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        st.info("No observations yet — process a report first.")
    else:
        c1, c2, c3 = st.columns(3)
        # Filter dropdown shows "ID — filename"; behind the scenes we filter by source_file.
        report_label_to_source = {
            f"{source_to_id[s]} — {s}": s for s in sorted(df.source_file.unique())
        }
        sel_labels = c1.multiselect("Report", list(report_label_to_source.keys()))
        sel_sources = [report_label_to_source[lbl] for lbl in sel_labels]
        dt = c2.multiselect("Defect type", sorted(df.defect_type.unique()))
        sev = c3.multiselect("Severity", sorted(df.severity.unique()))
        if sel_sources:
            df = df[df.source_file.isin(sel_sources)]
        if dt:
            df = df[df.defect_type.isin(dt)]
        if sev:
            df = df[df.severity.isin(sev)]
        st.caption(f"{len(df)} of {len(rows)} observations")
        # Optional columns (building_element, material) are off by default because
        # they're frequently null on procedural / fire-safety reports and just add
        # a column of em-dashes. Toggle on for structural condition assessments.
        show_optional = st.checkbox(
            "Show optional columns (building_element, material)",
            value=False,
            key="browse_show_optional",
        )

        # Build an HTML table so each ID cell can carry a native browser `title=`
        # tooltip — hover shows the full filename, mouseout hides it.
        # Trade-off vs. st.dataframe: no sort / column resize, but tooltip works
        # cross-browser without JS. At a few hundred rows this is fine.
        display_df = pd.DataFrame(index=df.index)
        display_df["report"] = df["source_file"].map(
            lambda f: (
                f'<span title="{html_escape(str(f))}">'
                f'{source_to_id.get(f, "?")}</span>'
            )
        )
        def _cell(v):
            # Render NULL / NaN as em-dash. pd.isna catches None, np.nan, pd.NA.
            # html-escape everything else so verbatim_quote etc. can't break layout.
            if pd.isna(v):
                return "—"
            return html_escape(str(v))

        OPTIONAL_COLS = {"building_element", "material"}
        all_cols = ["page", "defect_type", "building_element", "material",
                    "severity", "confidence", "verbatim_quote"]
        display_cols = all_cols if show_optional else [c for c in all_cols if c not in OPTIONAL_COLS]
        for col in display_cols:
            display_df[col] = df[col].map(_cell)

        st.markdown(
            "<style>"
            ".browse-tbl{font-size:0.875rem;border-collapse:collapse;width:100%;}"
            ".browse-tbl th,.browse-tbl td{border:1px solid #ddd;padding:6px 8px;"
            "text-align:left;vertical-align:top;}"
            ".browse-tbl thead{background:#f5f5f5;}"
            ".browse-tbl span[title]{border-bottom:1px dotted #999;cursor:help;}"
            "</style>",
            unsafe_allow_html=True,
        )
        st.markdown(
            display_df.to_html(escape=False, index=False, border=0,
                               classes="browse-tbl"),
            unsafe_allow_html=True,
        )

elif view == "Analytics":
    st.header("Portfolio analytics")

    # Filter options from current DB state.
    # Report labels include the rowid-based ID for consistency with Browse.
    report_rows = store.sql(
        "SELECT d.rowid AS report_id, d.source_file FROM documents d "
        "WHERE EXISTS (SELECT 1 FROM observations o WHERE o.source_file = d.source_file) "
        "ORDER BY d.rowid"
    )
    report_label_to_source = {
        f"{r['report_id']} — {r['source_file']}": r["source_file"] for r in report_rows
    }
    building_rows = store.sql(
        "SELECT building_id, COALESCE(canonical_address, raw_address) AS name "
        "FROM buildings ORDER BY name"
    )
    building_label_to_id = {b["name"]: b["building_id"] for b in building_rows}

    f1, f2 = st.columns(2)
    sel_report_labels = f1.multiselect("Report", list(report_label_to_source.keys()))
    sel_reports = [report_label_to_source[lbl] for lbl in sel_report_labels]
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

        # Both charts share height + label angle, so the bars sit on the same
        # baseline inside each column — x-axes line up across the two columns.
        CHART_HEIGHT = 350
        LABEL_ANGLE = -30

        defect_df = pd.DataFrame(top).copy()
        defect_df["defect_type"] = defect_df["defect_type"].map(
            lambda x: _DEFECT_SHORT_LABEL.get(x, x)
        )
        chart_defect = alt.Chart(defect_df).mark_bar().encode(
            x=alt.X("defect_type:N", sort="-y",
                    axis=alt.Axis(labelAngle=LABEL_ANGLE, title="defect type")),
            y=alt.Y("n:Q", title="count"),
            tooltip=["defect_type", "n"],
        ).properties(height=CHART_HEIGHT)

        sev_df = pd.DataFrame(sev)
        chart_sev = alt.Chart(sev_df).mark_bar().encode(
            x=alt.X("severity:N", sort="-y",
                    axis=alt.Axis(labelAngle=LABEL_ANGLE, title="severity")),
            y=alt.Y("n:Q", title="count"),
            tooltip=["severity", "n"],
        ).properties(height=CHART_HEIGHT)

        c1, c2 = st.columns(2)
        c1.subheader("Most frequent defect types")
        c1.altair_chart(chart_defect, use_container_width=True)
        c2.subheader("Severity distribution")
        c2.altair_chart(chart_sev, use_container_width=True)

elif view == "Ask":
    st.header("Ask the corpus (semantic)")
    st.caption("For fuzzy/open-ended questions. Use Analytics for exact counts.")
    q = st.text_input("Question", placeholder="Which reports mention chloride-induced corrosion?")
    if q:
        with st.spinner("Retrieving…"):
            res = query.answer_semantic(store, q)
        st.write(res["answer"])
        st.caption("Sources: " + ", ".join(res["sources"]))
