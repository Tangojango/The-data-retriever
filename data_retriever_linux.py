"""
data_retriever_linux.py

Core data processing for Picarro Linux instrument data (PI-series).
Designed for use with a Samba-mounted instrument share.

Key design decisions:
  - Dates are parsed from h5 filenames, not from file modification times
    (modification times are unreliable over Samba / after file copy).
  - Data is read with pd.read_hdf(..., key='results') — no h5py for reading.
  - No resampling or interpolation (pharma data integrity requirement).
  - Source zip files are copied to the export folder for audit trail.
"""

import os
import re
import shutil
import tempfile
import warnings
import zipfile
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import h5py
import pandas as pd

# ---------------------------------------------------------------------------
# Filename parsing
# ---------------------------------------------------------------------------

# Matches Picarro h5 filenames such as:
#   NEDS2155-20260403-214457Z-DataLog_Private.h5
_FILENAME_RE = re.compile(
    r"^([A-Z0-9]+)-(\d{8})-(\d{6})Z-.*\.h5$",
    re.IGNORECASE,
)


def parse_filename_metadata(filename: str) -> Optional[Tuple[str, datetime]]:
    """
    Parse the serial number and UTC datetime embedded in a Picarro h5 filename.

    Returns (serial, datetime) or None if the name doesn't match the pattern.
    """
    basename = os.path.basename(filename)
    m = _FILENAME_RE.match(basename)
    if not m:
        return None
    serial = m.group(1).upper()
    try:
        dt = datetime.strptime(m.group(2) + m.group(3), "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return serial, dt


# ---------------------------------------------------------------------------
# Folder scanning
# ---------------------------------------------------------------------------

def scan_instrument_folder(folder_path: str) -> Dict:
    """
    Scan a Picarro Linux instrument data folder for all zipped h5 files.

    Fast two-phase approach:
      Phase 1 — Walk the directory and parse dates/serial from zip filenames.
                 No zip files are opened. Completes in milliseconds even over Samba.
      Phase 2 — Open ONE zip to detect the internal subfolder structure
                 (e.g. 'DataLog_Private/'), then construct all h5 paths from
                 that pattern. Discover columns from the same file.

    Picarro zip and h5 files always share the same base name:
      NEDS2155-20260403-214457Z-DataLog_Private.zip
        └── DataLog_Private/NEDS2155-20260403-214457Z-DataLog_Private.h5

    Raises ValueError if the folder is missing or contains no valid files.
    """
    if not os.path.exists(folder_path):
        raise ValueError(f"Folder not found: {folder_path}")

    # --- Phase 1: collect zip files, parse metadata from filenames only ---
    zip_candidates: List[Dict] = []
    serial: Optional[str] = None

    for root, _dirs, files in os.walk(folder_path):
        for fname in sorted(files):
            if not fname.lower().endswith(".zip"):
                continue
            # Treat the zip as having a matching h5 name
            h5_name = fname[:-4] + ".h5"
            meta = parse_filename_metadata(h5_name)
            if meta is None:
                continue
            entry_serial, entry_dt = meta
            if serial is None:
                serial = entry_serial
            zip_candidates.append(
                {
                    "zip_path": os.path.join(root, fname),
                    "h5_basename": h5_name,
                    "file_date": entry_dt,
                    "serial": entry_serial,
                }
            )

    if not zip_candidates:
        raise ValueError(
            f"No valid Picarro zip files found in: {folder_path}\n"
            "Make sure the folder contains zip archives named in Picarro format "
            "(e.g. NEDS2155-20260403-214457Z-DataLog_Private.zip)."
        )

    zip_candidates.sort(key=lambda x: x["file_date"])

    # --- Phase 2: open ONE zip to learn the internal subfolder structure ---
    h5_prefix = ""
    for candidate in zip_candidates[:5]:
        try:
            with zipfile.ZipFile(candidate["zip_path"], "r") as zf:
                h5_entries = [e for e in zf.namelist() if e.lower().endswith(".h5")]
                if h5_entries:
                    # Extract the directory portion: "DataLog_Private/" or ""
                    sample = h5_entries[0]
                    parts = sample.replace("\\", "/").rsplit("/", 1)
                    h5_prefix = parts[0] + "/" if len(parts) == 2 else ""
                    break
        except Exception:
            continue

    # Build final file list using the detected prefix
    files_list: List[Dict] = [
        {
            "zip_path": c["zip_path"],
            "hdf5_file": h5_prefix + c["h5_basename"],
            "file_date": c["file_date"],
            "serial": c["serial"],
        }
        for c in zip_candidates
    ]

    columns, col_error = _discover_columns(files_list)

    return {
        "serial": serial or "UNKNOWN",
        "date_min": files_list[0]["file_date"],
        "date_max": files_list[-1]["file_date"],
        "file_count": len(files_list),
        "files_list": files_list,
        "columns": columns,
        "col_error": col_error,
    }


# ---------------------------------------------------------------------------
# Column discovery
# ---------------------------------------------------------------------------

def _discover_columns(files_list: List[Dict], max_tries: int = 5) -> Tuple[List[str], str]:
    """
    Read column names from the first readable file in the list.

    Returns (columns, error_message).
    columns is empty and error_message is set if nothing could be read.
    """
    errors = []
    for file_info in files_list[:max_tries]:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with zipfile.ZipFile(file_info["zip_path"], "r") as zf:
                    zf.extract(file_info["hdf5_file"], path=tmp)

                # Walk the temp dir to find the extracted h5 file — avoids
                # path-separator issues on Windows (zip uses /, Windows uses \).
                tmp_path = None
                for root, _dirs, files in os.walk(tmp):
                    for f in files:
                        if f.lower().endswith(".h5"):
                            tmp_path = os.path.join(root, f)
                            break
                    if tmp_path:
                        break

                if tmp_path is None:
                    errors.append(f"{file_info['hdf5_file']}: extracted file not found in temp dir")
                    continue

                # Try common Picarro HDF5 keys
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    for key in ("results", "/results", "data", "/data"):
                        try:
                            df = pd.read_hdf(tmp_path, key=key, start=0, stop=10)
                            return list(df.columns), ""
                        except KeyError:
                            continue
                        except Exception as e:
                            errors.append(f"{file_info['hdf5_file']} key={key}: {e}")
                            break

        except Exception as e:
            errors.append(f"{file_info['zip_path']}: {e}")
            continue

    return [], "\n".join(errors) if errors else "No readable h5 files found."


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

# Columns always included so the time axis is available for plotting.
_TIME_COLS = {"timestamp", "time"}


def load_data(
    files_list: List[Dict],
    columns: List[str],
) -> Tuple[pd.DataFrame, List[Dict]]:
    """
    Load and concatenate the requested columns from the given file list.

    timestamp and time are always included (needed for the chart x-axis)
    even if the user did not select them.

    Returns:
        (DataFrame, list of file_info dicts that were actually read)

    Raises ValueError if nothing could be extracted.
    """
    fetch_cols = list(_TIME_COLS | set(columns))

    chunks: List[pd.DataFrame] = []
    used_files: List[Dict] = []

    warnings.filterwarnings("ignore", category=pd.io.pytables.IncompatibilityWarning)

    for file_info in files_list:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with zipfile.ZipFile(file_info["zip_path"], "r") as zf:
                    zf.extract(file_info["hdf5_file"], path=tmp)

                tmp_path = None
                for root, _dirs, files in os.walk(tmp):
                    for f in files:
                        if f.lower().endswith(".h5"):
                            tmp_path = os.path.join(root, f)
                            break
                    if tmp_path:
                        break

                if tmp_path is None:
                    continue

                file_chunks: List[pd.DataFrame] = []
                for chunk in pd.read_hdf(tmp_path, key="results", iterator=True):
                    available = [c for c in fetch_cols if c in chunk.columns]
                    if available:
                        file_chunks.append(chunk[available])

                if file_chunks:
                    chunks.append(pd.concat(file_chunks, ignore_index=True))
                    used_files.append(file_info)

        except Exception:
            continue

    warnings.resetwarnings()

    if not chunks:
        raise ValueError("No data could be extracted from the selected files.")

    df = pd.concat(chunks, ignore_index=True)
    df.sort_values(
        by="timestamp" if "timestamp" in df.columns else df.columns[0],
        inplace=True,
        ignore_index=True,
    )
    return df, used_files


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_to_hdf5(df: pd.DataFrame, h5_path: str) -> None:
    """Write DataFrame to HDF5 using h5py (write-only use of h5py)."""
    records = df.to_records(index=False)
    with h5py.File(h5_path, "w") as hf:
        hf.create_dataset("results", data=records)


def copy_source_files(files_list: List[Dict], dest_dir: str) -> int:
    """
    Copy unique source zip files to dest_dir for the audit trail.
    Each zip is copied only once even if it contained multiple h5 files.

    Returns the number of zip files copied.
    """
    os.makedirs(dest_dir, exist_ok=True)
    seen: set = set()
    count = 0
    for file_info in files_list:
        zip_path = file_info["zip_path"]
        if zip_path not in seen:
            shutil.copy2(zip_path, dest_dir)
            seen.add(zip_path)
            count += 1
    return count


# ---------------------------------------------------------------------------
# Timestamp conversion
# ---------------------------------------------------------------------------

# Picarro timestamp = ms since 0001-01-01 00:00:00
# Unix epoch        = seconds since 1970-01-01 00:00:00
# Offset            = 62135596800 seconds between the two origins
PICARRO_EPOCH_OFFSET_MS = 62_135_596_800_000  # milliseconds


def picarro_ts_to_datetime(series: pd.Series) -> pd.Series:
    """Convert a Picarro millisecond timestamp series to UTC datetime."""
    unix_ms = series - PICARRO_EPOCH_OFFSET_MS
    return pd.to_datetime(unix_ms, unit="ms", utc=True)


def unix_ts_to_datetime(series: pd.Series) -> pd.Series:
    """Convert a Unix second timestamp series to UTC datetime."""
    return pd.to_datetime(series, unit="s", utc=True)
