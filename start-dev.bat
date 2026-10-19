@echo off
title Aquarient CRM Health — Dev Server

echo.
echo  ===============================================
echo   Aquarient CRM Health ^& Data Quality Platform
echo   Local Development Server
echo  ===============================================
echo.

:: Move into the project folder (works even if you run the bat from elsewhere)
cd /d "%~dp0"

:: Already running? Just open it instead of starting a second copy on another port.
netstat -ano | findstr "LISTENING" | findstr ":5173 " >nul
if %ERRORLEVEL% equ 0 (
    echo  [INFO] The website is already running - opening http://localhost:5173
    start http://localhost:5173
    timeout /t 3 /nobreak >nul
    exit /b 0
)

:: Check Node is installed
where node >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo  [ERROR] Node.js not found.
    echo  Download and install it from https://nodejs.org then try again.
    echo.
    pause
    exit /b 1
)

:: Check npm is installed
where npm >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo  [ERROR] npm not found. Please reinstall Node.js from https://nodejs.org
    echo.
    pause
    exit /b 1
)

:: Install dependencies if node_modules is missing
if not exist "node_modules\" (
    echo  [INFO] node_modules not found — installing dependencies...
    echo.
    npm install
    if %ERRORLEVEL% neq 0 (
        echo.
        echo  [ERROR] npm install failed. Check the errors above and try again.
        pause
        exit /b 1
    )
    echo.
)

:: Check .env.local exists
if not exist ".env.local" (
    echo  [WARN] .env.local not found — copying from .env.example
    copy ".env.example" ".env.local" >nul
    echo  [WARN] Please edit .env.local with your settings before using the app.
    echo.
)

echo  [INFO] Starting the dev server...
echo  [INFO] The app will open at: http://localhost:5173
echo.
echo  Press Ctrl+C to stop the server.
echo.

:: Open the browser after a short delay (2 seconds)
start "" /b cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:5173"

:: Start Vite dev server
npm run dev

echo.
echo  Dev server stopped.
pause
