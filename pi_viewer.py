"""
pi_viewer.py  —  Picarro Data Viewer for Linux instruments (PI-series)

Run with:
    streamlit run pi_viewer.py

Workflow:
  Step 1  Connect  — pick the instrument data folder, scan for files
  Step 2  Select   — choose date range and columns
  Step 3  View     — interactive Plotly charts, one per column
  Step 4  Export   — CSV + HDF5 + copies of source zips (audit trail)
"""

import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data_retriever_linux import (
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
    """Return a UTC datetime series suitable for chart x-axes."""
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
    "exports_folder": r"Y:\Exports",
    "scan": None,          # result dict from scan_instrument_folder()
    "data_df": None,       # loaded DataFrame
    "used_files": [],      # file_info dicts for loaded data
    "plot_columns": [],    # user-selected columns (excluding time cols)
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

if serial:
    st.title(f"🔬 Picarro Data Viewer  —  {serial}")
else:
    st.title("🔬 Picarro Data Viewer")

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
        placeholder=r"Y:\Data",
    )

with col_browse:
    if st.button("Browse…", use_container_width=True):
        picked = _browse_folder()
        if picked:
            st.session_state.data_folder = picked
            st.rerun()

with col_scan:
    scan_clicked = st.button("🔍 Scan files", type="primary", use_container_width=True)

if scan_clicked:
    if not os.path.exists(data_folder):
        st.error(f"Folder not found: `{data_folder}`")
    else:
        with st.spinner("Scanning…"):
            try:
                result = scan_instrument_folder(data_folder)
                st.session_state.scan = result
                st.session_state.data_folder = data_folder
                # Reset downstream state when re-scanning
                st.session_state.data_df = None
                st.session_state.used_files = []
                st.rerun()
            except ValueError as e:
                st.error(str(e))

# Show scan summary banner
scan = st.session_state.scan
if scan:
    st.success(
        f"**Instrument:** {scan['serial']}  \u2002|\u2002  "
        f"**Files found:** {scan['file_count']}  \u2002|\u2002  "
        f"**Date range:** {scan['date_min'].strftime('%Y-%m-%d')} "
        f"\u2192 {scan['date_max'].strftime('%Y-%m-%d')}"
    )

# ---------------------------------------------------------------------------
# Step 2 — Select (only after a successful scan)
# ---------------------------------------------------------------------------

if scan:
    st.markdown("---")
    st.subheader("Step 2 — Select time range and columns")

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

    # Column selector — pharma defaults pre-checked
    available_cols = scan["columns"]
    pharma_defaults = ["H2O2", "H2O", "CH4"]
    default_selected = [c for c in pharma_defaults if c in available_cols]
    if not default_selected and available_cols:
        default_selected = available_cols[:3]

    # Exclude internal time columns from the picker
    data_cols = [c for c in available_cols if c not in ("timestamp", "time")]
    selected_columns = st.multiselect(
        "Columns to load",
        options=data_cols,
        default=[c for c in default_selected if c in data_cols],
        help="H2O2, H2O and CH4 are pre-selected. Add or remove as needed.",
    )

    load_disabled = not selected_columns
    load_clicked = st.button(
        "📥 Load Data",
        type="primary",
        disabled=load_disabled,
    )

    if load_clicked and selected_columns:
        dt_from = datetime.combine(date_from, datetime.min.time())
        dt_to = datetime.combine(date_to, datetime.max.time())

        filtered = [
            f for f in scan["files_list"]
            if dt_from <= f["file_date"] <= dt_to
        ]

        if not filtered:
            st.warning("No files found in the selected date range.")
        else:
            with st.spinner(f"Loading {len(filtered)} file(s)…"):
                try:
                    df, used = load_data(filtered, selected_columns)
                    st.session_state.data_df = df
                    st.session_state.used_files = used
                    st.session_state.plot_columns = selected_columns
                    st.session_state.date_from = date_from
                    st.session_state.date_to = date_to
                    st.rerun()
                except Exception as exc:
                    st.error(f"Load failed: {exc}")

# ---------------------------------------------------------------------------
# Step 3 — Charts
# ---------------------------------------------------------------------------

if st.session_state.data_df is not None:
    df: pd.DataFrame = st.session_state.data_df
    plot_cols = st.session_state.plot_columns

    st.markdown("---")
    st.subheader(
        f"Step 3 — Data  ({len(df):,} rows · "
        f"{st.session_state.date_from} → {st.session_state.date_to})"
    )

    dt_axis = _datetime_axis(df)

    for col in plot_cols:
        if col not in df.columns:
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
        "Exports a timestamped subfolder containing CSV, HDF5, "
        "and copies of the original source zip files for audit purposes."
    )

    col_epath, col_ebrowse = st.columns([5, 1])
    with col_epath:
        exports_folder = st.text_input(
            "Exports folder",
            value=st.session_state.exports_folder,
            label_visibility="collapsed",
            placeholder=r"Y:\Exports",
        )
    with col_ebrowse:
        if st.button("Browse…", key="browse_exports", use_container_width=True):
            picked = _browse_folder()
            if picked:
                st.session_state.exports_folder = picked
                st.rerun()

    export_clicked = st.button(
        "💾 Export (CSV + HDF5 + source files)",
        type="primary",
    )

    if export_clicked:
        scan = st.session_state.scan
        d_from = st.session_state.date_from
        d_to = st.session_state.date_to
        s = scan["serial"]
        ts_now = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_name = (
            f"{s}_{d_from.strftime('%Y%m%d')}_{d_to.strftime('%Y%m%d')}_{ts_now}"
        )
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
                n_zips = copy_source_files(
                    st.session_state.used_files, str(orig_dir)
                )

                st.success(f"Exported to `{export_dir}`")
                col1, col2, col3 = st.columns(3)
                col1.metric("CSV", f"{csv_path.stat().st_size / 1e6:.1f} MB")
                col2.metric("HDF5", f"{h5_path.stat().st_size / 1e6:.1f} MB")
                col3.metric("Source zips copied", n_zips)

            except Exception as exc:
                st.error(f"Export failed: {exc}")
                st.exception(exc)

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown("---")
st.caption(
    f"Picarro Data Viewer  ·  Instrument: {serial or '—'}  ·  "
    "No data modification — raw values only"
)
