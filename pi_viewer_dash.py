"""
pi_viewer_dash.py  —  Picarro Data Viewer for Linux instruments (PI-series)

Run with:
    python pi_viewer_dash.py
then open http://127.0.0.1:8050 in your browser.

Workflow:
  Step 1  Connect  — pick the data folder, scan for date range (instant)
  Step 2  Select   — choose date + time range, click Load
  Step 3  View     — interactive Plotly charts; draw a box to select export range
  Step 4  Export   — CSV + HDF5 + copies of source files + PDF download
"""

import io
import json
import os
import uuid
from datetime import date, datetime, time as dt_time
from pathlib import Path

import dash
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, callback, dcc, html, no_update
from dash.exceptions import PreventUpdate
from plotly.subplots import make_subplots

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
# Constants
# ---------------------------------------------------------------------------

_TRACE_COLORS = {"H2O2": "#1f77b4", "H2O": "#ff7f0e", "CH4": "#2ca02c"}
_DEFAULT_EXPORTS = str(Path.home() / "Documents" / "PI_Exports")
_DEFAULT_DATA_FOLDER = r"Y:\\"

# Server-side cache — DataFrames are too large to round-trip through dcc.Store JSON
_DATA_CACHE: dict = {}  # data_key → {"df", "used_sources", "d_from", "d_to", "serial"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _browse_folder() -> str | None:
    """Open a native OS folder-picker via tkinter."""
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
    if "timestamp" in df.columns:
        return picarro_ts_to_datetime(df["timestamp"])
    if "time" in df.columns:
        return unix_ts_to_datetime(df["time"])
    return pd.Series(range(len(df)))


def _zoom_range_from_relayout(relayout_data: dict | None):
    """Extract (x_min_str, x_max_str) from Plotly relayoutData after a zoom, or (None, None)."""
    if not relayout_data:
        return None, None
    # Standard format from mouse zoom
    x0 = relayout_data.get("xaxis.range[0]")
    x1 = relayout_data.get("xaxis.range[1]")
    if x0 and x1:
        return str(x0), str(x1)
    # Array format
    rng = relayout_data.get("xaxis.range")
    if rng and len(rng) >= 2:
        return str(rng[0]), str(rng[1])
    return None, None


def _filter_df_to_range(df: pd.DataFrame, x_from: str, x_to: str):
    """Return df filtered to [x_from, x_to] (both UTC strings). Returns full df on error."""
    try:
        dt_axis = _datetime_axis(df)
        if hasattr(dt_axis, "dt") and dt_axis.dt.tz is None:
            dt_axis = dt_axis.dt.tz_localize("UTC")

        def _to_utc(s):
            t = pd.to_datetime(s)
            return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")

        mask = (dt_axis >= _to_utc(x_from)) & (dt_axis <= _to_utc(x_to))
        result = df[mask].reset_index(drop=True)
        return result if not result.empty else df
    except Exception as e:
        print(f"[filter] failed: {e}")
        return df


def _build_figure(
    df: pd.DataFrame,
    serial: str,
    d_from: str,
    d_to: str,
    report_name: str = "",
) -> go.Figure:
    dt_axis = _datetime_axis(df)
    available_cols = [c for c in MEASURE_COLS if c in df.columns]
    n = len(available_cols)
    if n == 0:
        return go.Figure()

    title_line1 = report_name.strip() or "Picarro Data Report"
    title_line2 = f"{serial}  ·  {d_from} → {d_to}"

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
            title_text=col, showgrid=True, gridcolor="#e5e5e5",
            row=i, col=1,
        )
    fig.update_xaxes(
        title_text="Time (UTC)", showgrid=True, gridcolor="#e5e5e5",
        row=n, col=1,
    )
    fig.update_layout(
        title=dict(
            text=f"<b>{title_line1}</b><br><sup>{title_line2}</sup>",
            x=0.5, xanchor="center", font=dict(size=15),
        ),
        height=280 * n,
        margin=dict(l=60, r=20, t=80, b=40),
        plot_bgcolor="#fafafa",
        paper_bgcolor="white",
        template="plotly_white",
        showlegend=False,
        dragmode="zoom",  # default: drag to zoom; use □ toolbar button for box select
    )
    return fig


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    title="Picarro Data Viewer",
)

