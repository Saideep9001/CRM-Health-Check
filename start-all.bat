@echo off
title Aquarient CRM Health — Starting All

echo.
echo  ===============================================
echo   Aquarient CRM Health ^& Data Quality Platform
echo   Backend (FastAPI) + Frontend (Vite)
echo  ===============================================
echo.

cd /d "%~dp0"

:: ---- Set DEV_API=false so Vite proxies to the real backend ----
if not exist ".env.local" (
    copy ".env.example" ".env.local" >nul
)

powershell -NoProfile -Command ^
  "$f='.env.local'; $c=[IO.File]::ReadAllText($f); if($c -match '(?m)^DEV_API\s*='){$c=$c -replace '(?m)^DEV_API\s*=.*$','DEV_API=false'}else{$c+=\"`r`nDEV_API=false`r`n\"}; [IO.File]::WriteAllText($f,$c)"

echo  [INFO] DEV_API set to false  ^(proxying to real backend on port 8000^)
echo.

echo  [1/2] Launching Backend ^(FastAPI^) in a new window...
start "Aquarient — Backend API" cmd /k start-backend.bat

echo  [2/2] Launching Frontend ^(Vite^) in a new window...
start "Aquarient — Frontend" cmd /k start-dev.bat

echo.
echo  Both servers are starting in separate windows.
echo.
echo  - Backend API:  http://localhost:8000
echo  - API Docs:     http://localhost:8000/docs
echo  - Frontend:     http://localhost:5173
echo.
echo  Wait ~5 seconds for both servers to finish starting,
echo  then open http://localhost:5173 in your browser.
echo.
pause
