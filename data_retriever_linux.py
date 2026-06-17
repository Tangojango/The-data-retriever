"""
data_retriever_linux.py

Core data processing for Picarro Linux instrument data (PI-series).
Designed for use with a Samba-mounted instrument share.

Scan is instant — reads only directory/filenames, never opens a zip.
Zips are opened only when the user triggers a data load.
Columns are hardcoded: H2O2, H2O, CH4 (plus timestamp/time for the x-axis).
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

        # Root-level zip (recent files not yet moved to a dated folder)
        elif entry.lower().endswith(".zip"):
            meta = parse_filename_metadata(entry)
            if meta:
                entry_serial, entry_dt = meta
                if serial is None:
                    serial = entry_serial
                dates.append(entry_dt)

    # If serial not found from root zips, open one zip inside a dated subfolder
    # and read the h5 filename from the zip's contents.
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

        # Root-level zip (recent)
        elif entry.lower().endswith(".zip"):
            meta = parse_filename_metadata(entry)
            if meta and date_from <= meta[1] <= date_to:
                zips.append(os.path.join(folder_path, entry))

    return zips


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data(
    folder_path: str,
    date_from: datetime,
    date_to: datetime,
) -> Tuple[pd.DataFrame, List[str]]:
    """
    Load H2O2, H2O, CH4 (+ timestamps) for the selected date range.

    Returns (DataFrame, list of zip paths that were read).
    Raises ValueError if no data could be extracted.
    """
    zips = _collect_zips(folder_path, date_from, date_to)
    if not zips:
        raise ValueError("No zip files found for the selected date range.")

    chunks: List[pd.DataFrame] = []
    used_zips: List[str] = []

    warnings.filterwarnings("ignore", category=pd.io.pytables.IncompatibilityWarning)

    for zip_path in zips:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    h5_entries = [e for e in zf.namelist() if e.lower().endswith(".h5")]
                    if not h5_entries:
                        continue
                    zf.extract(h5_entries[0], path=tmp)

                # Find the extracted h5 file (avoids Windows path-separator issues)
                tmp_path: Optional[str] = None
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
                    available = [c for c in _FETCH_COLS if c in chunk.columns]
                    if available:
                        file_chunks.append(chunk[available])

                if file_chunks:
                    chunks.append(pd.concat(file_chunks, ignore_index=True))
                    used_zips.append(zip_path)

        except Exception:
            continue

    warnings.resetwarnings()

    if not chunks:
        raise ValueError(
            "No data extracted. Check that the h5 files contain "
            "H2O2, H2O, or CH4 columns."
        )

    df = pd.concat(chunks, ignore_index=True)
    sort_col = "timestamp" if "timestamp" in df.columns else df.columns[0]
    df.sort_values(by=sort_col, inplace=True, ignore_index=True)
    return df, used_zips


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_to_hdf5(df: pd.DataFrame, h5_path: str) -> None:
    """Write DataFrame to HDF5 using h5py (write-only use of h5py)."""
    records = df.to_records(index=False)
    with h5py.File(h5_path, "w") as hf:
        hf.create_dataset("results", data=records)


def copy_source_files(zip_paths: List[str], dest_dir: str) -> int:
    """
    Copy source zip files to dest_dir for the audit trail.
    Returns the number of files copied.
    """
    os.makedirs(dest_dir, exist_ok=True)
    count = 0
    for zip_path in zip_paths:
        shutil.copy2(zip_path, dest_dir)
        count += 1
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