app.layout = dbc.Container([

    # ── Header ────────────────────────────────────────────────────────────
    dbc.Row(dbc.Col(html.H3([
        "🔬 Picarro Data Viewer",
        html.Span(id="header-serial", className="text-muted ms-3 fs-5"),
    ])), className="mt-3 mb-1"),
    html.Hr(className="mt-1"),

    # ── Step 1: Connect ───────────────────────────────────────────────────
    dbc.Card([
        dbc.CardHeader(html.Strong("Step 1 — Connect to instrument data")),
        dbc.CardBody([
            dbc.Row([
                dbc.Col(
                    dbc.Input(
                        id="folder-input",
                        value=_DEFAULT_DATA_FOLDER,
                        placeholder=r"Y:\\",
                        debounce=True,
                    ),
                    width=8,
                ),
                dbc.Col(
                    dbc.Button("Browse…", id="browse-data-btn",
                               color="secondary", className="w-100"),
                    width=2,
                ),
                dbc.Col(
                    dbc.Button("🔍 Scan", id="scan-btn",
                               color="primary", className="w-100"),
                    width=2,
                ),
            ], className="mb-2 g-2"),
            dcc.Loading(html.Div(id="scan-result"), type="circle"),
        ]),
    ], className="mb-3"),

    # ── Step 2: Date + time range ─────────────────────────────────────────
    dbc.Card(id="step2-card", style={"display": "none"}, children=[
        dbc.CardHeader(html.Strong("Step 2 — Select date range")),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.Label("From", className="fw-semibold"),
                    dbc.Row([
                        dbc.Col(
                            dcc.DatePickerSingle(
                                id="date-from",
                                display_format="YYYY-MM-DD",
                                className="w-100",
                            ),
                            width=7,
                        ),
                        dbc.Col(
                            dbc.Input(id="time-from", type="time",
                                      value="00:00", className="w-100"),
                            width=5,
                        ),
                    ], className="g-1"),
                ]),
                dbc.Col([
                    html.Label("To", className="fw-semibold"),
                    dbc.Row([
                        dbc.Col(
                            dcc.DatePickerSingle(
                                id="date-to",
                                display_format="YYYY-MM-DD",
                                className="w-100",
                            ),
                            width=7,
                        ),
                        dbc.Col(
                            dbc.Input(id="time-to", type="time",
                                      value="23:59", className="w-100"),
                            width=5,
                        ),
                    ], className="g-1"),
                ]),
            ], className="mb-3"),
            dcc.Loading(
                [
                    dbc.Button("📥 Load Data", id="load-btn",
                               color="primary", className="me-2"),
                    html.Div(id="load-status", className="mt-2"),
                ],
                type="circle",
            ),
        ]),
    ], className="mb-3"),

    # ── Step 3: Charts ────────────────────────────────────────────────────
    dbc.Card(id="step3-card", style={"display": "none"}, children=[
        dbc.CardHeader(html.Strong("Step 3 — View data")),
        dbc.CardBody([
            dbc.Row([
                dbc.Col(
                    dbc.Input(
                        id="report-name",
                        placeholder="Report name (e.g. Stability Run #12 — Line 3)",
                        debounce=True,
                    ),
                    width=8,
                ),
                dbc.Col(
                    html.Small(
                        "💡 Drag to zoom. Click □ in the chart toolbar to switch to Box Select, "
                        "then draw a range to enable selective export.",
                        className="text-muted fst-italic",
                    ),
                    width=4, className="d-flex align-items-center",
                ),
            ], className="mb-3"),

            dcc.Loading(
                dcc.Graph(
                    id="main-chart",
                    config={
                        "modeBarButtonsToAdd": ["select2d"],
                        "displayModeBar": True,
                        "scrollZoom": True,
                    },
                ),
                type="circle",
            ),

            # Selection range display
            dbc.Row(id="sel-row", style={"display": "none"}, children=[
                dbc.Col(
                    dbc.InputGroup([
                        dbc.InputGroupText("From"),
                        dbc.Input(id="sel-from", type="text", debounce=True),
                    ]),
                    width=5,
                ),
                dbc.Col(
                    dbc.InputGroup([
                        dbc.InputGroupText("To"),
                        dbc.Input(id="sel-to", type="text", debounce=True),
                    ]),
                    width=5,
                ),
                dbc.Col(
                    dbc.Button("✕ Clear", id="clear-sel-btn",
                               color="outline-secondary", size="sm"),
                    width=2, className="d-flex align-items-center",
                ),
            ], className="mt-2 g-2"),
        ]),
    ], className="mb-3"),

    # ── Step 4: Export ────────────────────────────────────────────────────
    dbc.Card(id="step4-card", style={"display": "none"}, children=[
        dbc.CardHeader(html.Strong("Step 4 — Export")),
        dbc.CardBody([
            dbc.Row([
                dbc.Col(
                    dbc.Input(
                        id="export-folder",
                        value=_DEFAULT_EXPORTS,
                        placeholder=_DEFAULT_EXPORTS,
                        debounce=True,
                    ),
                    width=10,
                ),
                dbc.Col(
                    dbc.Button("Browse…", id="browse-export-btn",
                               color="secondary", className="w-100"),
                    width=2,
                ),
            ], className="mb-3 g-2"),

            dbc.Row([
                dbc.Col(
                    dbc.Button(
                        "💾 Export (CSV + HDF5 + source files)",
                        id="export-btn", color="primary", className="w-100",
                    ),
                    width=9,
                ),
                dbc.Col(
                    dbc.Button(
                        "📄 Download PDF",
                        id="pdf-btn", color="info", className="w-100",
                    ),
                    width=3,
                ),
            ], className="mb-3 g-2"),

            dcc.Loading(html.Div(id="export-result"), type="circle"),
            dcc.Download(id="pdf-download"),
        ]),
    ], className="mb-3"),

    # ── Stores ────────────────────────────────────────────────────────────
    dcc.Store(id="scan-store"),      # scan metadata (small, JSON-safe)
    dcc.Store(id="data-key-store"),  # key into _DATA_CACHE

    # ── Footer ────────────────────────────────────────────────────────────
    html.Hr(),
    dbc.Row(dbc.Col(
        html.Small("Picarro Data Viewer · Raw values, no modification",
                   className="text-muted"),
    ), className="mb-4"),

], fluid=True)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

