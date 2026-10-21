@echo off
title Aquarient CRM Health — Frontend (Mock API)

echo.
echo  ===============================================
echo   Aquarient CRM Health ^& Data Quality Platform
echo   Frontend Dev Server  ^|  Built-in Mock API
echo  ===============================================
echo.

cd /d "%~dp0frontend"

:: ---- Check Node ----
where node >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo  [ERROR] Node.js not found. Install it from https://nodejs.org
    pause & exit /b 1
)

:: ---- Install deps if missing ----
if not exist "node_modules\" (
    echo  [INFO] First run — installing npm packages...
    npm install
    if %ERRORLEVEL% neq 0 ( echo  [ERROR] npm install failed. & pause & exit /b 1 )
    echo.
)

:: ---- Force DEV_API=true in .env.local so the built-in mock API is used ----
::      (no real backend needed in this mode)
if not exist ".env.local" (
    copy ".env.example" ".env.local" >nul
)

:: Replace or add DEV_API line
powershell -NoProfile -Command ^
  "$f='.env.local'; $c=[IO.File]::ReadAllText($f); if($c -match '(?m)^DEV_API\s*='){$c=$c -replace '(?m)^DEV_API\s*=.*$','DEV_API=true'}else{$c+=\"`r`nDEV_API=true`r`n\"}; [IO.File]::WriteAllText($f,$c)"

echo  [INFO] DEV_API set to true  ^(built-in mock API, no backend needed^)
echo  [INFO] Starting frontend at http://localhost:5173
echo.
echo  Press Ctrl+C in this window to stop.
echo.

:: Open browser after 3 s
start "" /b cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:5173"

npm run dev

echo.
echo  Server stopped.
pause
