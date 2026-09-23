@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto run
where py >nul 2>nul
if errorlevel 1 (python -m venv .venv) else (py -3 -m venv .venv)
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto fail
:run
.venv\Scripts\python.exe -m streamlit run app.py --server.address localhost
if errorlevel 1 goto fail
exit /b 0
:fail
echo Install Python 3.11+ and check your internet connection. See START_HERE.txt.
pause
exit /b 1