@echo off
REM Picarro Data Viewer — Linux Instrument Edition
REM -----------------------------------------------
REM If conda is not found automatically, set CONDA_BASE manually below.
REM Uncomment the line that matches your installation, or set the correct path.
REM
REM   set CONDA_BASE=C:\ProgramData\miniconda3
REM   set CONDA_BASE=C:\ProgramData\Anaconda3
REM   set CONDA_BASE=%USERPROFILE%\miniconda3
REM   set CONDA_BASE=%USERPROFILE%\Anaconda3
REM   set CONDA_BASE=C:\miniconda3

set CONDA_BASE=

REM --- Auto-detect conda if CONDA_BASE not set above ---
if "%CONDA_BASE%"=="" if exist "C:\Users\picarro\miniconda3\Scripts\activate.bat" set CONDA_BASE=C:\Users\picarro\miniconda3
if "%CONDA_BASE%"=="" if exist "C:\ProgramData\miniconda3\Scripts\activate.bat"   set CONDA_BASE=C:\ProgramData\miniconda3
if "%CONDA_BASE%"=="" if exist "C:\ProgramData\Miniconda3\Scripts\activate.bat"   set CONDA_BASE=C:\ProgramData\Miniconda3
if "%CONDA_BASE%"=="" if exist "C:\ProgramData\Anaconda3\Scripts\activate.bat"    set CONDA_BASE=C:\ProgramData\Anaconda3
if "%CONDA_BASE%"=="" if exist "%USERPROFILE%\miniconda3\Scripts\activate.bat"    set CONDA_BASE=%USERPROFILE%\miniconda3
if "%CONDA_BASE%"=="" if exist "%USERPROFILE%\Miniconda3\Scripts\activate.bat"    set CONDA_BASE=%USERPROFILE%\Miniconda3
if "%CONDA_BASE%"=="" if exist "%USERPROFILE%\Anaconda3\Scripts\activate.bat"     set CONDA_BASE=%USERPROFILE%\Anaconda3
if "%CONDA_BASE%"=="" if exist "C:\miniconda3\Scripts\activate.bat"               set CONDA_BASE=C:\miniconda3

if "%CONDA_BASE%"=="" (
    echo.
    echo ERROR: Could not find a conda installation.
    echo Please open run.bat in a text editor and set CONDA_BASE at the top.
    echo Example:  set CONDA_BASE=C:\ProgramData\miniconda3
    echo.
    pause
    exit /b 1
)

echo Using conda at: %CONDA_BASE%

call "%CONDA_BASE%\Scripts\activate.bat" "%CONDA_BASE%"
call conda activate linux-viewer
if errorlevel 1 (
    echo.
    echo ERROR: Could not activate the "linux-viewer" conda environment.
    echo Run this once to create it:
    echo   conda env create -f environment_linux.yml
    echo.
    pause
    exit /b 1
)

python "%~dp0pi_viewer_dash.py"
pause
