@echo off
call C:/Users/Baltazar/miniconda3/Scripts/activate.bat C:/Users/Baltazar/miniconda3/envs/myConda
python "C:/Users/Baltazar/Desktop/Data Retriever/data_retriever5.py"

:prompt
echo Work done. Do you want to close this window? (y/n):
set /p choice=
if /i "%choice%"=="y" (
    call <path_to_conda>\Scripts\deactivate.bat
    exit
) else if /i "%choice%"=="n" goto prompt
