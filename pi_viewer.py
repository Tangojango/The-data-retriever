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

import io
import os
from datetime import datetime, time as dt_time
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

# One distinct color per measurement channel
_TRACE_COLORS = {
    "H2O2": "#1f77b4",
    "H2O":  "#ff7f0e",
    "CH4":  "#2ca02c",
}

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

_DEFAULT_EXPORTS = str(Path.home() / "Documents" / "PI_Exports")

defaults = {
    "data_folder": r"Y:\\",
    "exports_folder": _DEFAULT_EXPORTS,
    "scan": None,
    "data_df": None,
    "used_zips": [],
    "date_from": None,
    "date_to": None,
    "chart_fig": None,
    "report_name": "",
    "sel_min": None,
    "sel_max": None,
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
    live_count = scan.get("live_count", 0)
    live_str = f"  \u2002|\u2002  **Live files:** {live_count}" if live_count else ""
    st.success(
        f"**Instrument:** {scan['serial']}  \u2002|\u2002  "
        f"**Archive folders:** {scan['folder_count']}"
        f"{live_str}  \u2002|\u2002  "
        f"**Range:** {scan['date_min'].strftime('%Y-%m-%d')} "
        f"\u2192 {scan['date_max'].strftime('%Y-%m-%d')}"
    )
    if not live_count:
        st.info(
            "ℹ️ No live data folder detected. Data from the last few hours may not appear yet. "
            "See INSTRUMENT_SETUP.md to enable live data access."
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
        st.caption("From")
        fc1, fc2 = st.columns([3, 2])
        date_from = fc1.date_input(
            "From date", label_visibility="collapsed",
            value=scan["date_min"].date(),
            min_value=scan["date_min"].date(),
            max_value=scan["date_max"].date(),
        )
        time_from = fc2.time_input(
            "From time", label_visibility="collapsed",
            value=dt_time(0, 0, 0),
            step=60,
        )
    with col_to:
        st.caption("To")
        tc1, tc2 = st.columns([3, 2])
        date_to = tc1.date_input(
            "To date", label_visibility="collapsed",
            value=scan["date_max"].date(),
            min_value=scan["date_min"].date(),
            max_value=scan["date_max"].date(),
        )
        time_to = tc2.time_input(
            "To time", label_visibility="collapsed",
            value=dt_time(23, 59, 59),
            step=60,
        )

    load_clicked = st.button("📥 Load Data", type="primary")

    if load_clicked:
        dt_from = datetime.combine(date_from, time_from)
        dt_to = datetime.combine(date_to, time_to)
        progress_bar = st.progress(0)
        status_text = st.empty()
        try:
            def _on_progress(frac: float, msg: str) -> None:
                progress_bar.progress(min(frac, 1.0))
                status_text.caption(msg)

            df, used_zips = load_data(
                scan["folder_path"], dt_from, dt_to,
                progress_cb=_on_progress,
            )
            st.session_state.data_df = df
            st.session_state.used_zips = used_zips
            st.session_state.date_from = date_from
            st.session_state.date_to = date_to
            progress_bar.empty()
            status_text.empty()
            st.rerun()
        except Exception as exc:
            progress_bar.empty()
            status_text.empty()
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

    report_name = st.text_input(
        "Report name (appears in PDF header)",
        value=st.session_state.report_name,
        placeholder="e.g. Stability Run #12 — Line 3",
    )
    st.session_state.report_name = report_name

    dt_axis = _datetime_axis(df)
    available_cols = [c for c in MEASURE_COLS if c in df.columns]

    for col in MEASURE_COLS:
        if col not in df.columns:
            st.info(f"{col} — not found in this dataset, skipping.")

    serial_str = st.session_state.scan["serial"]
    d_from = st.session_state.date_from
    d_to = st.session_state.date_to
    title_line1 = report_name if report_name else "Picarro Data Report"
    title_line2 = (
        f"{serial_str}  ·  "
        f"{d_from.strftime('%Y-%m-%d')} → {d_to.strftime('%Y-%m-%d')}"
    )

    n = len(available_cols)
    fig = make_subplots(
        rows=n, cols=1,
        shared_xaxes=True,
        subplot_titles=available_cols,
        vertical_spacing=0.06,
    )
    for i, col in enumerate(available_cols, start=1):
        fig.add_trace(
            go.Scatter(
                x=dt_axis,
                y=df[col],
                mode="lines",
                name=col,
                line=dict(width=1.5, color=_TRACE_COLORS.get(col, "#444")),
            ),
            row=i, col=1,
        )
        fig.update_yaxes(
            title_text=col,
            showgrid=True, gridcolor="#e5e5e5",
            row=i, col=1,
        )

    fig.update_xaxes(
        title_text="Time (UTC)",
        showgrid=True, gridcolor="#e5e5e5",
        row=n, col=1,
    )
    fig.update_layout(
        title=dict(
            text=f"<b>{title_line1}</b><br><sup>{title_line2}</sup>",
            x=0.5,
            xanchor="center",
            font=dict(size=15),
        ),
        height=280 * n,
        margin=dict(l=60, r=20, t=80, b=40),
        plot_bgcolor="#fafafa",
        paper_bgcolor="white",
        template="plotly_white",
        showlegend=False,
    )
    chart_event = st.plotly_chart(
        fig,
        key="chart_select",
        on_select="rerun",
        selection_mode=["box"],
        width="stretch",
    )
    st.session_state.chart_fig = fig

    # --- Selection range display ---
    pts = (chart_event.selection or {}).get("points", []) if chart_event else []
    if pts:
        x_vals = sorted([p["x"] for p in pts if "x" in p])
        st.session_state.sel_min = x_vals[0]
        st.session_state.sel_max = x_vals[-1]

    sel_min = st.session_state.get("sel_min")
    sel_max = st.session_state.get("sel_max")

    if sel_min and sel_max:
        st.caption("📌 Selection — use the Box Select tool (□) in the chart toolbar to update")
        sc1, sc2, sc3 = st.columns([3, 3, 1])
        sel_from_str = sc1.text_input("Selected from", value=str(sel_min), key="sel_from_text")
        sel_to_str   = sc2.text_input("Selected to",   value=str(sel_max), key="sel_to_text")
        if sc3.button("✕ Clear", key="clear_sel"):
            st.session_state.sel_min = None
            st.session_state.sel_max = None
            st.rerun()
    else:
        st.caption("💡 Use the Box Select tool (□) in the chart toolbar to select a sub-range for export.")

    # -----------------------------------------------------------------------
    # Step 4 — Export
    # -----------------------------------------------------------------------

    st.markdown("---")
    st.subheader("Step 4 — Export")
    st.caption(
        "Creates a timestamped subfolder with CSV, HDF5, "
        "and copies of the original source files."
    )

    col_epath, col_ebrowse = st.columns([5, 1])
    with col_epath:
        exports_folder = st.text_input(
            "Exports folder",
            value=st.session_state.exports_folder,
            label_visibility="collapsed",
            placeholder=_DEFAULT_EXPORTS,
        )
    with col_ebrowse:
        if st.button("Browse…", key="browse_exports", use_container_width=True):
            picked = _browse_folder()
            if picked:
                st.session_state.exports_folder = picked
                st.rerun()

    col_exp, col_pdf = st.columns([3, 1])

    with col_exp:
        sel_active = bool(st.session_state.get("sel_min") and st.session_state.get("sel_max"))
        btn_label = "💾 Export selected range" if sel_active else "💾 Export (CSV + HDF5 + source files)"
        if st.button(btn_label, type="primary", use_container_width=True):
            s = st.session_state.scan["serial"]
            d_from = st.session_state.date_from
            d_to = st.session_state.date_to
            ts_now = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Filter DataFrame to selection if active
            df_export = df
            if sel_active:
                try:
                    dt_axis_full = _datetime_axis(df)
                    sel_from_dt = pd.to_datetime(
                        st.session_state.get("sel_from_text") or st.session_state.sel_min,
                        utc=True
                    )
                    sel_to_dt = pd.to_datetime(
                        st.session_state.get("sel_to_text") or st.session_state.sel_max,
                        utc=True
                    )
                    mask = (dt_axis_full >= sel_from_dt) & (dt_axis_full <= sel_to_dt)
                    df_export = df[mask].reset_index(drop=True)
                    d_from_str = sel_from_dt.strftime("%Y%m%d_%H%M")
                    d_to_str   = sel_to_dt.strftime("%Y%m%d_%H%M")
                except Exception:
                    df_export = df
                    d_from_str = d_from.strftime("%Y%m%d")
                    d_to_str   = d_to.strftime("%Y%m%d")
            else:
                d_from_str = d_from.strftime("%Y%m%d")
                d_to_str   = d_to.strftime("%Y%m%d")

            folder_name = f"{s}_{d_from_str}_{d_to_str}_{ts_now}"
            export_dir = Path(exports_folder) / folder_name
            base_name  = f"{s}_{d_from_str}_{d_to_str}"

            with st.spinner("Exporting…"):
                try:
                    export_dir.mkdir(parents=True, exist_ok=True)
                    csv_path = export_dir / f"{base_name}.csv"
                    h5_path  = export_dir / f"{base_name}.h5"
                    orig_dir = export_dir / "original_files"

                    df_export.to_csv(csv_path, index=False)
                    export_to_hdf5(df_export, str(h5_path))
                    n_src = copy_source_files(st.session_state.used_zips, str(orig_dir))

                    st.success(f"Exported {len(df_export):,} rows to `{export_dir}`")
                    c1, c2, c3 = st.columns(3)
                    c1.metric("CSV", f"{csv_path.stat().st_size / 1e6:.1f} MB")
                    c2.metric("HDF5", f"{h5_path.stat().st_size / 1e6:.1f} MB")
                    c3.metric("Source files copied", n_src)

                except Exception as exc:
                    st.error(f"Export failed: {exc}")

    with col_pdf:
        chart_fig = st.session_state.get("chart_fig")
        if chart_fig is not None:
            try:
                pdf_bytes = chart_fig.to_image(format="pdf")
                s = st.session_state.scan["serial"]
                d_from = st.session_state.date_from
                d_to = st.session_state.date_to
                pdf_name = f"{s}_{d_from.strftime('%Y%m%d')}_{d_to.strftime('%Y%m%d')}.pdf"
                st.download_button(
                    "📄 Download PDF",
                    data=pdf_bytes,
                    file_name=pdf_name,
                    mime="application/pdf",
                    use_container_width=True,
                )
            except Exception as pdf_err:
                st.error(f"PDF export failed: {pdf_err}")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown("---")
st.caption(
    f"Picarro Data Viewer  ·  {serial or '—'}  ·  Raw values, no modification"
)
