@echo off
REM Picarro Data Viewer — Pharma Edition
REM Activates the conda environment and launches the Streamlit app.
REM Place this file in the same folder as pharma_app.py.

call conda activate linux-viewer
if errorlevel 1 (
    echo.
    echo ERROR: Could not activate the "linux-viewer" conda environment.
    echo Please run the setup steps first:
    echo   conda env create -f environment_linux.yml
    echo.
    pause
    exit /b 1
)

streamlit run "%~dp0pi_viewer.py"
pause
