@echo off
title Aquarient CRM Health - Backend API

echo.
echo  ===============================================
echo   Aquarient CRM Health - Backend API (FastAPI)
echo  ===============================================
echo.

cd /d "%~dp0backend"

:: Two backends on the same port answer requests at random (old and new code mixed) - never start a second one.
netstat -ano | findstr "LISTENING" | findstr ":8000 " >nul
if %ERRORLEVEL% equ 0 (
    echo  [INFO] The backend is already running on port 8000 - not starting a second copy.
    echo  [INFO] To restart it, close its window first ^(or press Ctrl+C in it^).
    echo.
    pause
    exit /b 0
)

where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo  [ERROR] Python not found. Install Python 3.12 from https://www.python.org then try again.
    pause
    exit /b 1
)

:: Create the virtual environment and install packages on first run
if not exist ".venv\Scripts\python.exe" (
    echo  [INFO] First run - creating Python environment and installing packages...
    python -m venv .venv
    ".venv\Scripts\python" -m pip install --disable-pip-version-check -q -r requirements.txt
    if %ERRORLEVEL% neq 0 (
        echo  [ERROR] Package install failed. Check the errors above.
        pause
        exit /b 1
    )
)

if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo  [WARN] Created backend\.env - add your Salesforce Connected App keys to it.
    echo.
)

echo  [INFO] API running at http://localhost:8000  (docs: http://localhost:8000/docs)
echo  [INFO] Start the website separately with start-dev.bat
echo  Press Ctrl+C to stop.
echo.

".venv\Scripts\python" -m uvicorn app.main:app --reload --port 8000

echo.
echo  Backend stopped.
pause
