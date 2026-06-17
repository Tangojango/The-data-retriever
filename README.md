# Picarro Data Viewer — Linux Instrument Edition

Streamlit app for reviewing Picarro instrument data from a Samba-mounted Linux share.

## What it does

1. **Scan** the instrument data folder — discovers all zipped h5 files, reads the date range and instrument serial number from filenames (not file modification times).
2. **Select** a date range and which measurement columns to load (H2O2, H2O, CH4 pre-selected).
3. **View** interactive charts — one per column, full timestamp resolution, no resampling.
4. **Export** — CSV + HDF5 of the selected data, plus copies of the original source zip files for audit / data-integrity verification.

## Folder structure expected on the instrument share

```
Y:\Data\
├── *.zip                              ← recent files (not yet sorted into date folders)
└── YYYY-MM-DD\
    └── Datalog_Private\
        └── *.zip                      ← historical files
```

## Setup (Windows — first time)

```bat
conda env create -f environment_linux.yml
```

Creates the `linux-viewer` conda environment with all required packages.

## Running the app

Double-click **`run.bat`**, or from the command line:

```bat
conda activate linux-viewer
streamlit run pi_viewer.py
```

The app opens in your default browser at `http://localhost:8501`.

## Files

| File | Purpose |
|---|---|
| `pi_viewer.py` | Streamlit UI — all four steps |
| `data_retriever_linux.py` | Core data functions (scanning, loading, export) |
| `environment_linux.yml` | Conda environment (cross-platform) |
| `requirements_linux.txt` | pip-only alternative |
| `run.bat` | Windows one-click launcher |

## Design constraints

- **No resampling, no interpolation** — raw rows only.
- Dates are parsed from h5 filenames (`NEDS2155-20260403-214457Z-DataLog_Private.h5`), not from file modification times.
- Data is read with `pd.read_hdf(..., key='results')` — no h5py for data reading.
- Source zip files are copied alongside the export so the original data can always be verified against the instrument.
