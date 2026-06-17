"""
pi_viewer.py  —  Picarro Data Viewer for Linux instruments (PI-series)

Run with:
    streamlit run pi_viewer.py

Workflow:
  Step 1  Connect  — pick the data folder, scan for date range (instant)
  Step 2  Select   — choose date range, click Load
  Step 3  View     — interactive Plotly charts for H2O2, H2O, CH4
  Step 4  Export   — CSV + HDF5 + copies of source zips (audit trail)
"""

import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data_retriever_linux import (
    MEASURE_COLS,
    copy_source_files,
    export_to_hdf5,
    load_data,
    picarro_ts_to_datetime,
    scan_instrument_folder,
    unix_ts_to_datetime,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Picarro Data Viewer",
    page_icon="🔬",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _browse_folder() -> str | None:
    """Open a native OS folder-picker dialog via tkinter."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", 1)
        folder = filedialog.askdirectory(master=root)
        root.destroy()
        return folder or None
    except Exception:
        return None


def _datetime_axis(df: pd.DataFrame) -> pd.Series:
    """Return a UTC datetime series for chart x-axes."""
    if "timestamp" in df.columns:
        return picarro_ts_to_datetime(df["timestamp"])
    if "time" in df.columns:
        return unix_ts_to_datetime(df["time"])
    return pd.Series(range(len(df)))


# ---------------------------------------------------------------------------
# Session-state initialisation
# ---------------------------------------------------------------------------

defaults = {
    "data_folder": r"Y:\\",
    "exports_folder": r"Y:\\Exports",
    "scan": None,
    "data_df": None,
    "used_zips": [],
    "date_from": None,
    "date_to": None,
}
for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

scan = st.session_state.scan
serial = scan["serial"] if scan else None

st.title(f"🔬 Picarro Data Viewer" + (f"  —  {serial}" if serial else ""))
st.markdown("---")

# ---------------------------------------------------------------------------
# Step 1 — Connect
# ---------------------------------------------------------------------------

st.subheader("Step 1 — Connect to instrument data")

col_path, col_browse, col_scan = st.columns([5, 1, 2])

with col_path:
    data_folder = st.text_input(
        "Data folder",
        value=st.session_state.data_folder,
        label_visibility="collapsed",
        placeholder=r"Y:\\",
    )

with col_browse:
    if st.button("Browse…", use_container_width=True):
        picked = _browse_folder()
        if picked:
            st.session_state.data_folder = picked
            st.rerun()

with col_scan:
    scan_clicked = st.button("🔍 Scan", type="primary", use_container_width=True)

if scan_clicked:
    if not os.path.exists(data_folder):
        st.error(f"Folder not found: `{data_folder}`")
    else:
        with st.spinner("Scanning…"):
            try:
                result = scan_instrument_folder(data_folder)
                st.session_state.scan = result
                st.session_state.data_folder = data_folder
                st.session_state.data_df = None
                st.session_state.used_zips = []
                st.rerun()
            except ValueError as e:
                st.error(str(e))

scan = st.session_state.scan
if scan:
    st.success(
        f"**Instrument:** {scan['serial']}  \u2002|\u2002  "
        f"**Date folders:** {scan['folder_count']}  \u2002|\u2002  "
        f"**Range:** {scan['date_min'].strftime('%Y-%m-%d')} "
        f"\u2192 {scan['date_max'].strftime('%Y-%m-%d')}"
    )
    if not scan.get("serial_found"):
        st.warning(
            "⚠️ Could not detect instrument serial. "
            "Run this in the DataRetriever folder to debug:\n\n"
            "```\npython -c \"from data_retriever_linux import scan_instrument_folder; "
            "r=scan_instrument_folder(r'Y:\\\\'); print(r)\"\n```"
        )

# ---------------------------------------------------------------------------
# Step 2 — Select date range and load
# ---------------------------------------------------------------------------

if scan:
    st.markdown("---")
    st.subheader("Step 2 — Select date range")
    st.caption(f"Will load: **{', '.join(MEASURE_COLS)}**")

    col_from, col_to = st.columns(2)
    with col_from:
        date_from = st.date_input(
            "From",
            value=scan["date_min"].date(),
            min_value=scan["date_min"].date(),
            max_value=scan["date_max"].date(),
        )
    with col_to:
        date_to = st.date_input(
            "To",
            value=scan["date_max"].date(),
            min_value=scan["date_min"].date(),
            max_value=scan["date_max"].date(),
        )

    load_clicked = st.button("📥 Load Data", type="primary")

    if load_clicked:
        dt_from = datetime.combine(date_from, datetime.min.time())
        dt_to = datetime.combine(date_to, datetime.max.time())
        with st.spinner("Loading data…"):
            try:
                df, used_zips = load_data(
                    scan["folder_path"], dt_from, dt_to
                )
                st.session_state.data_df = df
                st.session_state.used_zips = used_zips
                st.session_state.date_from = date_from
                st.session_state.date_to = date_to
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

# ---------------------------------------------------------------------------
# Step 3 — Charts
# ---------------------------------------------------------------------------

if st.session_state.data_df is not None:
    df: pd.DataFrame = st.session_state.data_df

    st.markdown("---")
    st.subheader(
        f"Step 3 — Data  "
        f"({len(df):,} rows · "
        f"{st.session_state.date_from} → {st.session_state.date_to})"
    )

    dt_axis = _datetime_axis(df)

    for col in MEASURE_COLS:
        if col not in df.columns:
            st.info(f"{col} — not found in this dataset, skipping.")
            continue

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=dt_axis,
                y=df[col],
                mode="lines",
                name=col,
                line=dict(width=1),
            )
        )
        fig.update_layout(
            title=dict(text=col, font=dict(size=14)),
            xaxis_title="Time (UTC)",
            yaxis_title=col,
            height=320,
            margin=dict(l=60, r=20, t=40, b=40),
            xaxis=dict(showgrid=True, gridcolor="#e5e5e5"),
            yaxis=dict(showgrid=True, gridcolor="#e5e5e5"),
            plot_bgcolor="#fafafa",
        )
        st.plotly_chart(fig, use_container_width=True)

    # -----------------------------------------------------------------------
    # Step 4 — Export
    # -----------------------------------------------------------------------

    st.markdown("---")
    st.subheader("Step 4 — Export")
    st.caption(
        "Creates a timestamped subfolder with CSV, HDF5, "
        "and copies of the original source zip files."
    )

    col_epath, col_ebrowse = st.columns([5, 1])
    with col_epath:
        exports_folder = st.text_input(
            "Exports folder",
            value=st.session_state.exports_folder,
            label_visibility="collapsed",
            placeholder=r"Y:\\Exports",
        )
    with col_ebrowse:
        if st.button("Browse…", key="browse_exports", use_container_width=True):
            picked = _browse_folder()
            if picked:
                st.session_state.exports_folder = picked
                st.rerun()

    if st.button("💾 Export (CSV + HDF5 + source files)", type="primary"):
        s = st.session_state.scan["serial"]
        d_from = st.session_state.date_from
        d_to = st.session_state.date_to
        ts_now = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_name = f"{s}_{d_from.strftime('%Y%m%d')}_{d_to.strftime('%Y%m%d')}_{ts_now}"
        export_dir = Path(exports_folder) / folder_name
        base_name = f"{s}_{d_from.strftime('%Y%m%d')}_{d_to.strftime('%Y%m%d')}"

        with st.spinner("Exporting…"):
            try:
                export_dir.mkdir(parents=True, exist_ok=True)
                csv_path = export_dir / f"{base_name}.csv"
                h5_path = export_dir / f"{base_name}.h5"
                orig_dir = export_dir / "original_files"

                df.to_csv(csv_path, index=False)
                export_to_hdf5(df, str(h5_path))
                n_zips = copy_source_files(st.session_state.used_zips, str(orig_dir))

                st.success(f"Exported to `{export_dir}`")
                c1, c2, c3 = st.columns(3)
                c1.metric("CSV", f"{csv_path.stat().st_size / 1e6:.1f} MB")
                c2.metric("HDF5", f"{h5_path.stat().st_size / 1e6:.1f} MB")
                c3.metric("Source zips copied", n_zips)

            except Exception as exc:
                st.error(f"Export failed: {exc}")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown("---")
st.caption(
    f"Picarro Data Viewer  ·  {serial or '—'}  ·  Raw values, no modification"
)