# ── 1. Browse data folder ─────────────────────────────────────────────────
@callback(
    Output("folder-input", "value"),
    Input("browse-data-btn", "n_clicks"),
    prevent_initial_call=True,
)
def cb_browse_data(n_clicks):
    folder = _browse_folder()
    return folder if folder else no_update


# ── 2. Scan ───────────────────────────────────────────────────────────────
@callback(
    Output("scan-store", "data"),
    Output("scan-result", "children"),
    Output("step2-card", "style"),
    Output("date-from", "date"),
    Output("date-from", "min_date_allowed"),
    Output("date-from", "max_date_allowed"),
    Output("date-to", "date"),
    Output("date-to", "min_date_allowed"),
    Output("date-to", "max_date_allowed"),
    Output("header-serial", "children"),
    Input("scan-btn", "n_clicks"),
    State("folder-input", "value"),
    prevent_initial_call=True,
)
def cb_scan(n_clicks, folder):
    if not folder:
        return (no_update,) * 10

    if not os.path.exists(folder):
        alert = dbc.Alert(f"Folder not found: {folder}", color="danger")
        return None, alert, {"display": "none"}, *([no_update] * 7)

    try:
        scan = scan_instrument_folder(folder)
    except ValueError as e:
        alert = dbc.Alert(str(e), color="danger")
        return None, alert, {"display": "none"}, *([no_update] * 7)

    d_min = scan["date_min"].date()
    d_max = scan["date_max"].date()
    live_count = scan.get("live_count", 0)
    live_badge = (
        dbc.Badge(f"Live: {live_count} files", color="success", className="ms-2")
        if live_count else ""
    )
    no_live_msg = (
        dbc.Alert(
            "No live data folder detected. See INSTRUMENT_SETUP.md to enable live access.",
            color="info", className="mt-2 mb-0 py-1",
        ) if not live_count else ""
    )
    result = html.Div([
        dbc.Alert([
            html.Strong(f"Instrument: {scan['serial']}"),
            f"  ·  Archive folders: {scan['folder_count']}",
            live_badge,
            f"  ·  Range: {d_min} → {d_max}",
        ], color="success", className="mb-1"),
        no_live_msg,
    ])

    # Serialise scan for dcc.Store (dates → strings)
    scan_json = {
        "serial": scan["serial"],
        "date_min": str(d_min),
        "date_max": str(d_max),
        "folder_count": scan["folder_count"],
        "live_count": live_count,
        "folder_path": scan["folder_path"],
    }

    return (
        scan_json,
        result,
        {"display": "block"},
        d_min, d_min, d_max,
        d_max, d_min, d_max,
        f"— {scan['serial']}",
    )


