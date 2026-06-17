"""
data_retriever_linux.py

Core data processing for Picarro Linux instrument data (PI-series).
Designed for use with a Samba-mounted instrument share.

Scan is instant — reads only directory/filenames, never opens a zip.
Zips are opened only when the user triggers a data load.
Columns are hardcoded: H2O2, H2O, CH4 (plus timestamp/time for the x-axis).

Two data sources are handled transparently:
  Archive  — YYYY-MM-DD/Datalog_Private/*.zip  (historical, zipped)
  Live     — DataLogger/DataLog_Private/*.h5   (recent, plain h5 files)
"""

import io
import os
import re
import shutil
import warnings
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import h5py
import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Columns returned to the UI (time columns are always added automatically)
MEASURE_COLS = ["H2O2", "H2O", "CH4"]
_TIME_COLS = ["timestamp", "time"]
_FETCH_COLS = _TIME_COLS + MEASURE_COLS

# ---------------------------------------------------------------------------
# Filename / folder patterns
# ---------------------------------------------------------------------------

# Matches Picarro filenames: NEDS2155-20260403-214457Z-DataLog_Private
_FILENAME_RE = re.compile(r"^([A-Z0-9]+)-(\d{8})-(\d{6})Z-", re.IGNORECASE)

# Matches dated subfolders: 2026-01-01
_DATE_FOLDER_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Path to live h5 files relative to the share root
_LIVE_SUBPATH = os.path.join("DataLogger", "DataLog_Private")


