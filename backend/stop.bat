@echo off
REM Free port 8000 so the server can start (kills any process using it)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    taskkill /PID %%a /F 2>nul
    echo Killed process %%a that was using port 8000.
)
echo Done. You can run run.bat again.
pause