# ── 3. Load data ──────────────────────────────────────────────────────────
@callback(
    Output("data-key-store", "data"),
    Output("load-status", "children"),
    Output("step3-card", "style"),
    Output("step4-card", "style"),
    Input("load-btn", "n_clicks"),
    State("scan-store", "data"),
    State("date-from", "date"),
    State("time-from", "value"),
    State("date-to", "date"),
    State("time-to", "value"),
    prevent_initial_call=True,
)
def cb_load(n_clicks, scan_data, date_from, time_from, date_to, time_to):
    if not scan_data or not date_from or not date_to:
        raise PreventUpdate

    try:
        d_from = date.fromisoformat(date_from)
        d_to   = date.fromisoformat(date_to)
        t_from = dt_time.fromisoformat(time_from or "00:00")
        t_to   = dt_time.fromisoformat(time_to   or "23:59")
    except ValueError as e:
        return no_update, dbc.Alert(str(e), color="danger"), no_update, no_update

    dt_from = datetime.combine(d_from, t_from)
    dt_to   = datetime.combine(d_to,   t_to)

    try:
        df, used_sources = load_data(scan_data["folder_path"], dt_from, dt_to)
    except Exception as e:
        return no_update, dbc.Alert(str(e), color="danger"), no_update, no_update

    data_key = str(uuid.uuid4())
    _DATA_CACHE[data_key] = {
        "df": df,
        "used_sources": used_sources,
        "d_from": str(d_from),
        "d_to":   str(d_to),
        "serial": scan_data["serial"],
    }

    status = dbc.Alert(
        f"Loaded {len(df):,} rows · {d_from} {t_from.strftime('%H:%M')} "
        f"→ {d_to} {t_to.strftime('%H:%M')}",
        color="success", className="mb-0 py-1",
    )
    return data_key, status, {"display": "block"}, {"display": "block"}


# ── 4. Build / rebuild chart ──────────────────────────────────────────────
@callback(
    Output("main-chart", "figure"),
    Input("data-key-store", "data"),
    Input("report-name", "value"),
    prevent_initial_call=True,
)
def cb_chart(data_key, report_name):
    if not data_key or data_key not in _DATA_CACHE:
        raise PreventUpdate
    entry = _DATA_CACHE[data_key]
    return _build_figure(
        entry["df"], entry["serial"],
        entry["d_from"], entry["d_to"],
        report_name or "",
    )


# ── 5. Selection → fill range fields ─────────────────────────────────────
@callback(
    Output("sel-from", "value"),
    Output("sel-to", "value"),
    Output("sel-row", "style"),
    Input("main-chart", "selectedData"),
    prevent_initial_call=True,
)
def cb_selection(selected_data):
    if not selected_data or not selected_data.get("points"):
        raise PreventUpdate
    x_vals = sorted([p["x"] for p in selected_data["points"] if "x" in p])
    if not x_vals:
        raise PreventUpdate
    return x_vals[0], x_vals[-1], {"display": "flex"}


# ── 6. Clear selection ────────────────────────────────────────────────────
@callback(
    Output("sel-from", "value", allow_duplicate=True),
    Output("sel-to",   "value", allow_duplicate=True),
    Output("sel-row",  "style", allow_duplicate=True),
    Input("clear-sel-btn", "n_clicks"),
    prevent_initial_call=True,
)
def cb_clear_sel(n_clicks):
    return "", "", {"display": "none"}


# ── 7. Browse export folder ───────────────────────────────────────────────
@callback(
    Output("export-folder", "value"),
    Input("browse-export-btn", "n_clicks"),
    prevent_initial_call=True,
)
def cb_browse_export(n_clicks):
    folder = _browse_folder()
    return folder if folder else no_update


