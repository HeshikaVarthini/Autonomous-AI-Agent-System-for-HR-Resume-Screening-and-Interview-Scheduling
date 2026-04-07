@echo off
cd /d "%~dp0backend"
echo Running FormWatcher backend from: %CD%
py -3.10 -m pip install -r requirements.txt -q 2>nul
py -3.10 main.py
pause
