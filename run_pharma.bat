@echo off
REM Picarro Data Viewer — Pharma Edition
REM Activates the conda environment and launches the Streamlit app.
REM Place this file in the same folder as pharma_app.py.

call conda activate picarro-pharma
if errorlevel 1 (
    echo.
    echo ERROR: Could not activate the "picarro-pharma" conda environment.
    echo Please run the setup steps first:
    echo   conda env create -f environment_pharma.yml
    echo.
    pause
    exit /b 1
)

streamlit run "%~dp0pharma_app.py"
pause