def parse_filename_metadata(filename: str) -> Optional[Tuple[str, datetime]]:
    """
    Parse serial number and UTC datetime from a Picarro filename (zip or h5).
    Returns (serial, datetime) or None if the name doesn't match.
    """
    stem = os.path.basename(filename).rsplit(".", 1)[0]
    m = _FILENAME_RE.match(stem)
    if not m:
        return None
    serial = m.group(1).upper()
    try:
        dt = datetime.strptime(m.group(2) + m.group(3), "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return serial, dt


# ---------------------------------------------------------------------------
# Scan — instant, no zip opening
# ---------------------------------------------------------------------------

def _find_serial_from_subfolders(folder_path: str, entries: List[str]) -> Tuple[Optional[str], str]:
    """
    Open the first zip in the first plain YYYY-MM-DD/Datalog_Private folder
    and read the serial number from the h5 filename inside the zip.

    Returns (serial_or_None, debug_message).
    """
    log: List[str] = []

    date_folders = sorted(
        e for e in entries
        if _DATE_FOLDER_RE.match(e) and "-RDF" not in e.upper()
    )
    log.append(f"Date folders found: {len(date_folders)}")

    for entry in date_folders[:5]:           # try up to 5 folders
        for subdir in ("Datalog_Private", "DataLog_Private", ""):
            d = os.path.join(folder_path, entry, subdir) if subdir else os.path.join(folder_path, entry)
            if not os.path.isdir(d):
                log.append(f"  {entry}/{subdir} — not found")
                continue

            try:
                zips = sorted(f for f in os.listdir(d) if f.lower().endswith(".zip"))
            except Exception as e:
                log.append(f"  {entry}/{subdir} — listdir error: {e}")
                continue

            log.append(f"  {entry}/{subdir} — {len(zips)} zip(s)")

            for fname in zips[:3]:           # try up to 3 zips per folder
                zip_path = os.path.join(d, fname)
                # First try: parse serial from zip filename itself
                meta = parse_filename_metadata(fname)
                if meta:
                    log.append(f"    {fname} — serial from filename: {meta[0]}")
                    return meta[0], "\n".join(log)

                # Second try: open zip, read h5 entry names
                try:
                    with zipfile.ZipFile(zip_path, "r") as zf:
                        h5_names = [n for n in zf.namelist() if n.lower().endswith(".h5")]
                    log.append(f"    {fname} — {len(h5_names)} h5 entries: {h5_names[:2]}")
                    for h5_name in h5_names:
                        meta = parse_filename_metadata(h5_name)
                        if meta:
                            log.append(f"    matched serial: {meta[0]}")
                            return meta[0], "\n".join(log)
                        else:
                            log.append(f"    no match: {os.path.basename(h5_name)}")
                except Exception as e:
                    log.append(f"    {fname} — zip error: {e}")

    return None, "\n".join(log)


def scan_instrument_folder(folder_path: str) -> Dict:
    """
    Instant scan: reads only directory names and zip filenames.
    No zip files are opened.

    Folder structure handled:
      <folder_path>/YYYY-MM-DD/Datalog_Private/*.zip  (historical)
      <folder_path>/*.zip                              (recent, not yet sorted)

    Returns:
      serial, date_min, date_max, folder_count
    """
    if not os.path.exists(folder_path):
        raise ValueError(f"Folder not found: {folder_path}")

    try:
        entries = os.listdir(folder_path)
    except Exception as e:
        raise ValueError(f"Cannot read folder: {e}")

    dates: List[datetime] = []
    serial: Optional[str] = None

    for entry in entries:
        # Dated subfolder — grab the date from the folder name directly
        if _DATE_FOLDER_RE.match(entry):
            try:
                dates.append(datetime.strptime(entry, "%Y-%m-%d"))
            except ValueError:
                pass

        # Root-level zip — two sub-cases:
        elif entry.lower().endswith(".zip"):
            meta = parse_filename_metadata(entry)
            if meta:
                # Standard Picarro-named zip (SERIAL-DATE-TIME-...)
                entry_serial, entry_dt = meta
                if serial is None:
                    serial = entry_serial
                dates.append(entry_dt)
            else:
                # Non-standard name (e.g. DataLog_Private.zip) — peek inside
                zip_path = os.path.join(folder_path, entry)
                try:
                    with zipfile.ZipFile(zip_path, "r") as zf:
                        h5_names = [n for n in zf.namelist() if n.lower().endswith(".h5")]
                    for h5_name in h5_names:
                        h5_meta = parse_filename_metadata(os.path.basename(h5_name))
                        if h5_meta:
                            h5_serial, h5_dt = h5_meta
                            if serial is None:
                                serial = h5_serial
                            dates.append(h5_dt)
                except Exception:
                    pass

    # Check live folder (DataLogger/DataLog_Private) for recent h5 files
    live_folder = os.path.join(folder_path, _LIVE_SUBPATH)
    live_count = 0
    if os.path.isdir(live_folder):
        try:
            for fname in os.listdir(live_folder):
                if fname.lower().endswith(".h5"):
                    meta = parse_filename_metadata(fname)
                    if meta:
                        entry_serial, entry_dt = meta
                        if serial is None:
                            serial = entry_serial
                        dates.append(entry_dt)
                        live_count += 1
        except Exception:
            pass

    # If serial still not found, open one zip inside a dated subfolder
    if serial is None:
        serial, serial_debug = _find_serial_from_subfolders(folder_path, entries)
    else:
        serial_debug = ""

    if not dates:
        raise ValueError(
            f"No dated folders or Picarro zip files found in: {folder_path}\n"
            "Expected folders named YYYY-MM-DD or zip files named in Picarro format."
        )

    dates.sort()
    folder_count = sum(1 for e in entries if _DATE_FOLDER_RE.match(e))

    return {
        "serial": serial or "UNKNOWN",
        "date_min": dates[0],
        "date_max": dates[-1],
        "folder_count": folder_count,
        "live_count": live_count,
        "folder_path": folder_path,
    }


# ---------------------------------------------------------------------------
# Collect zips for a date range
# ---------------------------------------------------------------------------

def _collect_zips(folder_path: str, date_from: datetime, date_to: datetime) -> List[str]:
    """Return sorted list of zip paths that fall within [date_from, date_to]."""
    zips: List[str] = []

    try:
        entries = os.listdir(folder_path)
    except Exception:
        return zips

    for entry in sorted(entries):
        # Dated subfolder
        if _DATE_FOLDER_RE.match(entry):
            try:
                folder_date = datetime.strptime(entry, "%Y-%m-%d").date()
            except ValueError:
                continue
            if not (date_from.date() <= folder_date <= date_to.date()):
                continue

            # Prefer Datalog_Private subfolder, fall back to dated folder root
            datalog = os.path.join(folder_path, entry, "Datalog_Private")
            search = datalog if os.path.exists(datalog) else os.path.join(folder_path, entry)
            try:
                for fname in sorted(os.listdir(search)):
                    if fname.lower().endswith(".zip"):
                        zips.append(os.path.join(search, fname))
            except Exception:
                continue

        # Root-level zip — two sub-cases:
        elif entry.lower().endswith(".zip"):
            meta = parse_filename_metadata(entry)
            if meta:
                # Standard Picarro-named zip
                if date_from <= meta[1] <= date_to:
                    zips.append(os.path.join(folder_path, entry))
            else:
                # Non-standard name (e.g. DataLog_Private.zip) — peek inside
                zip_path = os.path.join(folder_path, entry)
                try:
                    with zipfile.ZipFile(zip_path, "r") as zf:
                        h5_names = [n for n in zf.namelist() if n.lower().endswith(".h5")]
                    for h5_name in h5_names:
                        h5_meta = parse_filename_metadata(os.path.basename(h5_name))
                        if h5_meta and date_from <= h5_meta[1] <= date_to:
                            zips.append(zip_path)
                            break  # one match is enough to include this zip
                except Exception:
                    pass

    return zips


# ---------------------------------------------------------------------------
# Live h5 collection
# ---------------------------------------------------------------------------

def _collect_live_h5(live_folder: str, date_from: datetime, date_to: datetime) -> List[str]:
    """
    Return sorted list of live h5 file paths whose filename date falls
    within [date_from, date_to].
    """
    h5_files: List[str] = []
    if not os.path.isdir(live_folder):
        return h5_files
    try:
        for fname in sorted(os.listdir(live_folder)):
            if not fname.lower().endswith(".h5"):
                continue
            meta = parse_filename_metadata(fname)
            if meta and date_from <= meta[1] <= date_to:
                h5_files.append(os.path.join(live_folder, fname))
    except Exception:
        pass
    return h5_files


def _read_h5_from_bytes(h5_bytes: bytes) -> Optional[pd.DataFrame]:
    """
    Read selected columns from h5 file content held in memory.
    Uses h5py + BytesIO — no temp file needed.
    """
    try:
        buf = io.BytesIO(h5_bytes)
        with h5py.File(buf, "r") as hf:
            key = next((k for k in ("results", "/results", "data", "/data") if k in hf), None)
            if key is None:
                return None
            grp = hf[key]
            available = [c for c in _FETCH_COLS if c in grp]
            if not available:
                return None
            df = pd.DataFrame({col: grp[col][()] for col in available})
        return df if not df.empty else None
    except Exception:
        return None


def _read_h5_file(h5_path: str) -> Optional[pd.DataFrame]:
    """Read selected columns from a plain (unzipped) h5 file on disk."""
    try:
        with open(h5_path, "rb") as fh:
            return _read_h5_from_bytes(fh.read())
    except Exception:
        return None


def _load_zip(
    zip_path: str,
    date_from: datetime,
    date_to: datetime,
) -> Tuple[str, List[pd.DataFrame]]:
    """
    Worker: open one zip, read matching h5 files into DataFrames.
    Everything stays in memory — no temp files written.
    Returns (zip_path, list_of_dataframes).
    """
    chunks: List[pd.DataFrame] = []
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            all_h5 = [e for e in zf.namelist() if e.lower().endswith(".h5")]
            if not all_h5:
                return zip_path, chunks

            zip_is_standard = parse_filename_metadata(os.path.basename(zip_path)) is not None
            if zip_is_standard:
                h5_to_read = all_h5[:1]
            else:
                h5_to_read = [
                    h for h in all_h5
                    if (lambda m: m is not None and date_from <= m[1] <= date_to)(
                        parse_filename_metadata(os.path.basename(h))
                    )
                ]

            for h5_entry in h5_to_read:
                try:
                    h5_bytes = zf.read(h5_entry)
                    df = _read_h5_from_bytes(h5_bytes)
                    if df is not None:
                        chunks.append(df)
                except Exception:
                    continue
    except Exception:
        pass
    return zip_path, chunks


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data(
    folder_path: str,
    date_from: datetime,
    date_to: datetime,
    progress_cb=None,
) -> Tuple[pd.DataFrame, List[str]]:
    """
    Load H2O2, H2O, CH4 (+ timestamps) for the selected date range.
    Reads from both the archive (zipped) and live (plain h5) sources.

    progress_cb: optional callable(fraction: float, message: str) for UI updates.
    Returns (DataFrame, list of source paths — zips and/or h5 files).
    Raises ValueError if no data could be extracted.
    """
    zips = _collect_zips(folder_path, date_from, date_to)
    live_h5s = _collect_live_h5(
        os.path.join(folder_path, _LIVE_SUBPATH), date_from, date_to
    )

    if not zips and not live_h5s:
        raise ValueError("No data files found for the selected date range.")

    chunks: List[pd.DataFrame] = []
    used_sources: List[str] = []
    total = len(zips) + len(live_h5s)
    done = 0

    def _progress(msg: str) -> None:
        nonlocal done
        done += 1
        if progress_cb:
            progress_cb(done / total, msg)

    # --- Archive: load zips in parallel, all in-memory ---
    with ThreadPoolExecutor(max_workers=4) as pool:
        future_to_zip = {
            pool.submit(_load_zip, zp, date_from, date_to): zp
            for zp in zips
        }
        for future in as_completed(future_to_zip):
            zp, zip_chunks = future.result()
            if zip_chunks:
                chunks.extend(zip_chunks)
                used_sources.append(zp)
            _progress(f"Loaded: {os.path.basename(zp)}")

    # --- Live: read plain h5 files directly ---
    for h5_path in live_h5s:
        df_live = _read_h5_file(h5_path)
        if df_live is not None:
            chunks.append(df_live)
            used_sources.append(h5_path)
        _progress(f"Loaded (live): {os.path.basename(h5_path)}")

    warnings.resetwarnings()

    if not chunks:
        raise ValueError(
            "No data extracted. Check that the files contain "
            "H2O2, H2O, or CH4 columns."
        )

    df = pd.concat(chunks, ignore_index=True)
    sort_col = "timestamp" if "timestamp" in df.columns else df.columns[0]
    df.sort_values(by=sort_col, inplace=True, ignore_index=True)
    return df, used_sources


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_to_hdf5(df: pd.DataFrame, h5_path: str) -> None:
    """Write DataFrame to HDF5 using h5py (write-only use of h5py)."""
    records = df.to_records(index=False)
    with h5py.File(h5_path, "w") as hf:
        hf.create_dataset("results", data=records)


def copy_source_files(source_paths: List[str], dest_dir: str) -> int:
    """
    Copy source files (zips or plain h5) to dest_dir for the audit trail.
    Returns the number of files copied.
    """
    os.makedirs(dest_dir, exist_ok=True)
    count = 0
    for path in source_paths:
        try:
            shutil.copy2(path, dest_dir)
            count += 1
        except Exception:
            continue
    return count


# ---------------------------------------------------------------------------
# Timestamp conversion
# ---------------------------------------------------------------------------

# Picarro timestamp = ms since 0001-01-01 00:00:00
# Unix epoch        = seconds since 1970-01-01 00:00:00
# Offset between origins = 62135596800 seconds
PICARRO_EPOCH_OFFSET_MS = 62_135_596_800_000


def picarro_ts_to_datetime(series: pd.Series) -> pd.Series:
    """Convert a Picarro millisecond timestamp series to UTC datetime."""
    return pd.to_datetime(series - PICARRO_EPOCH_OFFSET_MS, unit="ms", utc=True)


def unix_ts_to_datetime(series: pd.Series) -> pd.Series:
    """Convert a Unix second timestamp series to UTC datetime."""
    return pd.to_datetime(series, unit="s", utc=True)