# ── 8. Export ─────────────────────────────────────────────────────────────
@callback(
    Output("export-result", "children"),
    Input("export-btn", "n_clicks"),
    State("data-key-store", "data"),
    State("export-folder", "value"),
    State("sel-from", "value"),
    State("sel-to",   "value"),
    State("main-chart", "relayoutData"),
    prevent_initial_call=True,
)
def cb_export(n_clicks, data_key, export_folder, sel_from, sel_to, relayout_data):
    if not data_key or data_key not in _DATA_CACHE:
        raise PreventUpdate

    entry  = _DATA_CACHE[data_key]
    df     = entry["df"]
    serial = entry["serial"]
    d_from = entry["d_from"]
    d_to   = entry["d_to"]

    # Determine range: box selection > zoom > full
    x_from = (sel_from if sel_from and sel_to else None) or _zoom_range_from_relayout(relayout_data)[0]
    x_to   = (sel_to   if sel_from and sel_to else None) or _zoom_range_from_relayout(relayout_data)[1]

    df_export = df
    d_from_str = d_from.replace("-", "")
    d_to_str   = d_to.replace("-", "")

    if x_from and x_to:
        df_export = _filter_df_to_range(df, x_from, x_to)
        try:
            d_from_str = pd.to_datetime(x_from).strftime("%Y%m%d_%H%M")
            d_to_str   = pd.to_datetime(x_to).strftime("%Y%m%d_%H%M")
        except Exception:
            pass

    ts_now     = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder_name = f"{serial}_{d_from_str}_{d_to_str}_{ts_now}"
    export_dir  = Path(export_folder or _DEFAULT_EXPORTS) / folder_name
    base_name   = f"{serial}_{d_from_str}_{d_to_str}"

    try:
        export_dir.mkdir(parents=True, exist_ok=True)
        csv_path = export_dir / f"{base_name}.csv"
        h5_path  = export_dir / f"{base_name}.h5"
        orig_dir = export_dir / "original_files"

        df_export.to_csv(csv_path, index=False)
        export_to_hdf5(df_export, str(h5_path))
        n_src = copy_source_files(entry["used_sources"], str(orig_dir))

        return dbc.Alert([
            html.Strong(f"Exported {len(df_export):,} rows"),
            html.Br(),
            html.Code(str(export_dir)),
            html.Br(),
            dbc.Badge(f"CSV {csv_path.stat().st_size / 1e6:.1f} MB",
                      color="primary", className="me-1"),
            dbc.Badge(f"HDF5 {h5_path.stat().st_size / 1e6:.1f} MB",
                      color="primary", className="me-1"),
            dbc.Badge(f"{n_src} source files copied",
                      color="secondary"),
        ], color="success")
    except Exception as e:
        return dbc.Alert(f"Export failed: {e}", color="danger")


# ── 9. PDF download ───────────────────────────────────────────────────────
@callback(
    Output("pdf-download", "data"),
    Input("pdf-btn", "n_clicks"),
    State("data-key-store", "data"),
    State("report-name", "value"),
    State("sel-from", "value"),
    State("sel-to",   "value"),
    State("main-chart", "relayoutData"),
    prevent_initial_call=True,
)
def cb_pdf(n_clicks, data_key, report_name, sel_from, sel_to, relayout_data):
    if not data_key or data_key not in _DATA_CACHE:
        raise PreventUpdate

    entry  = _DATA_CACHE[data_key]
    df     = entry["df"]
    serial = entry["serial"]
    d_from = entry["d_from"]
    d_to   = entry["d_to"]

    # Determine range: box selection > zoom > full
    x_from = (sel_from if sel_from and sel_to else None) or _zoom_range_from_relayout(relayout_data)[0]
    x_to   = (sel_to   if sel_from and sel_to else None) or _zoom_range_from_relayout(relayout_data)[1]

    df_pdf = df
    d_from_pdf, d_to_pdf = d_from, d_to
    if x_from and x_to:
        df_pdf = _filter_df_to_range(df, x_from, x_to)
        try:
            d_from_pdf = pd.to_datetime(x_from).strftime("%Y-%m-%d %H:%M")
            d_to_pdf   = pd.to_datetime(x_to).strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass

    fig = _build_figure(df_pdf, serial, d_from_pdf, d_to_pdf, report_name or "")

    try:
        pdf_bytes = fig.to_image(format="pdf")
        filename  = f"{serial}_{d_from.replace('-','')}_{d_to.replace('-','')}.pdf"
        return dcc.send_bytes(pdf_bytes, filename)
    except Exception as e:
        raise PreventUpdate


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import webbrowser
    webbrowser.open("http://127.0.0.1:8050")
    app.run(debug=False, host="127.0.0.1", port=8050)
