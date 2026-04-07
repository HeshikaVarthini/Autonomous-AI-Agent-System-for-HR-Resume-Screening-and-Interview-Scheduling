@echo off
cd /d "%~dp0"
REM If port 8000 is in use, run stop.bat first to free it.
REM Prefer Python 3.10; create venv if missing and install deps
set PYEXE=py -3.10
where py >nul 2>&1 && py -3.10 -c "import sys; exit(0)" 2>nul || set PYEXE=python
if not exist ".venv\Scripts\python.exe" (
    echo Creating .venv...
    %PYEXE% -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -r requirements.txt -q
python main.py
pause
