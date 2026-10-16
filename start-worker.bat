@echo off
title Aquarient CRM Health - Health check worker

echo.
echo  ===============================================
echo   Aquarient CRM Health - Health check worker
echo  ===============================================
echo.
echo  Only needed when backend\.env has JOB_MODE=external.
echo  (With the default JOB_MODE=embedded, start-backend.bat runs checks itself.)
echo  You can start several of these to run more checks at once.
echo.

cd /d "%~dp0backend"

if not exist ".venv\Scripts\python.exe" (
    echo  [ERROR] Run start-backend.bat once first to set up the Python environment.
    pause
    exit /b 1
)

".venv\Scripts\python" -m app.worker

echo.
echo  Worker stopped.
pause
